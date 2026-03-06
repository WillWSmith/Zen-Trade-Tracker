let equityChart = null;
let currentChartTF = 'All Time'; 

// State for Table Sorting
let currentData = null;
let holdSort = { column: 'allocation', asc: false };
let histSort = { column: 'date', asc: false };

window.addEventListener('pywebviewready', function() {
    loadPortfolios();
});

function updateChartTimeframe(tf, btnElement) {
    currentChartTF = tf;
    document.querySelectorAll('.tf-btn').forEach(btn => {
        btn.className = 'tf-btn text-zen-gray px-4 py-1.5 hover:text-white transition';
    });
    btnElement.className = 'tf-btn bg-white/10 text-white px-4 py-1.5 rounded shadow-sm transition';
    refreshData();
}

async function loadPortfolios() {
    const portfolios = await pywebview.api.get_portfolios();
    const select = document.getElementById('portfolio-select');
    select.innerHTML = '';
    
    if (Object.keys(portfolios).length === 0) {
        select.innerHTML = '<option>No Portfolios</option>';
        updateDashboard(null);
        return;
    }
    
    for (const [name, id] of Object.entries(portfolios)) {
        const option = document.createElement('option');
        option.value = id;
        option.textContent = name;
        select.appendChild(option);
    }
    refreshData();
}

async function changePortfolio() {
    refreshData();
}

async function refreshData() {
    const id = document.getElementById('portfolio-select').value;
    if (!id || id === "No Portfolios") return;
    
    document.getElementById('val-account').textContent = "Loading...";
    
    try {
        currentData = await pywebview.api.get_dashboard_data(id, currentChartTF);
        updateDashboard(currentData);
    } catch (e) {
        console.error("Error loading data:", e);
    }
}

function updateDashboard(data) {
    if (!data) return;

    // Update Auto-fill Tickers
    const datalist = document.getElementById('ticker-suggestions');
    if (datalist && data.unique_tickers) {
        datalist.innerHTML = '';
        data.unique_tickers.forEach(ticker => {
            const opt = document.createElement('option');
            opt.value = ticker;
            datalist.appendChild(opt);
        });
    }

    // Top Level Summary Cards
    document.getElementById('val-account').textContent = `$${data.total_account.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
    
    // Calculate and Animate Progress Bar
    let investedPct = 0; let cashPct = 0;
    if (data.total_account > 0) {
        investedPct = (data.total_market / data.total_account) * 100;
        cashPct = (data.total_cash / data.total_account) * 100;
    }
    document.getElementById('bar-invested').style.width = `${Math.max(0, investedPct)}%`;
    document.getElementById('bar-cash').style.width = `${Math.max(0, cashPct)}%`;
    document.getElementById('lbl-invested').textContent = `${investedPct.toFixed(1)}%`;
    document.getElementById('lbl-cash').textContent = `${cashPct.toFixed(1)}% ($${data.total_cash.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})})`;

    // Today's Return
    const todayEl = document.getElementById('val-today');
    todayEl.textContent = `${data.today_dlr >= 0 ? '+' : ''}$${data.today_dlr.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})} (${data.today_pct >= 0 ? '+' : ''}${data.today_pct.toFixed(2)}%)`;
    todayEl.className = data.today_dlr >= 0 ? 'text-3xl font-semibold tracking-tight tabular-nums text-[#10B981]' : 'text-3xl font-semibold tracking-tight tabular-nums text-[#EF4444]';

    // Unrealized
    const unrealEl = document.getElementById('val-unreal');
    unrealEl.textContent = `${data.unreal_dlr >= 0 ? '+' : ''}$${data.unreal_dlr.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})} (${data.unreal_pct >= 0 ? '+' : ''}${data.unreal_pct.toFixed(2)}%)`;
    unrealEl.className = data.unreal_dlr >= 0 ? 'text-3xl font-semibold tracking-tight tabular-nums text-[#10B981]' : 'text-3xl font-semibold tracking-tight tabular-nums text-[#EF4444]';

    // Realized
    const realEl = document.getElementById('val-real');
    realEl.textContent = `${data.realized_gl >= 0 ? '+' : ''}$${data.realized_gl.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})} (${data.realized_pct >= 0 ? '+' : ''}${data.realized_pct.toFixed(2)}%)`;
    realEl.className = data.realized_gl >= 0 ? 'text-3xl font-semibold tracking-tight tabular-nums text-[#10B981]' : 'text-3xl font-semibold tracking-tight tabular-nums text-[#EF4444]';

    renderHoldings();
    renderHistory();
    drawMainChart(data.chart_dates, data.chart_values);
}

// Sorting Functions
function sortHoldings(col) {
    if (holdSort.column === col) holdSort.asc = !holdSort.asc;
    else { holdSort.column = col; holdSort.asc = (col === 'ticker'); }
    renderHoldings();
}

function sortHistory(col) {
    if (histSort.column === col) histSort.asc = !histSort.asc;
    else { histSort.column = col; histSort.asc = false; }
    renderHistory();
}

function renderHoldings() {
    if (!currentData) return;
    
    // Sort logic
    let sorted = [...currentData.holdings].sort((a, b) => {
        let valA = a[holdSort.column]; let valB = b[holdSort.column];
        if (typeof valA === 'string') return holdSort.asc ? valA.localeCompare(valB) : valB.localeCompare(valA);
        return holdSort.asc ? valA - valB : valB - valA;
    });

    const body = document.getElementById('holdings-body');
    body.innerHTML = '';
    sorted.forEach(h => {
        const tr = document.createElement('tr');
        tr.className = 'table-row-hover transition-colors';
        const colorClass = h.unreal_dlr >= 0 ? 'text-[#10B981]' : 'text-[#EF4444]';
        const prefix = h.unreal_dlr >= 0 ? '+' : '';
        tr.innerHTML = `
            <td class="px-3 py-3 font-semibold text-white">${h.ticker}</td>
            <td class="px-3 py-3 text-right text-zen-green/80 bg-zen-green/5">${h.allocation.toFixed(1)}%</td>
            <td class="px-3 py-3 text-right">${h.shares.toLocaleString('en-US', {maximumFractionDigits: 4})}</td>
            <td class="px-3 py-3 text-right">$${h.avg_cost.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 4})}</td>
            <td class="px-3 py-3 text-right">$${h.current_price.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 4})}</td>
            <td class="px-3 py-3 text-right font-semibold ${colorClass}">${prefix}$${h.unreal_dlr.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}</td>
        `;
        body.appendChild(tr);
    });
}

function renderHistory() {
    if (!currentData) return;
    
    let sorted = [...currentData.history].sort((a, b) => {
        let valA = a[histSort.column]; let valB = b[histSort.column];
        if (valA === null) valA = -999999999; if (valB === null) valB = -999999999;
        if (typeof valA === 'string') return histSort.asc ? valA.localeCompare(valB) : valB.localeCompare(valA);
        return histSort.asc ? valA - valB : valB - valA;
    });

    const body = document.getElementById('history-body');
    body.innerHTML = '';
    sorted.forEach(h => {
        const tr = document.createElement('tr');
        tr.className = 'table-row-hover transition-colors';
        
        let typeClass = '';
        if (h.type === 'Buy' || h.type === 'Deposit') typeClass = 'text-[#10B981] font-medium bg-[#10B981]/10 rounded px-2 py-0.5';
        else if (h.type === 'Sell' || h.type === 'Withdraw') typeClass = 'text-[#EF4444] font-medium bg-[#EF4444]/10 rounded px-2 py-0.5';
        else if (h.type === 'Dividend') typeClass = 'text-[#3B82F6] font-medium bg-[#3B82F6]/10 rounded px-2 py-0.5'; // Blue for Dividend
        
        let tickerDisplay = h.ticker;
        let sharesDisplay = h.shares.toLocaleString('en-US', {maximumFractionDigits: 4});
        let priceDisplay = `$${h.price.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 4})}`;
        let glDisplay = '-';
        let glColor = 'text-[#888]';

        if (h.ticker === 'CASH') {
            tickerDisplay = 'CASH';
            sharesDisplay = '-';
            priceDisplay = `$${h.shares.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
        } else if (h.type === 'Dividend') {
            sharesDisplay = '-';
            priceDisplay = `+$${h.price.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
        } else if (h.type === 'Sell' && h.trade_gl !== null) {
            glDisplay = `${h.trade_gl >= 0 ? '+' : ''}$${h.trade_gl.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
            glColor = h.trade_gl >= 0 ? 'text-[#10B981] font-semibold' : 'text-[#EF4444] font-semibold';
        }

        tr.innerHTML = `
            <td class="px-2 py-3 text-[#888]">${h.date.split(' ')[0]}</td>
            <td class="px-2 py-3"><span class="${typeClass}">${h.type}</span></td>
            <td class="px-2 py-3 font-semibold text-white">${tickerDisplay}</td>
            <td class="px-2 py-3 text-right">${sharesDisplay}</td>
            <td class="px-2 py-3 text-right">${priceDisplay}</td>
            <td class="px-2 py-3 text-right ${glColor}">${glDisplay}</td>
        `;
        body.appendChild(tr);
    });
}

function drawMainChart(labels, dataPoints) {
    const ctx = document.getElementById('equityChart').getContext('2d');
    if (equityChart) equityChart.destroy();
    if (!dataPoints || dataPoints.length === 0) return;

    const isPositive = dataPoints[dataPoints.length - 1] >= dataPoints[0];
    const lineColor = isPositive ? '#10B981' : '#EF4444'; // Emerald or Red
    const gradient = ctx.createLinearGradient(0, 0, 0, 300);
    gradient.addColorStop(0, isPositive ? 'rgba(16, 185, 129, 0.25)' : 'rgba(239, 68, 68, 0.25)');
    gradient.addColorStop(1, 'rgba(0, 0, 0, 0)');

    equityChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                data: dataPoints,
                borderColor: lineColor,
                backgroundColor: gradient,
                borderWidth: 2.5,
                fill: true,
                pointRadius: 0,
                pointHoverRadius: 6,
                tension: 0.4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { intersect: false, mode: 'index' },
            plugins: { legend: { display: false } },
            scales: {
                x: { grid: { display: false }, ticks: { color: '#666', maxTicksLimit: 6 } },
                y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#888' } }
            }
        }
    });
}

// Logic Actions
async function addPortfolio() {
    const name = prompt("Enter new portfolio name:");
    if (name) { await pywebview.api.add_portfolio(name); loadPortfolios(); }
}
async function editPortfolio() {
    const id = document.getElementById('portfolio-select').value;
    const name = prompt("Enter new name:");
    if (id && name) { await pywebview.api.edit_portfolio(id, name); loadPortfolios(); }
}
async function deletePortfolio() {
    if (confirm("Permanently delete this portfolio?")) {
        const id = document.getElementById('portfolio-select').value;
        await pywebview.api.delete_portfolio(id); loadPortfolios();
    }
}
async function submitTrade(type) {
    const id = document.getElementById('portfolio-select').value;
    const ticker = document.getElementById('ticker-input').value.toUpperCase();
    const shares = parseFloat(document.getElementById('shares-input').value);
    const price = parseFloat(document.getElementById('price-input').value);
    
    if (!ticker || isNaN(shares) || isNaN(price)) {
        alert("Please fill out Ticker, Shares, and Price correctly."); return;
    }
    
    await pywebview.api.add_trade(id, ticker, type, shares, price);
    document.getElementById('shares-input').value = '';
    document.getElementById('price-input').value = '';
    refreshData();
}

async function submitDividend() {
    const id = document.getElementById('portfolio-select').value;
    const ticker = document.getElementById('ticker-input').value.toUpperCase();
    const amount = parseFloat(document.getElementById('price-input').value);
    
    if (!ticker || isNaN(amount) || amount <= 0) {
        alert("To log a Dividend: Type the Ticker, leave Shares blank, and enter the total payout amount in the 'Price' box."); return;
    }
    
    // Dividend is treated as Shares=1, Price=Amount in the DB logic
    await pywebview.api.add_trade(id, ticker, "Dividend", 1.0, amount);
    document.getElementById('shares-input').value = '';
    document.getElementById('price-input').value = '';
    refreshData();
}

async function submitCash(type) {
    const id = document.getElementById('portfolio-select').value;
    const amount = parseFloat(document.getElementById('cash-input').value);
    
    if (isNaN(amount) || amount <= 0) {
        alert("Please enter a valid cash amount."); return;
    }
    
    await pywebview.api.add_trade(id, "CASH", type, amount, 1.0);
    document.getElementById('cash-input').value = '';
    refreshData();
}
