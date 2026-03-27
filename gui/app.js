let equityChart = null;
let currentChartTF = 'All Time';

// State for Table Sorting
let currentData = null;
let holdSort = { column: 'allocation', asc: false };
let histSort = { column: 'date', asc: false };

// Track the active portfolio id so we can pass it to the auditor
let currentPortfolioId = null;

// Chart timeframe button state — tracked separately from data so a failed
// refresh doesn't leave the button in a misleading active state.
let pendingChartTF = null;

window.addEventListener('pywebviewready', function() {
    loadPortfolios();
});

function updateChartTimeframe(tf, btnElement) {
    pendingChartTF = tf;
    refreshData().then(() => {
        // Only update visual state after data successfully loads
        currentChartTF = pendingChartTF;
        document.querySelectorAll('.tf-btn').forEach(btn => {
            btn.className = 'tf-btn text-zen-gray px-4 py-1.5 hover:text-white transition';
        });
        btnElement.className = 'tf-btn bg-white/10 text-white px-4 py-1.5 rounded shadow-sm transition';
    }).catch(() => {
        pendingChartTF = currentChartTF; // revert on failure
    });
}

async function loadPortfolios() {
    const portfolios = await pywebview.api.get_portfolios();
    const select = document.getElementById('portfolio-select');
    select.innerHTML = '';

    if (Object.keys(portfolios).length === 0) {
        select.innerHTML = '<option>No Portfolios</option>';
        currentPortfolioId = null;
        updateDashboard(null);
        return;
    }

    for (const [name, id] of Object.entries(portfolios)) {
        const option = document.createElement('option');
        option.value = id;
        option.textContent = name;
        select.appendChild(option);
    }
    currentPortfolioId = select.value;
    refreshData();
}

async function changePortfolio() {
    currentPortfolioId = document.getElementById('portfolio-select').value;
    refreshData();
}

async function refreshData() {
    const id = document.getElementById('portfolio-select').value;
    if (!id || id === "No Portfolios") return;

    currentPortfolioId = id;
    document.getElementById('val-account').textContent = "Loading...";

    try {
        const tf = pendingChartTF || currentChartTF;
        currentData = await pywebview.api.get_dashboard_data(id, tf);
        updateDashboard(currentData);
    } catch (e) {
        console.error("Error loading data:", e);
        document.getElementById('val-account').textContent = "Error";
        throw e; // re-throw so updateChartTimeframe can catch it
    }
}

function updateDashboard(data) {
    if (!data) return;

    const datalist = document.getElementById('ticker-suggestions');
    if (datalist && data.unique_tickers) {
        datalist.innerHTML = '';
        data.unique_tickers.forEach(ticker => {
            const opt = document.createElement('option');
            opt.value = ticker;
            datalist.appendChild(opt);
        });
    }

    document.getElementById('val-account').textContent = `$${data.total_account.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;

    let investedPct = 0; let cashPct = 0;
    if (data.total_account > 0) {
        investedPct = (data.total_market / data.total_account) * 100;
        cashPct = (data.total_cash / data.total_account) * 100;
    }
    document.getElementById('bar-invested').style.width = `${Math.max(0, investedPct)}%`;
    document.getElementById('bar-cash').style.width = `${Math.max(0, cashPct)}%`;
    document.getElementById('lbl-invested').textContent = `${investedPct.toFixed(1)}%`;
    document.getElementById('lbl-cash').textContent = `${cashPct.toFixed(1)}% ($${data.total_cash.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})})`;

    const todayEl = document.getElementById('val-today');
    todayEl.textContent = `${data.today_dlr >= 0 ? '+' : ''}$${data.today_dlr.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})} (${data.today_pct >= 0 ? '+' : ''}${data.today_pct.toFixed(2)}%)`;
    todayEl.className = data.today_dlr >= 0 ? 'text-3xl font-semibold tracking-tight tabular-nums text-[#22C55E]' : 'text-3xl font-semibold tracking-tight tabular-nums text-[#EF4444]';

    const unrealEl = document.getElementById('val-unreal');
    unrealEl.textContent = `${data.unreal_dlr >= 0 ? '+' : ''}$${data.unreal_dlr.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})} (${data.unreal_pct >= 0 ? '+' : ''}${data.unreal_pct.toFixed(2)}%)`;
    unrealEl.className = data.unreal_dlr >= 0 ? 'text-3xl font-semibold tracking-tight tabular-nums text-[#22C55E]' : 'text-3xl font-semibold tracking-tight tabular-nums text-[#EF4444]';

    const realEl = document.getElementById('val-real');
    realEl.textContent = `${data.realized_gl >= 0 ? '+' : ''}$${data.realized_gl.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})} (${data.realized_pct >= 0 ? '+' : ''}${data.realized_pct.toFixed(2)}%)`;
    realEl.className = data.realized_gl >= 0 ? 'text-3xl font-semibold tracking-tight tabular-nums text-[#22C55E]' : 'text-3xl font-semibold tracking-tight tabular-nums text-[#EF4444]';

    renderHoldings();
    renderHistory();
    drawMainChart(data.chart_dates, data.chart_values);
}

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
        const colorClass = h.unreal_dlr >= 0 ? 'text-[#22C55E]' : 'text-[#EF4444]';
        const prefix = h.unreal_dlr >= 0 ? '+' : '';
        tr.innerHTML = `
            <td class="px-2 py-3 font-bold cursor-pointer hover:text-zen-green transition" onclick="setTickerInput('${h.ticker}')" title="Click to queue trade">
                ${h.ticker}
            </td>
            <td class="px-2 py-3 text-right text-zen-green bg-zen-green/5">${h.allocation.toFixed(1)}%</td>
            <td class="px-2 py-3 text-right">${h.shares.toLocaleString('en-US', {maximumFractionDigits: 4})}</td>
            <td class="px-2 py-3 text-right">$${h.avg_cost.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 4})}</td>
            <td class="px-2 py-3 text-right">$${h.current_price.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 4})}</td>
            <td class="px-2 py-3 text-right font-semibold ${colorClass}">${prefix}$${h.unreal_dlr.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}</td>
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
        if (h.type === 'Buy' || h.type === 'Deposit') typeClass = 'text-[#22C55E] font-medium bg-[#22C55E]/10 rounded px-2 py-0.5';
        else if (h.type === 'Sell' || h.type === 'Withdraw') typeClass = 'text-[#EF4444] font-medium bg-[#EF4444]/10 rounded px-2 py-0.5';
        else if (h.type === 'Dividend') typeClass = 'text-[#3B82F6] font-medium bg-[#3B82F6]/10 rounded px-2 py-0.5';

        let tickerDisplay = h.ticker;
        let sharesDisplay = h.shares.toLocaleString('en-US', {maximumFractionDigits: 4});
        let priceDisplay = `$${h.price.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 4})}`;
        let glDisplay = '-';
        let glColor = 'text-[#a1a1aa]';

        if (h.ticker === 'CASH') {
            tickerDisplay = 'CASH';
            sharesDisplay = '-';
            priceDisplay = `$${h.shares.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
        } else if (h.type === 'Dividend') {
            sharesDisplay = '-';
            priceDisplay = `+$${h.price.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
        } else if (h.type === 'Sell' && h.trade_gl !== null) {
            glDisplay = `${h.trade_gl >= 0 ? '+' : ''}$${h.trade_gl.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
            glColor = h.trade_gl >= 0 ? 'text-[#22C55E] font-semibold' : 'text-[#EF4444] font-semibold';
        }

        tr.innerHTML = `
            <td class="px-2 py-3 text-[#a1a1aa]">${h.date.split(' ')[0]}</td>
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
    const lineColor = isPositive ? '#22C55E' : '#EF4444';
    const gradient = ctx.createLinearGradient(0, 0, 0, 300);
    gradient.addColorStop(0, isPositive ? 'rgba(34, 197, 94, 0.35)' : 'rgba(239, 68, 68, 0.35)');
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
                x: { grid: { display: false }, ticks: { color: '#888', maxTicksLimit: 6 } },
                y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#a1a1aa' } }
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

async function submitDividend() {
    const id = document.getElementById('portfolio-select').value;
    const ticker = document.getElementById('ticker-input').value.toUpperCase();
    const amount = parseFloat(document.getElementById('price-input').value);

    if (!ticker || isNaN(amount) || amount <= 0) {
        alert("To log a Dividend: Type the Ticker, leave Shares blank, and enter the total payout amount in the 'Price' box."); return;
    }

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

async function openScanner() {
    const cash  = currentData ? currentData.total_cash    : 0;
    const total = currentData ? currentData.total_account : 0;

    document.getElementById('scanner-modal').classList.remove('hidden');
    document.getElementById('scanner-results').innerHTML = `
        <div class="col-span-3 text-center py-16 flex flex-col items-center justify-center">
            <i class="fas fa-satellite-dish fa-spin text-5xl text-indigo-400 mb-6 drop-shadow-[0_0_10px_rgba(129,140,248,0.6)]"></i>
            <h3 class="text-white text-xl font-bold tracking-wider mb-2">Scanning TSX & TSX.V...</h3>
            <p class="text-zen-gray text-sm animate-pulse">Running momentum filters...</p>
        </div>`;

    try {
        const results = await pywebview.api.run_swing_scanner(cash, total);
        renderScannerResults(results);
    } catch(e) {
        document.getElementById('scanner-results').innerHTML =
            `<div class="col-span-3 text-center text-zen-red py-10 font-bold">Scanner Error: ${e}</div>`;
    }
}

function closeScanner() {
    document.getElementById('scanner-modal').classList.add('hidden');
}

function renderScannerResults(results) {
    const container = document.getElementById('scanner-results');
    container.innerHTML = '';

    if (!results || results.length === 0) {
        container.innerHTML = '<div class="col-span-3 text-center text-zen-gray py-10 text-lg border border-dashed border-white/10 rounded-xl bg-white/5">No setups found matching criteria.</div>';
        return;
    }

    const sectorColors = {
        'Energy':      'bg-[#FF5722] text-white border border-[#FFAB91]',
        'Materials':   'bg-[#FBC02D] text-black font-black border border-[#FFF9C4]',
        'Technology':  'bg-[#00BCD4] text-black font-black border border-[#B2EBF2]',
        'Financials':  'bg-[#4CAF50] text-black font-black border border-[#C8E6C9]',
        'Healthcare':  'bg-[#E91E63] text-white border border-[#F8BBD0]',
        'Industrials': 'bg-[#673AB7] text-white border border-[#D1C4E9]',
        'Unknown':     'bg-[#9E9E9E] text-black font-black border border-[#F5F5F5]'
    };

    results.forEach(r => {
        if (r.ticker === "ERROR") {
            container.innerHTML += `<div class="col-span-3 text-center text-zen-red py-2">${r.setup}</div>`;
            return;
        }

        const sColor = sectorColors[r.sector] || 'bg-indigo-600 text-white border border-indigo-400';
        let setupIcon = '<i class="fas fa-bolt text-fuchsia-400"></i>';
        if (r.setup.includes('52-Wk'))         setupIcon = '<i class="fas fa-fire text-rose-500"></i>';
        else if (r.setup.includes('High Vol')) setupIcon = '<i class="fas fa-water text-sky-400"></i>';
        else if (r.setup.includes('Golden'))   setupIcon = '<i class="fas fa-shield-halved text-yellow-400"></i>';

        // Earnings warning badge — critical for overnight swing holds
        const earningsBadge = r.earnings_warning
            ? `<div class="flex items-center gap-1.5 mt-2 px-2 py-1 bg-amber-500/20 border border-amber-500/40 rounded text-amber-400 text-[0.65rem] font-bold uppercase tracking-wider">
                    <i class="fas fa-triangle-exclamation"></i>
                    Earnings ~${r.earnings_date} (${r.earnings_days}d) — overnight risk
               </div>`
            : '';

        container.innerHTML += `
            <div class="bg-white/5 backdrop-blur-md border border-indigo-500/30 rounded-xl p-5 transition relative overflow-hidden flex flex-col h-full hover:border-indigo-400 hover:shadow-[0_0_20px_rgba(99,102,241,0.2)]">
                <div class="flex justify-between items-start mb-2">
                    <div class="flex flex-col items-start gap-1">
                        <h3 class="text-3xl font-extrabold text-white tracking-tight leading-none">${r.ticker}</h3>
                        <div class="flex items-center text-[0.65rem] font-semibold text-zen-gray uppercase tracking-wider mt-1">
                            ${setupIcon}
                            <span class="ml-1.5 opacity-80">${r.setup}</span>
                        </div>
                    </div>
                    <span class="px-2.5 py-1 text-[0.7rem] font-extrabold uppercase tracking-wider rounded border shadow-sm ${sColor}">${r.sector}</span>
                </div>

                ${earningsBadge}

                <div class="space-y-2.5 text-sm tabular-nums flex-1 mt-3 border-t border-white/10 pt-4">
                    <div class="flex justify-between border-b border-white/5 pb-2">
                        <span class="text-zen-gray">Buy Limit:</span>
                        <span class="text-white font-bold max-w-[100px] text-right">$${r.buy_price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 3 })}</span>
                    </div>
                    <div class="flex justify-between border-b border-white/5 pb-2">
                        <span class="text-zen-gray mt-1">Position Size:</span>
                        <div class="flex flex-col items-end leading-tight">
                            <span class="text-white font-bold">${r.shares}</span>
                            <span class="text-[0.65rem] opacity-60 font-normal mt-0.5">($${r.total_cost.toFixed(2)})</span>
                        </div>
                    </div>
                    <div class="flex justify-between border-b border-white/5 pb-2">
                        <span class="text-zen-gray" title="Recommended Stop Trigger">Stop Trigger:</span>
                        <span class="text-[#EF4444] font-bold">$${r.stop_trigger.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 3 })}</span>
                    </div>
                    <div class="flex justify-between border-b border-white/5 pb-2">
                        <span class="text-zen-gray" title="Recommended Stop Limit">Stop Limit:</span>
                        <span class="text-[#EF4444] font-bold opacity-80">$${r.stop_limit.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 3 })}</span>
                    </div>
                    <div class="flex justify-between pt-1">
                        <span class="text-zen-gray">Target:</span>
                        <span class="text-[#22C55E] font-bold">$${r.take_profit.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 3 })}</span>
                    </div>
                </div>
            </div>
        `;
    });
}

async function openAuditor() {
    if (!currentData || !currentData.holdings || currentData.holdings.length === 0) {
        alert("You don't have any active stock holdings to audit.");
        return;
    }

    document.getElementById('auditor-modal').classList.remove('hidden');
    document.getElementById('auditor-results').innerHTML = `
        <div class="col-span-3 text-center py-16 flex flex-col items-center justify-center">
            <i class="fas fa-shield-halved text-5xl text-teal-400 mb-6 animate-pulse drop-shadow-[0_0_10px_rgba(45,212,191,0.6)]"></i>
            <h3 class="text-white text-xl font-bold tracking-wider mb-2">Auditing Current Holdings...</h3>
            <p class="text-zen-gray text-sm animate-pulse">Calculating Trailing Stops & Trend Health...</p>
        </div>`;

    try {
        const activeTickers = currentData.holdings.map(h => h.ticker);
        // FIX: Pass portfolio_id so the auditor uses the correct buy date per portfolio
        const results = await pywebview.api.audit_portfolio(activeTickers, currentPortfolioId);
        renderAuditorResults(results);
    } catch(e) {
        document.getElementById('auditor-results').innerHTML =
            `<div class="col-span-3 text-center text-zen-red py-10 font-bold">Auditor Error: ${e}</div>`;
    }
}

function closeAuditor() {
    document.getElementById('auditor-modal').classList.add('hidden');
}

function renderAuditorResults(results) {
    const container = document.getElementById('auditor-results');
    container.innerHTML = '';

    if (!results || results.length === 0) {
        container.innerHTML = '<div class="col-span-3 text-center text-zen-gray py-10 text-lg border border-dashed border-white/10 rounded-xl bg-white/5">No audit data available.</div>';
        return;
    }

    results.forEach(r => {
        if (r.ticker === "ERROR") {
            container.innerHTML += `<div class="col-span-3 text-center text-zen-red py-2">${r.reason}</div>`;
            return;
        }

        let borderColor = 'border-teal-500/30 hover:border-teal-400 hover:shadow-[0_0_20px_rgba(20,184,166,0.2)]';
        let statusStyle = 'bg-green-500/20 text-green-400 border-green-500/50';

        if (r.status === 'SELL') {
            borderColor = 'border-red-500/50 hover:border-red-400 hover:shadow-[0_0_20px_rgba(239,68,68,0.2)]';
            statusStyle = 'bg-red-500/20 text-red-400 border-red-500/50';
        } else if (r.status === 'TRIM') {
            borderColor = 'border-yellow-500/50 hover:border-yellow-400 hover:shadow-[0_0_20px_rgba(234,179,8,0.2)]';
            statusStyle = 'bg-yellow-500/20 text-yellow-400 border-yellow-500/50';
        }

        container.innerHTML += `
            <div class="bg-white/5 backdrop-blur-md border ${borderColor} rounded-xl p-5 transition relative overflow-hidden flex flex-col h-full">
                <div class="mb-4">
                    <div class="flex justify-between items-start mb-1">
                        <h3 class="text-2xl font-bold text-white tracking-tight">${r.ticker}</h3>
                        <div class="flex flex-col items-end gap-1.5">
                            <span class="px-2 py-0.5 text-[0.65rem] font-extrabold uppercase tracking-widest rounded border ${statusStyle} shadow-sm">${r.status}</span>
                        </div>
                    </div>
                    <p class="${r.color} text-xs font-semibold uppercase tracking-wider opacity-80 mt-1">${r.reason}</p>
                </div>

                <div class="space-y-2.5 text-sm tabular-nums flex-1 mt-2">
                    <div class="flex justify-between border-b border-white/10 pb-2">
                        <span class="text-zen-gray">Current Price:</span>
                        <span class="text-white font-bold">$${r.current_price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 3 })}</span>
                    </div>
                    <div class="flex justify-between border-b border-white/10 pb-2">
                        <span class="text-zen-gray" title="Recommended Trailing Stop Strike Price">Trail Trigger:</span>
                        <span class="text-[#EF4444] font-bold">$${r.stop_trigger.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 3 })}</span>
                    </div>
                    <div class="flex justify-between border-b border-white/10 pb-2">
                        <span class="text-zen-gray" title="Recommended Trailing Stop Limit Price">Trail Limit:</span>
                        <span class="text-[#EF4444] font-bold opacity-80">$${r.stop_limit.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 3 })}</span>
                    </div>
                </div>
            </div>
        `;
    });
}

function setTickerInput(ticker) {
    const input = document.getElementById('ticker-input');
    input.value = ticker;
    input.focus();
    input.classList.add('border-zen-green', 'bg-zen-green/20');
    setTimeout(() => {
        input.classList.remove('border-zen-green', 'bg-zen-green/20');
    }, 300);
}
