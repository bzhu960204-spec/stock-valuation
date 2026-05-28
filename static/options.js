// Options Chain Module Frontend

let chartInstance = null;
let currentData = null;

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("tickerInput").addEventListener("keydown", (e) => {
        if (e.key === "Enter") fetchOptions();
    });
});

function showStatus(msg, type) {
    const el = document.getElementById("statusMsg");
    el.textContent = msg;
    el.className = "status-msg" + (type ? " " + type : "");
}

async function fetchOptions() {
    const input = document.getElementById("tickerInput").value.trim().toUpperCase();
    if (!input) { showStatus("请输入股票代码", "error"); return; }

    const btn = document.getElementById("fetchBtn");
    const loading = document.getElementById("loading");

    btn.disabled = true;
    btn.textContent = "查询中...";
    loading.classList.remove("hidden");
    showStatus("正在查询 " + input + " 的期权数据...", "");

    try {
        const resp = await fetch("/api/options/chain", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ticker: input }),
        });
        const data = await resp.json();

        if (data.error) {
            showStatus("查询失败: " + data.error, "error");
            return;
        }

        currentData = data;

        // 填充行权日期下拉
        const expSection = document.getElementById("expSection");
        const expSelect = document.getElementById("expSelect");
        expSection.classList.remove("hidden");
        expSelect.innerHTML = "";
        (data.expirations || []).forEach(exp => {
            const opt = document.createElement("option");
            opt.value = exp;
            opt.textContent = exp;
            if (exp === data.expiration) opt.selected = true;
            expSelect.appendChild(opt);
        });

        renderChart(data);
        showStatus(`${data.ticker} — 行权日 ${data.expiration}，共 ${data.strikes.length} 个行权价`, "success");

    } catch (e) {
        showStatus("网络错误: " + e.message, "error");
    } finally {
        btn.disabled = false;
        btn.textContent = "查询";
        loading.classList.add("hidden");
    }
}

async function onExpirationChange() {
    const ticker = currentData?.ticker;
    const expiration = document.getElementById("expSelect").value;
    if (!ticker || !expiration) return;

    const loading = document.getElementById("loading");
    loading.classList.remove("hidden");
    showStatus("正在加载 " + expiration + " 的期权数据...", "");

    try {
        const resp = await fetch("/api/options/chain-by-date", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ticker, expiration }),
        });
        const data = await resp.json();

        if (data.error) {
            showStatus("查询失败: " + data.error, "error");
            return;
        }

        // 保持初次加载的数据
        data.expirations = currentData.expirations;
        data.expirationSummary = currentData.expirationSummary;
        data.snapshotTime = currentData.snapshotTime;
        currentData = data;
        renderChart(data);
        showStatus(`${data.ticker} — 行权日 ${data.expiration}，共 ${data.strikes.length} 个行权价`, "success");

    } catch (e) {
        showStatus("网络错误: " + e.message, "error");
    } finally {
        loading.classList.add("hidden");
    }
}

function renderChart(data) {
    const container = document.getElementById("results");

    container.innerHTML = `
        <div class="options-card">
            <h3>${data.ticker} 期权链</h3>
            <div class="subtitle">行权日: ${data.expiration}</div>
            <div class="tab-bar">
                <button class="active" onclick="switchMetric('openInterest', this)">持仓量 (OI)</button>
                <button onclick="switchMetric('volume', this)">成交量</button>
                <button onclick="switchMetric('impliedVolatility', this)">隐含波动率 (%)</button>
            </div>
            <div class="legend-info">
                <span><span class="dot dot-call"></span>Call</span>
                <span><span class="dot dot-put"></span>Put</span>
            </div>
            <div class="chart-wrapper">
                <canvas id="optionsChart"></canvas>
            </div>
        </div>
        ${renderCprTable(data)}
    `;

    drawChart(data, "openInterest");
}

function renderCprTable(data) {
    const summary = data.expirationSummary;
    if (!summary || summary.length === 0) return "";

    const snapshotHtml = data.snapshotTime
        ? `<div class="snapshot-time">📸 快照时间: ${data.snapshotTime}（CBOE 15 分钟延迟）</div>`
        : "";

    const rows = summary.map(row => {
        const cpr = row.cpr;
        const isSelected = row.expiration === data.expiration ? " selected-row" : "";
        let cprClass = "cpr-neutral", biasText = "中性", biasClass = "bias-neutral";
        if (cpr !== null) {
            if (cpr >= 1.2)      { cprClass = "cpr-bullish"; biasText = "偏多"; biasClass = "bias-bull"; }
            else if (cpr <= 0.8) { cprClass = "cpr-bearish"; biasText = "偏空"; biasClass = "bias-bear"; }
            else if (cpr > 1)    { cprClass = "cpr-bullish"; }
            else if (cpr < 1)    { cprClass = "cpr-bearish"; }
        }
        const cprDisplay = cpr !== null ? `<span class="${cprClass}">${cpr.toFixed(2)}</span>` : "—";
        return `<tr class="${isSelected}">
            <td>${row.expiration}</td>
            <td class="num-cell">${row.callOI.toLocaleString()}</td>
            <td class="num-cell">${row.putOI.toLocaleString()}</td>
            <td class="num-cell">${cprDisplay}</td>
            <td><span class="bias-tag ${biasClass}">${biasText}</span></td>
        </tr>`;
    }).join("");

    return `
        <div class="cpr-section">
            <h4>各到期日 Call / Put OI 分布</h4>
            ${snapshotHtml}
            <div class="table-wrapper">
                <table class="cpr-table">
                    <thead>
                        <tr>
                            <th>到期日</th>
                            <th style="text-align:right">Call OI</th>
                            <th style="text-align:right">Put OI</th>
                            <th style="text-align:right">CPR</th>
                            <th>多空偏向</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        </div>
    `;
}

function switchMetric(metric, btn) {
    // Update active tab
    document.querySelectorAll(".tab-bar button").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    drawChart(currentData, metric);
}

function drawChart(data, metric) {
    const ctx = document.getElementById("optionsChart").getContext("2d");

    if (chartInstance) {
        chartInstance.destroy();
    }

    const strikes = data.strikes;

    // Build lookup maps
    const callMap = {};
    data.calls.forEach(c => { callMap[c.strike] = c[metric] || 0; });
    const putMap = {};
    data.puts.forEach(p => { putMap[p.strike] = p[metric] || 0; });

    const callValues = strikes.map(s => callMap[s] || 0);
    const putValues = strikes.map(s => -(putMap[s] || 0)); // negative for puts

    const labels = strikes.map(s => s.toString());

    const metricLabels = {
        openInterest: "持仓量 (Open Interest)",
        volume: "成交量 (Volume)",
        impliedVolatility: "隐含波动率 IV (%)",
    };

    chartInstance = new Chart(ctx, {
        type: "bar",
        data: {
            labels: labels,
            datasets: [
                {
                    label: "Call",
                    data: callValues,
                    backgroundColor: "rgba(0, 186, 124, 0.7)",
                    borderColor: "rgba(0, 186, 124, 1)",
                    borderWidth: 1,
                },
                {
                    label: "Put",
                    data: putValues,
                    backgroundColor: "rgba(244, 33, 46, 0.7)",
                    borderColor: "rgba(244, 33, 46, 1)",
                    borderWidth: 1,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                intersect: false,
                mode: "index",
            },
            plugins: {
                title: {
                    display: true,
                    text: metricLabels[metric] || metric,
                    color: "#e7e9ea",
                    font: { size: 14 },
                },
                legend: {
                    display: false,
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const val = Math.abs(context.raw);
                            const label = context.dataset.label;
                            if (metric === "impliedVolatility") {
                                return `${label}: ${val.toFixed(1)}%`;
                            }
                            return `${label}: ${val.toLocaleString()}`;
                        },
                    },
                },
            },
            scales: {
                x: {
                    title: {
                        display: true,
                        text: "行权价 (Strike)",
                        color: "#8899a6",
                    },
                    ticks: {
                        color: "#8899a6",
                        maxRotation: 45,
                        autoSkip: true,
                        maxTicksLimit: 30,
                    },
                    grid: { color: "#1e2732" },
                },
                y: {
                    title: {
                        display: true,
                        text: metricLabels[metric] || metric,
                        color: "#8899a6",
                    },
                    ticks: {
                        color: "#8899a6",
                        callback: function(value) {
                            if (metric === "impliedVolatility") {
                                return Math.abs(value).toFixed(0) + "%";
                            }
                            return Math.abs(value).toLocaleString();
                        },
                    },
                    grid: { color: "#1e2732" },
                },
            },
        },
    });
}
