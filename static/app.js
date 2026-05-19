// Stock Valuation Frontend

// ── Market state ──────────────────────────────────────────────────────────────
let currentMarket = "global";  // "global" | "cn"

const PLACEHOLDERS = {
    global: "输入股票代码，逗号分隔 (如: AAPL, MSFT, STO:SIVE)",
    cn:     "输入A股代码，逗号分隔 (如: 600519, 000001, 688599)",
};

function apiUrl(path) {
    return currentMarket === "cn" ? `/api/cn${path}` : `/api${path}`;
}

function switchMarket(market) {
    if (market === currentMarket) return;
    currentMarket = market;

    document.getElementById("tab-global").classList.toggle("active", market === "global");
    document.getElementById("tab-cn").classList.toggle("active", market === "cn");
    document.getElementById("tickerInput").placeholder = PLACEHOLDERS[market];

    showStatus("", "");
    loadData();
}

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("tickerInput").placeholder = PLACEHOLDERS[currentMarket];
    document.getElementById("tickerInput").addEventListener("keydown", (e) => {
        if (e.key === "Enter") fetchStocks();
    });
    loadData();
});

async function loadData() {
    try {
        const resp = await fetch(apiUrl("/valuations"));
        const data = await resp.json();
        renderTable(data);
    } catch (e) {
        showStatus("加载缓存数据失败", "error");
    }
}

// 点击任意 .editable-cell 可手动填入数值
document.addEventListener("click", (e) => {
    const cell = e.target.closest("td.editable-cell");
    if (!cell || cell.querySelector("input")) return;
    startEdit(cell);
});

function startEdit(cell) {
    const ticker = cell.dataset.ticker;
    const field  = cell.dataset.field;
    const isPct  = cell.dataset.type === "pct";

    const originalHTML = cell.innerHTML;
    const span = cell.querySelector("span");

    // fmtPct wraps in <span>, fmtVal returns plain text — handle both
    let currentVal = "";
    if (span && !span.classList.contains("val-na")) {
        currentVal = span.textContent.replace("%", "").trim();
    } else if (!span) {
        currentVal = cell.textContent.trim();
    }

    const input = document.createElement("input");
    input.type = "number";
    input.value = currentVal;
    input.step  = "any";
    input.className = "edit-input";
    input.title = isPct ? "输入百分比（如 15.5 代表 15.5%）；留空可清除" : "输入数值；留空可清除";

    // Lock input width to the cell's current pixel width BEFORE clearing content
    const cellPx = cell.clientWidth;
    input.style.width = Math.max(cellPx - 4, 32) + "px";

    cell.innerHTML = "";
    cell.appendChild(input);
    input.focus();
    input.select();

    let committed = false;

    async function commit() {
        if (committed) return;
        committed = true;

        const raw = input.value.trim();
        let value = null;
        if (raw !== "") {
            value = parseFloat(raw);
            if (isNaN(value)) { cell.innerHTML = originalHTML; return; }
            if (isPct) value = value / 100;
        }

        try {
            const resp = await fetch(apiUrl("/update"), {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ ticker, field, value }),
            });
            if (resp.ok) {
                // Update this cell directly — no full table reload, no flash
                if (value === null) {
                    cell.innerHTML = `<span class="val-na">-</span>`;
                } else if (isPct) {
                    const pct = (value * 100).toFixed(2) + "%";
                    const cls = value >= 0 ? "val-positive" : "val-negative";
                    cell.innerHTML = `<span class="${cls}">${pct}</span>`;
                } else {
                    cell.innerHTML = value.toFixed(1);
                }
            } else {
                cell.innerHTML = originalHTML;
            }
        } catch { cell.innerHTML = originalHTML; }
    }

    input.addEventListener("blur", commit);
    input.addEventListener("keydown", (e) => {
        if (e.key === "Enter")  { e.preventDefault(); input.blur(); }
        if (e.key === "Escape") { committed = true; cell.innerHTML = originalHTML; }
    });
}

async function fetchStocks() {
    const input = document.getElementById("tickerInput").value.trim();
    if (!input) {
        showStatus("请输入股票代码", "error");
        return;
    }

    const tickers = input.split(/[,，\s]+/).filter(t => t.length > 0).map(t => t.toUpperCase());
    if (tickers.length === 0) {
        showStatus("请输入有效的股票代码", "error");
        return;
    }

    if (tickers.length > 10) {
        showStatus("单次最多拉取10只股票", "error");
        return;
    }

    const btn = document.getElementById("fetchBtn");
    const loading = document.getElementById("loading");

    btn.disabled = true;
    btn.textContent = "拉取中...";
    loading.classList.remove("hidden");
    loading.textContent = currentMarket === "cn"
        ? `⏳ 正在拉取A股数据，每只股票约需12秒...`
        : `⏳ 正在拉取数据，每只股票约需5-8秒...`;
    showStatus(`正在拉取 ${tickers.join(", ")} ...`, "");

    try {
        const resp = await fetch(apiUrl("/fetch"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tickers }),
        });

        const results = await resp.json();

        if (resp.ok) {
            const success = results.filter(r => !r.error).length;
            const failed = results.filter(r => r.error).length;
            let msg = `完成！成功 ${success} 只`;
            if (failed > 0) msg += `，失败 ${failed} 只`;
            showStatus(msg, "success");

            // Reload all data
            await loadData();
        } else {
            showStatus(results.error || "拉取失败", "error");
        }
    } catch (e) {
        showStatus("请求失败: " + e.message, "error");
    } finally {
        btn.disabled = false;
        btn.textContent = "拉取数据";
        loading.classList.add("hidden");
    }
}

async function deleteStock(ticker) {
    if (!confirm(`确定删除 ${ticker} 的数据？`)) return;

    try {
        await fetch(apiUrl("/delete"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ticker }),
        });
        await loadData();
        showStatus(`已删除 ${ticker}`, "success");
    } catch (e) {
        showStatus("删除失败", "error");
    }
}

function renderTable(data) {
    const container = document.getElementById("tableContainer");

    if (!data || data.length === 0) {
        container.innerHTML = `<div class="loading">暂无数据，请在上方输入股票代码拉取</div>`;
        return;
    }

    // Get period labels from most recently fetched stock that has them
    const withQ = [...data].reverse().find(d => d.quarterLabels && d.quarterLabels.length === 4);
    const withR = [...data].reverse().find(d => d.roicLabels && d.roicLabels.length >= 1);
    const qLabels = (withQ && withQ.quarterLabels) || ["Q1", "Q2", "Q3", "Q4"];
    const rLabels = (withR && withR.roicLabels) || ["Y1", "Y2", "Y3", "Y4"];

    // Display newest-first (matching stockanalysis order)
    const qDisplay = [...qLabels].reverse();  // [Q4_newest, Q3, Q2, Q1_oldest]
    const rDisplay = [...rLabels].reverse();  // [Y4_newest, Y3, Y2, Y1_oldest]

    // Header: Ticker | Metric | Q4..Q1 | EV/FCF | PE | Fwd PE | PS | ROIC Current + FY years | delete
    const thead = `<thead>
        <tr>
            <th rowspan="2" class="col-ticker">Ticker</th>
            <th rowspan="2" class="col-metric-hdr">Margin</th>
            <th colspan="4" class="group-header">Quarterly</th>
            <th colspan="5" class="group-header">Valuation</th>
            <th colspan="${1 + rDisplay.length}" class="group-header">ROIC</th>
            <th rowspan="2"></th>
        </tr>
        <tr>
            ${qDisplay.map(l => `<th>${l}</th>`).join("")}
            <th>EV/FCF</th>
            <th>PE</th>
            <th>Fwd PE</th>
            <th>PS</th>
            <th>Fwd PS</th>
            <th>Current</th>
            ${rDisplay.map(l => `<th>${l}</th>`).join("")}
        </tr>
    </thead>`;

    // Build valuation + ROIC cells (rowspan=3, rendered only on first sub-row)
    function roicCells(row) {
        const t = row.ticker;
        const roicYears = rDisplay.map((_, i) => {
            const key = `ttmRoicY${rDisplay.length - i}`;
            return `<td rowspan="3" class="editable-cell" data-ticker="${t}" data-field="${key}" data-type="pct">${fmtPct(row[key])}</td>`;
        }).join("");
        return `<td rowspan="3" class="editable-cell" data-ticker="${t}" data-field="fcfMultiple" data-type="val">${fmtVal(row.fcfMultiple)}</td>
                <td rowspan="3" class="editable-cell" data-ticker="${t}" data-field="peRatio"     data-type="val">${fmtVal(row.peRatio)}</td>
                <td rowspan="3" class="editable-cell" data-ticker="${t}" data-field="fwdPe"       data-type="val">${fmtVal(row.fwdPe)}</td>
                <td rowspan="3" class="editable-cell" data-ticker="${t}" data-field="psRatio"     data-type="val">${fmtVal(row.psRatio)}</td>
                <td rowspan="3" class="editable-cell" data-ticker="${t}" data-field="fwdPs"       data-type="val">${fmtVal(row.fwdPs)}</td>
                <td rowspan="3" class="editable-cell" data-ticker="${t}" data-field="roicCurrent" data-type="pct">${fmtPct(row.roicCurrent)}</td>
                ${roicYears}
                <td rowspan="3"><button class="delete-btn" onclick="deleteStock('${row.ticker}')" title="删除">✕</button></td>`;
    }

    let tbody = "<tbody>";
    for (const row of data) {
        const dateStr = row.fetchDate ? `<span class="fetch-date">${row.fetchDate}</span>` : "";
        const t = row.ticker;
        tbody += `
        <tr class="stock-row-first">
            <td class="col-ticker" rowspan="3">${row.ticker}${dateStr}</td>
            <td class="col-metric">Gross Margin</td>
            <td class="editable-cell" data-ticker="${t}" data-field="grossMarginQ4" data-type="pct">${fmtPct(row.grossMarginQ4)}</td>
            <td class="editable-cell" data-ticker="${t}" data-field="grossMarginQ3" data-type="pct">${fmtPct(row.grossMarginQ3)}</td>
            <td class="editable-cell" data-ticker="${t}" data-field="grossMarginQ2" data-type="pct">${fmtPct(row.grossMarginQ2)}</td>
            <td class="editable-cell" data-ticker="${t}" data-field="grossMarginQ1" data-type="pct">${fmtPct(row.grossMarginQ1)}</td>
            ${roicCells(row)}
        </tr>
        <tr class="stock-row-mid">
            <td class="col-metric">Oper. Margin</td>
            <td class="editable-cell" data-ticker="${t}" data-field="opMarginQ4" data-type="pct">${fmtPct(row.opMarginQ4)}</td>
            <td class="editable-cell" data-ticker="${t}" data-field="opMarginQ3" data-type="pct">${fmtPct(row.opMarginQ3)}</td>
            <td class="editable-cell" data-ticker="${t}" data-field="opMarginQ2" data-type="pct">${fmtPct(row.opMarginQ2)}</td>
            <td class="editable-cell" data-ticker="${t}" data-field="opMarginQ1" data-type="pct">${fmtPct(row.opMarginQ1)}</td>
        </tr>
        <tr class="stock-row-last">
            <td class="col-metric">Net Margin</td>
            <td class="editable-cell" data-ticker="${t}" data-field="netMarginQ4" data-type="pct">${fmtPct(row.netMarginQ4)}</td>
            <td class="editable-cell" data-ticker="${t}" data-field="netMarginQ3" data-type="pct">${fmtPct(row.netMarginQ3)}</td>
            <td class="editable-cell" data-ticker="${t}" data-field="netMarginQ2" data-type="pct">${fmtPct(row.netMarginQ2)}</td>
            <td class="editable-cell" data-ticker="${t}" data-field="netMarginQ1" data-type="pct">${fmtPct(row.netMarginQ1)}</td>
        </tr>`;
    }
    tbody += "</tbody>";

    container.innerHTML = `<table>${thead}${tbody}</table>`;
}

function fmtPct(v) {
    if (v === null || v === undefined) return `<span class="val-na">-</span>`;
    const pct = (v * 100).toFixed(2) + "%";
    const cls = v >= 0 ? "val-positive" : "val-negative";
    return `<span class="${cls}">${pct}</span>`;
}

function fmtVal(v) {
    if (v === null || v === undefined) return `<span class="val-na">-</span>`;
    const str = v.toFixed(1);
    return str;
}

function showStatus(msg, type) {
    const el = document.getElementById("statusMsg");
    el.textContent = msg;
    el.className = "status-msg" + (type ? " " + type : "");
}
