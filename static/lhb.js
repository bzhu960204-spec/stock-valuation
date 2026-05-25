/**
 * 龙虎榜前端逻辑 (lhb.js)
 */
(function () {
    const btnFetch      = document.getElementById("btn-fetch");
    const btnFetchRange = document.getElementById("btn-fetch-range");
    const rangeStart    = document.getElementById("range-start");
    const rangeEnd      = document.getElementById("range-end");
    const dateSelect    = document.getElementById("date-select");
    const tbody         = document.getElementById("lhb-body");
    const status        = document.getElementById("status");
    const chips         = document.querySelectorAll(".chip");
    const thExplain       = document.getElementById("th-explain");
    const sortIcon         = document.getElementById("sort-icon");
    const thNetBuy         = document.getElementById("th-netbuy");
    const netBuySortIcon   = document.getElementById("netbuy-sort-icon");

    let allItems    = [];
    let activeChip  = "all";
    let instSort    = null;   // null | "desc" | "asc"  — 解读列（机构数）
    let netBuySort  = null;   // null | "desc" | "asc"  — 净买额列

    // ── 分类判断 ──────────────────────────────────────────────────
    function classify(info) {
        if (!info) return "other";
        if (info.includes("普通席位")) return "normal";
        if (info.includes("买一主买")) return "zhumai";
        if (/\d+家机构买入/.test(info) || info.includes("机构买入")) return "inst";
        if (/\d+家机构卖出/.test(info) || info.includes("机构卖出")) return "inst-sell";
        if (info.includes("买入")) return "fund";
        return "other";
    }

    // ── 筛选 & 渲染 ────────────────────────────────────────────────
    function applyFilter() {
        const filtered = activeChip === "all"
            ? allItems
            : activeChip === "buy-all"
                ? allItems.filter(x => ["normal", "zhumai", "fund", "inst"].includes(classify(x.explain_info)))
                : allItems.filter(x => classify(x.explain_info) === activeChip);

        // 按机构数排序（inst 和 inst-sell 分类下生效）
        if ((activeChip === "inst" || activeChip === "inst-sell") && instSort) {
            filtered.sort((a, b) => {
                const na = parseInt(a.explain_info) || 0;
                const nb = parseInt(b.explain_info) || 0;
                return instSort === "desc" ? nb - na : na - nb;
            });
        }

        // 按净买额排序（所有分类均可用，优先级高于机构数排序）
        if (netBuySort) {
            filtered.sort((a, b) => {
                const na = a.net_buy_amt ?? -Infinity;
                const nb = b.net_buy_amt ?? -Infinity;
                return netBuySort === "desc" ? nb - na : na - nb;
            });
        }

        renderTable(filtered);
        const total = allItems.length;
        const shown = filtered.length;
        const suffix = activeChip === "all" ? "" : `，显示 ${shown}/${total} 条`;
        const base = status.textContent.replace(/，显示.*/, "");
        setStatus(base + suffix);
    }

    function updateSortHeader() {
        const isInst = activeChip === "inst" || activeChip === "inst-sell";
        thExplain.classList.toggle("sortable", isInst);
        sortIcon.style.display = isInst ? "inline" : "none";
        const icons = { null: "&#8693;", desc: "&#8595;", asc: "&#8593;" };
        sortIcon.innerHTML = icons[instSort] ?? "&#8693;";
    }

    function updateNetBuySortHeader() {
        const icons = { null: "&#8693;", desc: "&#8595;", asc: "&#8593;" };
        netBuySortIcon.innerHTML = icons[netBuySort] ?? "&#8693;";
    }

    function fmtAmt(v) {
        if (v == null) return "-";
        return v.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
    function fmtRate(v) {
        if (v == null) return "-";
        return (v * 100).toFixed(2) + "%";
    }
    function fmtPct(v) {
        if (v == null) return "-";
        return v.toFixed(2) + "%";
    }

    function renderTable(items) {
        if (!items || items.length === 0) {
            tbody.innerHTML = '<tr><td colspan="15" style="text-align:center;color:#71767b;padding:40px">暂无数据</td></tr>';
            return;
        }
        tbody.innerHTML = items.map((item, idx) => {
            const rate    = item.change_rate;
            const rateStr = rate != null ? rate.toFixed(2) + "%" : "-";
            const cls     = rate > 0 ? "change-pos" : rate < 0 ? "change-neg" : "";
            const netCls  = item.net_buy_amt != null && item.net_buy_amt > 0 ? "change-pos"
                          : item.net_buy_amt != null && item.net_buy_amt < 0 ? "change-neg" : "";
            return `<tr>
                <td class="col-idx">${idx + 1}</td>
                <td class="col-code">${item.code}</td>
                <td>${item.name}</td>
                <td>${item.explanation || ""}</td>
                <td>${item.explain_info || ""}</td>
                <td class="col-change ${cls}">${rateStr}</td>
                <td class="col-num ${netCls}">${fmtAmt(item.net_buy_amt)}</td>
                <td class="col-num">${fmtAmt(item.buy_amt)}</td>
                <td class="col-num">${fmtAmt(item.sell_amt)}</td>
                <td class="col-num">${fmtAmt(item.billboard_amt)}</td>
                <td class="col-num">${fmtAmt(item.total_mkt_amt)}</td>
                <td class="col-rate">${fmtPct(item.net_buy_rate)}</td>
                <td class="col-rate">${fmtPct(item.billboard_rate)}</td>
                <td class="col-rate">${fmtPct(item.turnover_rate)}</td>
                <td class="col-num">${item.free_mkt_cap != null ? item.free_mkt_cap.toFixed(2) : "-"}</td>
            </tr>`;
        }).join("");
    }

    function setStatus(msg) {
        status.textContent = msg;
    }

    // ── 日期下拉 ───────────────────────────────────────────────────
    async function loadDates() {
        try {
            const resp  = await fetch("/api/lhb/dates");
            const dates = await resp.json();
            dateSelect.innerHTML = '<option value="">-- 选择历史日期 --</option>';
            dates.forEach(d => {
                const opt = document.createElement("option");
                opt.value = d;
                opt.textContent = d;
                dateSelect.appendChild(opt);
            });
        } catch (e) {
            console.error("加载日期列表失败", e);
        }
    }

    // ── 抓取最新数据 ───────────────────────────────────────────────
    async function fetchLatest() {
        btnFetch.disabled = true;
        setStatus("正在抓取最新龙虎榜数据...");
        tbody.innerHTML = "";
        try {
            const resp = await fetch("/api/lhb/fetch", { method: "POST" });
            const data = await resp.json();
            if (data.error) { setStatus("错误: " + data.error); return; }
            setStatus(`交易日: ${data.trade_date}  共 ${data.count} 条`);
            allItems = data.items;
            applyFilter();
            await loadDates();
            dateSelect.value = data.trade_date;
        } catch (e) {
            setStatus("请求失败: " + e.message);
        } finally {
            btnFetch.disabled = false;
        }
    }

    // ── 按日期加载 ─────────────────────────────────────────────────
    async function loadByDate(date) {
        if (!date) return;
        setStatus("加载中...");
        try {
            const resp = await fetch(`/api/lhb/data?date=${encodeURIComponent(date)}`);
            const data = await resp.json();
            if (data.error) { setStatus("错误: " + data.error); return; }
            setStatus(`交易日: ${data.trade_date}  共 ${data.count} 条`);
            allItems = data.items;
            applyFilter();
        } catch (e) {
            setStatus("请求失败: " + e.message);
        }
    }

    // ── 事件绑定 ───────────────────────────────────────────────────
    btnFetch.addEventListener("click", fetchLatest);
    dateSelect.addEventListener("change", () => loadByDate(dateSelect.value));

    btnFetchRange.addEventListener("click", async () => {
        const s = rangeStart.value;
        const e = rangeEnd.value;
        if (!s || !e) { setStatus("请选择起止日期"); return; }
        if (s > e)    { setStatus("起始日期不能晚于结束日期"); return; }
        btnFetchRange.disabled = true;
        setStatus(`正在拉取 ${s} 至 ${e} 的数据...`);
        try {
            const resp = await fetch("/api/lhb/fetch-range", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ start_date: s, end_date: e }),
            });
            const data = await resp.json();
            if (data.error) { setStatus("错误: " + data.error); return; }
            setStatus(`拉取完成：${data.dates_fetched.length} 个交易日，共 ${data.total_records} 条`);
            await loadDates();
            if (data.dates_fetched.length > 0) {
                const latest = data.dates_fetched[data.dates_fetched.length - 1];
                dateSelect.value = latest;
                loadByDate(latest);
            }
        } catch (err) {
            setStatus("请求失败: " + err.message);
        } finally {
            btnFetchRange.disabled = false;
        }
    });

    chips.forEach(chip => {
        chip.addEventListener("click", () => {
            activeChip = chip.dataset.cat;
            if (activeChip !== "inst" && activeChip !== "inst-sell") instSort = null;
            netBuySort = null;
            chips.forEach(c => c.className = "chip");
            chip.classList.add(`active-${activeChip}`);
            updateSortHeader();
            updateNetBuySortHeader();
            applyFilter();
        });
    });

    thExplain.addEventListener("click", () => {
        if (activeChip !== "inst" && activeChip !== "inst-sell") return;
        instSort = instSort === null ? "desc" : instSort === "desc" ? "asc" : null;
        netBuySort = null;   // 两个排序互斥
        updateSortHeader();
        updateNetBuySortHeader();
        applyFilter();
    });

    thNetBuy.addEventListener("click", () => {
        netBuySort = netBuySort === null ? "desc" : netBuySort === "desc" ? "asc" : null;
        instSort = null;   // 两个排序互斥
        updateSortHeader();
        updateNetBuySortHeader();
        applyFilter();
    });

    // 初始化
    loadDates();
})();
