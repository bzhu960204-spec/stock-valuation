// Options Chain Module Frontend

let chartInstance = null;
let currentData = null;

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("tickerInput").addEventListener("keydown", (e) => {
        if (e.key === "Enter") fetchOptions();
    });
    loadHistoryList();
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
        loadHistoryList();

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

// ════════════════════════════════════════════════════════════════
//  历史快照功能
// ════════════════════════════════════════════════════════════════

let currentHistorySnapshots = []; // 原始顺序（旧→新）
let currentModalTicker = "";
let readingChartInstance = null;

async function loadHistoryList() {
    try {
        const resp = await fetch("/api/options/history");
        const tickers = await resp.json();
        const container = document.getElementById("tickerList");
        if (!tickers || tickers.length === 0) {
            container.innerHTML = '<span style="color:#71767b;font-size:0.85rem">暂无历史数据，查询后自动保存</span>';
            return;
        }
        container.innerHTML = tickers.map(t => `
            <div class="ticker-chip" onclick="openHistoryModal('${t.ticker}', this)">
                <span>${t.ticker}</span>
                <span class="chip-count">${t.count} 条</span>
            </div>
        `).join("");
    } catch (e) {
        console.error("Failed to load history:", e);
    }
}

// ── Modal（快照列表） ────────────────────────────────────────────

async function openHistoryModal(ticker, chipEl) {
    document.querySelectorAll(".ticker-chip").forEach(c => c.classList.remove("active"));
    if (chipEl) chipEl.classList.add("active");
    currentModalTicker = ticker;

    try {
        const resp = await fetch(`/api/options/history/${encodeURIComponent(ticker)}`);
        const data = await resp.json();
        currentHistorySnapshots = data.snapshots || [];
        renderHistoryModal(ticker, currentHistorySnapshots);
        document.getElementById("historyModal").classList.remove("hidden");
    } catch (e) {
        console.error("Failed to load ticker history:", e);
    }
}

function renderHistoryModal(ticker, snapshots) {
    document.getElementById("modalTitle").textContent = `${ticker} — ${snapshots.length} 条历史快照`;
    const body = document.getElementById("modalBody");

    if (!snapshots.length) {
        body.innerHTML = `<p style="padding:20px;color:#71767b">暂无快照</p>`;
        return;
    }

    // 倒序展示（最新在上）
    const rows = [...snapshots].reverse().map((snap, ri) => {
        const origIdx = snapshots.length - 1 - ri;
        const summary = snap.expirationSummary || [];
        const totalCallOI = summary.reduce((s, r) => s + r.callOI, 0);
        const totalPutOI  = summary.reduce((s, r) => s + r.putOI,  0);
        const cpr = totalPutOI > 0 ? (totalCallOI / totalPutOI).toFixed(2) : "—";
        return `
            <div class="modal-snap-row" onclick="openReadingMode(${origIdx})">
                <span class="modal-snap-time">📸 ${snap.snapshotTime}</span>
                <span class="modal-snap-stats">
                    <span>Call OI: <b>${totalCallOI.toLocaleString()}</b></span>
                    <span>Put OI: <b>${totalPutOI.toLocaleString()}</b></span>
                    <span>CPR: <b>${cpr}</b></span>
                    <span style="color:#555f6a">${summary.length} 个到期日</span>
                </span>
                <span class="modal-snap-arrow">&#8250;</span>
            </div>
        `;
    }).join("");
    body.innerHTML = rows;
}

function closeHistoryModal(event) {
    // 点击遮罩层关闭（点击内容框不关闭）
    if (event && event.target !== document.getElementById("historyModal")) return;
    document.getElementById("historyModal").classList.add("hidden");
}

// ── 阅读模式（完整快照：柱状图 + CPR 表 + 期权链） ────────────────

function openReadingMode(origIdx) {
    const snap = currentHistorySnapshots[origIdx];
    if (!snap) return;

    // 关闭 Modal，进入阅读模式
    document.getElementById("historyModal").classList.add("hidden");
    document.getElementById("readingTitle").textContent =
        `${currentModalTicker}  •  📸 ${snap.snapshotTime}`;

    const expData = snap.expirationData || {};
    const expirations = Object.keys(expData).sort();
    const firstExp  = expirations[0] || "";
    const expOptions = expirations.map(e => `<option value="${e}">${e}</option>`).join("");
    const hasChain  = expirations.length > 0;

    document.getElementById("readingContent").innerHTML = `
        <!-- 柱状图：选定到期日各行权价 Call/Put -->
        <div class="options-card" style="margin-top:0">
            <h3>期权链行权价分布</h3>
            <div style="display:flex;align-items:center;gap:16px;margin-bottom:12px;flex-wrap:wrap">
                <div class="chain-controls" style="margin:0">
                    <span>到期日:</span>
                    <select id="readingExpSelect" onchange="updateReadingView(${origIdx}, this.value)">
                        ${expOptions}
                    </select>
                </div>
                <div class="tab-bar" style="margin:0" id="readingTabBar">
                    <button class="active" onclick="switchReadingMetric('openInterest', this, ${origIdx})">持仓量 (OI)</button>
                    <button onclick="switchReadingMetric('volume', this, ${origIdx})">成交量</button>
                    <button onclick="switchReadingMetric('impliedVolatility', this, ${origIdx})">隐含波动率 (%)</button>
                </div>
            </div>
            <div class="legend-info">
                <span><span class="dot dot-call"></span>Call</span>
                <span><span class="dot dot-put"></span>Put</span>
            </div>
            <div class="chart-wrapper">
                <canvas id="readingChart"></canvas>
            </div>
        </div>

        <!-- 价格链表格（紧贴柱状图，随到期日联动） -->
        ${hasChain ? `
        <div class="cpr-section">
            <h4>期权价格明细</h4>
            <div class="chain-table-wrapper table-wrapper" id="readingChainTable">
                ${buildChainTable(expData[firstExp])}
            </div>
        </div>` : ""}

        <!-- 各到期日 Call/Put OI 分布 -->
        ${buildCprTableHtml(snap)}
    `;

    drawReadingChart(origIdx, firstExp, "openInterest");
    document.getElementById("readingMode").classList.remove("hidden");
}

function buildCprTableHtml(snap) {
    const summary = snap.expirationSummary || [];
    if (!summary.length) return "";
    const rows = summary.map(row => {
        const cpr = row.cpr;
        let cprHtml = "—", biasHtml = "";
        if (cpr !== null) {
            let cls = "cpr-neutral", bt = "中性", bc = "bias-neutral";
            if (cpr >= 1.2)      { cls = "cpr-bullish"; bt = "偏多"; bc = "bias-bull"; }
            else if (cpr <= 0.8) { cls = "cpr-bearish"; bt = "偏空"; bc = "bias-bear"; }
            else if (cpr > 1)    { cls = "cpr-bullish"; }
            else if (cpr < 1)    { cls = "cpr-bearish"; }
            cprHtml  = `<span class="${cls}">${cpr.toFixed(2)}</span>`;
            biasHtml = `<span class="bias-tag ${bc}">${bt}</span>`;
        }
        return `<tr>
            <td>${row.expiration}</td>
            <td class="num-cell">${row.callOI.toLocaleString()}</td>
            <td class="num-cell">${row.putOI.toLocaleString()}</td>
            <td class="num-cell">${cprHtml}</td>
            <td>${biasHtml}</td>
        </tr>`;
    }).join("");
    return `
        <div class="cpr-section">
            <h4>各到期日 CPR 汇总</h4>
            <div class="table-wrapper">
                <table class="cpr-table">
                    <thead><tr>
                        <th>到期日</th>
                        <th style="text-align:right">Call OI</th>
                        <th style="text-align:right">Put OI</th>
                        <th style="text-align:right">CPR</th>
                        <th>多空偏向</th>
                    </tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        </div>
    `;
}

function drawReadingChart(origIdx, expiration, metric) {
    const snap = currentHistorySnapshots[origIdx];
    if (!snap) return;
    const expData = (snap.expirationData || {})[expiration];
    if (!expData) return;

    const ctx = document.getElementById("readingChart").getContext("2d");
    if (readingChartInstance) readingChartInstance.destroy();

    const { strikes, calls, puts } = expData;
    const callMap = {}, putMap = {};
    calls.forEach(c => { callMap[c.strike] = c[metric] || 0; });
    puts.forEach(p  => { putMap[p.strike]  = p[metric] || 0; });

    const callValues = strikes.map(s => callMap[s] || 0);
    const putValues  = strikes.map(s => -(putMap[s] || 0));
    const labels     = strikes.map(s => s % 1 === 0 ? String(s | 0) : String(s));

    const metricLabels = {
        openInterest:      "持仓量 (Open Interest)",
        volume:            "成交量 (Volume)",
        impliedVolatility: "隐含波动率 IV (%)",
    };

    readingChartInstance = new Chart(ctx, {
        type: "bar",
        data: {
            labels,
            datasets: [
                {
                    label: "Call",
                    data: callValues,
                    backgroundColor: "rgba(0,186,124,0.7)",
                    borderColor: "rgba(0,186,124,1)",
                    borderWidth: 1,
                },
                {
                    label: "Put",
                    data: putValues,
                    backgroundColor: "rgba(244,33,46,0.7)",
                    borderColor: "rgba(244,33,46,1)",
                    borderWidth: 1,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { intersect: false, mode: "index" },
            plugins: {
                title: {
                    display: true,
                    text: metricLabels[metric] || metric,
                    color: "#e7e9ea",
                    font: { size: 14 },
                },
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: ctx => {
                            const val = Math.abs(ctx.raw);
                            if (metric === "impliedVolatility") return `${ctx.dataset.label}: ${val.toFixed(1)}%`;
                            return `${ctx.dataset.label}: ${val.toLocaleString()}`;
                        },
                    },
                },
            },
            scales: {
                x: {
                    title: { display: true, text: "行权价 (Strike)", color: "#8899a6" },
                    ticks: { color: "#8899a6", maxRotation: 45, autoSkip: true, maxTicksLimit: 30 },
                    grid: { color: "#1e2732" },
                },
                y: {
                    title: { display: true, text: metricLabels[metric] || metric, color: "#8899a6" },
                    ticks: {
                        color: "#8899a6",
                        callback: v => metric === "impliedVolatility"
                            ? Math.abs(v).toFixed(0) + "%"
                            : Math.abs(v).toLocaleString(),
                    },
                    grid: { color: "#1e2732" },
                },
            },
        },
    });
}

// 切换到期日 → 更新图表 + 链表格
function updateReadingView(origIdx, expiration) {
    const activeTab = document.querySelector("#readingTabBar button.active");
    const metric = activeTab ? activeTab.dataset.metric || "openInterest" : "openInterest";
    drawReadingChart(origIdx, expiration, metric);

    const snap = currentHistorySnapshots[origIdx];
    if (snap && snap.expirationData) {
        document.getElementById("readingChainTable").innerHTML =
            buildChainTable(snap.expirationData[expiration]);
    }
}

// 切换指标 tab → 只重绘图表
function switchReadingMetric(metric, btn, origIdx) {
    document.querySelectorAll("#readingTabBar button").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    btn.dataset.metric = metric;
    const expiration = document.getElementById("readingExpSelect").value;
    drawReadingChart(origIdx, expiration, metric);
}

function updateReadingChain(origIdx, expiration) {
    const snap = currentHistorySnapshots[origIdx];
    if (!snap || !snap.expirationData) return;
    document.getElementById("readingChainTable").innerHTML =
        buildChainTable(snap.expirationData[expiration]);
}

function closeReadingMode() {
    document.getElementById("readingMode").classList.add("hidden");
    if (readingChartInstance) { readingChartInstance.destroy(); readingChartInstance = null; }
    // 回到列表 Modal
    document.getElementById("historyModal").classList.remove("hidden");
}

// ── 期权链侧边表格 ────────────────────────────────────────────────

function buildChainTable(expData) {
    if (!expData || !expData.strikes || expData.strikes.length === 0) {
        return "<p style='color:#71767b;font-size:0.85rem;padding:8px 0'>暂无链数据</p>";
    }
    const { strikes, calls, puts } = expData;
    const callMap = {}, putMap = {};
    calls.forEach(c => { callMap[c.strike] = c; });
    puts.forEach(p  => { putMap[p.strike]  = p; });

    const rows = strikes.map(s => {
        const c = callMap[s] || {}, p = putMap[s] || {};
        const fmt   = v => v != null && v !== 0 ? Number(v).toLocaleString() : '<span class="dim">—</span>';
        const fmtP  = v => v != null && v !== 0 ? Number(v).toFixed(2)       : '<span class="dim">—</span>';
        const fmtIV = v => v != null && v !== 0 ? Number(v).toFixed(1) + "%" : '<span class="dim">—</span>';
        return `<tr>
            <td class="call-cell">${fmt(c.openInterest)}</td>
            <td class="call-cell">${fmt(c.volume)}</td>
            <td class="call-cell">${fmtIV(c.impliedVolatility)}</td>
            <td class="call-cell">${fmtP(c.lastPrice)}</td>
            <td class="strike-col">${s % 1 === 0 ? s.toFixed(0) : s}</td>
            <td class="put-cell">${fmtP(p.lastPrice)}</td>
            <td class="put-cell">${fmtIV(p.impliedVolatility)}</td>
            <td class="put-cell">${fmt(p.volume)}</td>
            <td class="put-cell">${fmt(p.openInterest)}</td>
        </tr>`;
    }).join("");

    return `<table class="chain-table">
        <thead>
            <tr>
                <th colspan="4" class="call-hdr">── Call ──</th>
                <th class="strike-col"></th>
                <th colspan="4" class="put-hdr">── Put ──</th>
            </tr>
            <tr>
                <th>OI</th><th>Vol</th><th>IV</th><th>Last</th>
                <th class="strike-col">Strike</th>
                <th>Last</th><th>IV</th><th>Vol</th><th>OI</th>
            </tr>
        </thead>
        <tbody>${rows}</tbody>
    </table>`;
}

// ── 删除 ─────────────────────────────────────────────────────────

async function deleteCurrentTicker() {
    if (!currentModalTicker) return;
    if (!confirm(`确定删除 ${currentModalTicker} 的所有历史快照？`)) return;
    try {
        await fetch("/api/options/delete-history", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ticker: currentModalTicker }),
        });
        document.getElementById("historyModal").classList.add("hidden");
        currentHistorySnapshots = [];
        currentModalTicker = "";
        loadHistoryList();
    } catch (e) {
        console.error("Delete failed:", e);
    }
}
