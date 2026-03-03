let equityChart = null;
let currentChartTF = 'All Time'; 

window.addEventListener('pywebviewready', function() {
    loadPortfolios();
});

function updateChartTimeframe(tf) {
    currentChartTF = tf;
    document.querySelectorAll('.tf-btn').forEach(btn => {
        btn.classList.remove('active');
        if(btn.innerText === tf) btn.classList.add('active');
    });
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
    
    const data = await pywebview.api.get_dashboard_data(id, currentChartTF);
    updateDashboard(data);
}

function updateDashboard(data) {
    if (!data) return;

    document.getElementById('val-account').textContent = `$${data.total_account.toFixed(2)}`;
    document.getElementById('val-cash').textContent = `$${data.total_cash.toFixed(2)}`;
    
    const unrealEl = document.getElementById('val-unreal');
    unrealEl.textContent = `$${data.unreal_dlr.toFixed(2)} (${data.unreal_pct.toFixed(1)}%)`;
    unrealEl.className = data.unreal_dlr >= 0 ? 'positive' : 'negative';

    const realEl = document.getElementById('val-real');
    realEl.textContent = `$${data.realized_gl.toFixed(2)}`;
    realEl.className = data.realized_gl >= 0 ? 'positive' : 'negative';

    const holdingsBody = document.querySelector('#holdings-table tbody');
    holdingsBody.innerHTML = '';
    data.holdings.forEach(h => {
        const tr = document.createElement('tr');
        const colorClass = h.unreal_dlr >= 0 ? 'positive' : 'negative';
        tr.innerHTML = `
            <td><strong>${h.ticker}</strong></td>
            <td>${h.shares.toFixed(2)}</td>
            <td>$${h.avg_cost.toFixed(2)}</td>
            <td>$${h.current_price.toFixed(2)}</td>
            <td class="${colorClass}">$${h.unreal_dlr.toFixed(2)}</td>
        `;
        holdingsBody.appendChild(tr);
    });

    const historyBody = document.querySelector('#history-table tbody');
    historyBody.innerHTML = '';
    data.history.forEach(h => {
        const tr = document.createElement('tr');
        let typeClass = '';
        if (h.type === 'Buy' || h.type === 'Deposit') typeClass = 'positive';
        else if (h.type === 'Sell' || h.type === 'Withdraw') typeClass = 'negative';
        
        tr.innerHTML = `
            <td style="color: #888;">${h.date.split(' ')[0]}</td>
            <td class="${typeClass}">${h.type}</td>
            <td><strong>${h.ticker}</strong></td>
            <td>${h.shares.toFixed(2)}</td>
            <td>$${h.price.toFixed(2)}</td>
        `;
        historyBody.appendChild(tr);
    });

    drawChart(data.chart_dates, data.chart_values);
}

function drawChart(labels, dataPoints) {
    const ctx = document.getElementById('equityChart').getContext('2d');
    
    if (equityChart) {
        equityChart.destroy();
    }

    if (!dataPoints || dataPoints.length === 0) return;

    const isPositive = dataPoints[dataPoints.length - 1] >= dataPoints[0];
    const lineColor = isPositive ? '#76B900' : '#ff4747';
    const gradient = ctx.createLinearGradient(0, 0, 0, 300);
    gradient.addColorStop(0, isPositive ? 'rgba(118, 185, 0, 0.4)' : 'rgba(255, 71, 71, 0.4)');
    gradient.addColorStop(1, 'rgba(0, 0, 0, 0)');

    equityChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Total Account Value',
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
                x: { grid: { display: false }, ticks: { color: '#666', maxTicksLimit: 8 } },
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
