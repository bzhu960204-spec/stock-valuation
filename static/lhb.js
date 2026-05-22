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
    const thExplain     = document.getElementById("th-explain");
    const sortIcon      = document.getElementById("sort-icon");

    let allItems   = [];
    let activeChip = "all";
    let instSort   = null;   // null | "desc" | "asc"

    // ── 分类判断 ──────────────────────────────────────────────────
    function classify(info) {
        if (!info) return "other";
        if (info.includes("普通席位")) return "normal";        if (info.includes("买一主买")) return "zhumai";        if (/\d+家机构买入/.test(info) || info.includes("机构买入")) return "inst";
        if (info.includes("买入")) return "fund";   // 游资/地区资金/其它买入
        return "other";
    }

    // ── 筛选 & 渲染 ────────────────────────────────────────────────
    function applyFilter() {
        const filtered = activeChip === "all"
            ? allItems
            : activeChip === "buy-all"
                ? allItems.filter(x => ["normal", "zhumai", "fund", "inst"].includes(classify(x.explain_info)))
                : allItems.filter(x => classify(x.explain_info) === activeChip);

        // 按机构数排序（仅 inst 分类下生效）
        if (activeChip === "inst" && instSort) {
            filtered.sort((a, b) => {
                const na = parseInt(a.explain_info) || 0;
                const nb = parseInt(b.explain_info) || 0;
                return instSort === "desc" ? nb - na : na - nb;
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
        const isInst = activeChip === "inst";
        thExplain.classList.toggle("sortable", isInst);
        sortIcon.style.display = isInst ? "inline" : "none";
        const icons = { null: "&#8693;", desc: "&#8595;", asc: "&#8593;" };
        sortIcon.innerHTML = icons[instSort] ?? "&#8693;";
    }

    function renderTable(items) {
        if (!items || items.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#71767b;padding:40px">暂无数据</td></tr>';
            return;
        }
        tbody.innerHTML = items.map((item, idx) => {
            const rate    = item.change_rate;
            const rateStr = rate != null ? rate.toFixed(2) + "%" : "-";
            const cls     = rate > 0 ? "change-pos" : rate < 0 ? "change-neg" : "";
            return `<tr>
                <td class="col-idx">${idx + 1}</td>
                <td class="col-code">${item.code}</td>
                <td>${item.name}</td>
                <td>${item.explanation || ""}</td>
                <td>${item.explain_info || ""}</td>
                <td class="col-change ${cls}">${rateStr}</td>
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
            if (activeChip !== "inst") instSort = null;
            chips.forEach(c => c.className = "chip");
            chip.classList.add(`active-${activeChip}`);
            updateSortHeader();
            applyFilter();
        });
    });

    thExplain.addEventListener("click", () => {
        if (activeChip !== "inst") return;
        instSort = instSort === null ? "desc" : instSort === "desc" ? "asc" : null;
        updateSortHeader();
        applyFilter();
    });

    // 初始化
    loadDates();
})();
