let equityChart = null;
let currentChartTF = 'All Time'; 

window.addEventListener('pywebviewready', function() {
    loadPortfolios();
});

function updateChartTimeframe(tf, btnElement) {
    currentChartTF = tf;
    
    // Reset all buttons to inactive styling
    document.querySelectorAll('.tf-btn').forEach(btn => {
        btn.className = 'tf-btn text-zen-gray px-3 py-1 hover:text-white transition';
    });
    
    // Set the clicked button to active styling
    btnElement.className = 'tf-btn bg-white/10 text-white px-3 py-1 rounded shadow-sm transition';
    
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
        const data = await pywebview.api.get_dashboard_data(id, currentChartTF);
        updateDashboard(data);
    } catch (e) {
        console.error("Error loading data:", e);
    }
}

function updateDashboard(data) {
    if (!data) return;

    document.getElementById('val-account').textContent = `$${data.total_account.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
    document.getElementById('val-cash').textContent = `$${data.total_cash.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
    
    const unrealEl = document.getElementById('val-unreal');
    unrealEl.textContent = `${data.unreal_dlr >= 0 ? '+' : ''}$${data.unreal_dlr.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})} (${data.unreal_pct >= 0 ? '+' : ''}${data.unreal_pct.toFixed(2)}%)`;
    unrealEl.className = data.unreal_dlr >= 0 ? 'text-3xl font-semibold tracking-tight text-[#9FFF40]' : 'text-3xl font-semibold tracking-tight text-[#E63946]';

    const realEl = document.getElementById('val-real');
    realEl.textContent = `${data.realized_gl >= 0 ? '+' : ''}$${data.realized_gl.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
    realEl.className = data.realized_gl >= 0 ? 'text-3xl font-semibold tracking-tight text-[#9FFF40]' : 'text-3xl font-semibold tracking-tight text-[#E63946]';

    const holdingsBody = document.getElementById('holdings-body');
    holdingsBody.innerHTML = '';
    data.holdings.forEach(h => {
        const tr = document.createElement('tr');
        tr.className = 'table-row-hover transition-colors';
        const colorClass = h.unreal_dlr >= 0 ? 'text-[#9FFF40]' : 'text-[#E63946]';
        const prefix = h.unreal_dlr >= 0 ? '+' : '';
        tr.innerHTML = `
            <td class="px-5 py-3 font-semibold text-white">${h.ticker}</td>
            <td class="px-5 py-3 text-right">${h.shares.toLocaleString()}</td>
            <td class="px-5 py-3 text-right">$${h.avg_cost.toFixed(2)}</td>
            <td class="px-5 py-3 text-right">$${h.current_price.toFixed(2)}</td>
            <td class="px-5 py-3 text-right font-medium ${colorClass}">${prefix}$${h.unreal_dlr.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}</td>
        `;
        holdingsBody.appendChild(tr);
    });

    const historyBody = document.getElementById('history-body');
    historyBody.innerHTML = '';
    data.history.forEach(h => {
        const tr = document.createElement('tr');
        tr.className = 'table-row-hover transition-colors';
        let typeClass = '';
        if (h.type === 'Buy' || h.type === 'Deposit') typeClass = 'text-[#9FFF40] font-medium';
        else if (h.type === 'Sell' || h.type === 'Withdraw') typeClass = 'text-[#E63946] font-medium';
        
        tr.innerHTML = `
            <td class="px-5 py-3 text-[#888]">${h.date.split(' ')[0]}</td>
            <td class="px-5 py-3 ${typeClass}">${h.type}</td>
            <td class="px-5 py-3 font-semibold text-white">${h.ticker === 'CASH' ? '-' : h.ticker}</td>
            <td class="px-5 py-3 text-right">${h.ticker === 'CASH' ? '-' : h.shares.toLocaleString()}</td>
            <td class="px-5 py-3 text-right">$${h.price.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}</td>
        `;
        historyBody.appendChild(tr);
    });

    drawMainChart(data.chart_dates, data.chart_values);
}

function drawMainChart(labels, dataPoints) {
    const ctx = document.getElementById('equityChart').getContext('2d');
    if (equityChart) equityChart.destroy();
    if (!dataPoints || dataPoints.length === 0) return;

    const isPositive = dataPoints[dataPoints.length - 1] >= dataPoints[0];
    const lineColor = isPositive ? '#9FFF40' : '#E63946';
    const gradient = ctx.createLinearGradient(0, 0, 0, 300);
    gradient.addColorStop(0, isPositive ? 'rgba(159, 255, 64, 0.2)' : 'rgba(230, 57, 70, 0.2)');
    gradient.addColorStop(1, 'rgba(0, 0, 0, 0)');

    equityChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                data: dataPoints,
                borderColor: lineColor,
                backgroundColor: gradient,
                borderWidth: 2,
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
                y: { grid: { color: '#222' }, ticks: { color: '#666' } }
            }
        }
    });
}

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
