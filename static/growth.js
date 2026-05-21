// Growth Module Frontend

const chartInstances = {};

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("tickerInput").addEventListener("keydown", (e) => {
        if (e.key === "Enter") fetchGrowth();
    });
    loadData();
});

async function loadData() {
    try {
        const resp = await fetch("/api/growth/data");
        const data = await resp.json();
        if (data.length > 0) renderResults(data);
    } catch (e) {
        // 缓存加载失败不提示
    }
}

function showStatus(msg, type) {
    const el = document.getElementById("statusMsg");
    el.textContent = msg;
    el.className = "status-msg" + (type ? " " + type : "");
}

// stockanalysis 财务表格数值均为百万单位
function formatRevenue(val) {
    if (val >= 1000000) return (val / 1000000).toFixed(2) + "T";
    if (val >= 1000)    return (val / 1000).toFixed(2) + "B";
    return val.toFixed(0) + "M";
}

async function fetchGrowth() {
    const input = document.getElementById("tickerInput").value.trim();
    if (!input) { showStatus("请输入股票代码", "error"); return; }

    const tickers = input.split(/[,，\s]+/).filter(t => t.length > 0).map(t => t.toUpperCase());
    if (tickers.length === 0) { showStatus("请输入有效的股票代码", "error"); return; }
    if (tickers.length > 10)  { showStatus("单次最多查询10只股票", "error"); return; }

    const btn     = document.getElementById("fetchBtn");
    const loading = document.getElementById("loading");

    btn.disabled    = true;
    btn.textContent = "查询中...";
    loading.classList.remove("hidden");
    showStatus("正在查询 " + tickers.join(", ") + " ...", "");

    try {
        const resp = await fetch("/api/growth/fetch", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tickers }),
        });
        const data = await resp.json();

        if (resp.ok) {
            // 重新加载全量缓存（包含旧数据）
            const cached = await (await fetch("/api/growth/data")).json();
            renderResults(cached);
            const success = data.filter(d => !d.error).length;
            const failed  = data.filter(d =>  d.error).length;
            let msg = "完成！成功 " + success + " 只";
            if (failed > 0) msg += "，失败 " + failed + " 只";
            showStatus(msg, "success");
        } else {
            showStatus(data.error || "查询失败", "error");
        }
    } catch (e) {
        showStatus("请求失败: " + e.message, "error");
    } finally {
        btn.disabled    = false;
        btn.textContent = "查询";
        loading.classList.add("hidden");
    }
}

function renderResults(data) {
    const container = document.getElementById("results");

    // 销毁旧图表实例
    Object.values(chartInstances).forEach(c => c.destroy());
    Object.keys(chartInstances).forEach(k => delete chartInstances[k]);

    const htmlParts = [];
    const chartJobs = [];

    for (const item of data) {
        if (item.error) {
            htmlParts.push(
                '<div class="error-card"><strong>' + item.ticker + '</strong>: ' + item.error + '</div>'
            );
            continue;
        }

        const canvasId = "chart-" + item.ticker;
        const currency = item.currency || "USD";

        const rows = item.revenue.map(r => {
            const growthText  = r.growth !== null
                ? (r.growth >= 0 ? "+" : "") + (r.growth * 100).toFixed(2) + "%"
                : "-";
            const growthClass = r.growth !== null
                ? (r.growth >= 0 ? "val-positive" : "val-negative")
                : "val-na";
            return "<tr><td class='year-col'>" + r.year + "</td><td>" +
                   formatRevenue(r.revenue) + "</td><td><span class='" +
                   growthClass + "'>" + growthText + "</span></td></tr>";
        }).join("");

        htmlParts.push(
            '<div class="growth-card">' +
            '<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:4px">' +
            '<h3>' + item.ticker + '</h3>' +
            '<button class="delete-btn" onclick="deleteStock(\'' + item.ticker + '\')" title="删除">&#x2715;</button>' +
            '</div>' +
            '<div class="subtitle">' + item.name + ' &nbsp;&middot;&nbsp; 单位：百万 ' + currency + '</div>' +
            '<div class="chart-wrapper"><canvas id="' + canvasId + '"></canvas></div>' +
            '<table class="growth-table"><thead><tr>' +
            '<th>财年</th><th>营收（Millions ' + currency + '）</th><th>同比增长</th>' +
            '</tr></thead><tbody>' + rows + '</tbody></table>' +
            '</div>'
        );

        chartJobs.push({ canvasId, item, currency });
    }

    // 一次性写入 DOM，再渲染图表
    container.innerHTML = htmlParts.join("");
    chartJobs.forEach(function(job) { renderChart(job.canvasId, job.item, job.currency); });
}

function renderChart(canvasId, item, currency) {
    var years    = item.revenue.map(function(r) { return r.year; });
    var revenues = item.revenue.map(function(r) { return r.revenue; });
    var growths  = item.revenue.map(function(r) {
        return r.growth !== null ? parseFloat((r.growth * 100).toFixed(2)) : null;
    });

    var barColors = growths.map(function(g) {
        if (g === null) return "rgba(29,155,240,0.75)";
        return g >= 0 ? "rgba(0,186,124,0.75)" : "rgba(244,33,46,0.75)";
    });
    var barBorderColors = barColors.map(function(c) { return c.replace("0.75", "1"); });

    var pointColors = growths.map(function(g) {
        if (g === null) return "#555";
        return g >= 0 ? "#00ba7c" : "#f4212e";
    });

    var canvas = document.getElementById(canvasId);
    if (!canvas) return;
    var ctx = canvas.getContext("2d");

    chartInstances[canvasId] = new Chart(ctx, {
        type: "bar",
        data: {
            labels: years,
            datasets: [
                {
                    label: "营收 (M " + currency + ")",
                    data: revenues,
                    backgroundColor: barColors,
                    borderColor: barBorderColors,
                    borderWidth: 1,
                    borderRadius: 4,
                    barPercentage: 0.45,
                    categoryPercentage: 0.6,
                    yAxisID: "yRev",
                    order: 2,
                },
                {
                    label: "同比增长 (%)",
                    data: growths,
                    type: "line",
                    borderColor: "#e7e9ea",
                    backgroundColor: "rgba(231,233,234,0.1)",
                    pointBackgroundColor: pointColors,
                    pointRadius: 5,
                    pointHoverRadius: 7,
                    borderWidth: 2,
                    tension: 0.3,
                    yAxisID: "yGrowth",
                    order: 1,
                    spanGaps: true,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            plugins: {
                legend: { labels: { color: "#8899a6", font: { size: 12 } } },
                tooltip: {
                    callbacks: {
                        label: function(ctx) {
                            if (ctx.dataset.yAxisID === "yRev") {
                                return " " + formatRevenue(ctx.raw) + " " + currency;
                            }
                            return ctx.raw !== null
                                ? " " + (ctx.raw >= 0 ? "+" : "") + ctx.raw + "%"
                                : " -";
                        },
                    },
                },
            },
            scales: {
                x: {
                    ticks: { color: "#8899a6" },
                    grid:  { color: "rgba(255,255,255,0.05)" },
                },
                yRev: {
                    position: "left",
                    title: { display: true, text: "百万 " + currency, color: "#8899a6", font: { size: 11 } },
                    ticks: { color: "#8899a6", callback: function(v) { return formatRevenue(v); } },
                    grid:  { color: "rgba(255,255,255,0.05)" },
                },
                yGrowth: {
                    position: "right",
                    title: { display: true, text: "同比增长 %", color: "#8899a6", font: { size: 11 } },
                    ticks: { color: "#8899a6", callback: function(v) { return v + "%"; } },
                    grid:  { drawOnChartArea: false },
                },
            },
        },
    });
}

async function deleteStock(ticker) {
    if (!confirm("确定删除 " + ticker + " 的数据？")) return;
    try {
        await fetch("/api/growth/delete", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ticker }),
        });
        const cached = await (await fetch("/api/growth/data")).json();
        renderResults(cached);
        showStatus("已删除 " + ticker, "success");
    } catch (e) {
        showStatus("删除失败", "error");
    }
}
