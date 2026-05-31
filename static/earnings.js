/**
 * 财报日历前端逻辑 — 日历视图
 */

let calendarData = {};      // { "2026-06-02": [...], ... }
let monthsFetched = {};     // { "2026-06": "2026-05-31T10:00:00", ... }
let currentYear = new Date().getFullYear();
let currentMonth = new Date().getMonth(); // 0-indexed
let selectedDate = null;

const WEEKDAYS_CN = ['日', '一', '二', '三', '四', '五', '六'];
const MONTHS_CN = ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月'];

function pad(n) { return n < 10 ? '0' + n : '' + n; }

function toDateStr(y, m, d) {
    return `${y}-${pad(m + 1)}-${pad(d)}`;
}

function formatDateCN(dateStr) {
    const d = new Date(dateStr + 'T00:00:00');
    return `${d.getMonth() + 1}月${d.getDate()}日 (周${WEEKDAYS_CN[d.getDay()]})`;
}

function timingBadge(time, confirmed) {
    let cls = 'badge-tbd';
    if (time === '盘前') cls = 'badge-pre';
    else if (time === '盘后') cls = 'badge-post';
    let html = `<span class="badge ${cls}">${time}</span>`;
    if (!confirmed) {
        html += `<span class="badge badge-est">Est.</span>`;
    }
    return html;
}

function sp500Badge(isSp500) {
    if (!isSp500) return '';
    return `<span class="badge badge-sp500">S&P 500</span>`;
}

// ── 月份状态提示 ─────────────────────────────────────────────────

function updateMonthStatus() {
    const key = `${currentYear}-${pad(currentMonth + 1)}`;
    const statusEl = document.getElementById('monthStatus');
    if (monthsFetched[key]) {
        const t = new Date(monthsFetched[key]);
        statusEl.innerHTML = `<span class="fetched">✓ 已拉取 · 更新于 ${t.toLocaleString('zh-CN')}</span>`;
    } else {
        statusEl.innerHTML = `<span class="not-fetched">⚠ 本月尚未拉取数据，点击「拉取本月数据」获取</span>`;
    }
}

// ── 日历渲染 ─────────────────────────────────────────────────────

function renderCalendarGrid() {
    const grid = document.getElementById('calendarGrid');
    const label = document.getElementById('monthLabel');
    label.textContent = `${currentYear}年 ${MONTHS_CN[currentMonth]}`;
    updateMonthStatus();

    const firstDay = new Date(currentYear, currentMonth, 1).getDay();
    const daysInMonth = new Date(currentYear, currentMonth + 1, 0).getDate();
    const today = new Date();
    const todayStr = toDateStr(today.getFullYear(), today.getMonth(), today.getDate());

    let html = '';
    // Weekday headers
    for (const w of WEEKDAYS_CN) {
        html += `<div class="weekday-header">${w}</div>`;
    }

    // Empty cells before first day
    for (let i = 0; i < firstDay; i++) {
        html += `<div class="calendar-cell empty"></div>`;
    }

    // Day cells
    for (let d = 1; d <= daysInMonth; d++) {
        const dateStr = toDateStr(currentYear, currentMonth, d);
        const dayOfWeek = new Date(currentYear, currentMonth, d).getDay();
        const isWeekend = dayOfWeek === 0 || dayOfWeek === 6;
        const isToday = dateStr === todayStr;
        const earnings = calendarData[dateStr] || [];
        const hasEarnings = earnings.length > 0;
        const isSelected = dateStr === selectedDate;

        let classes = 'calendar-cell';
        if (isWeekend && !hasEarnings) classes += ' weekend';
        if (hasEarnings) classes += ' has-earnings';
        if (isToday) classes += ' today';
        if (isSelected) classes += ' selected';

        const onclick = hasEarnings ? `onclick="selectDate('${dateStr}')"` : '';

        let cellContent = `<div class="day-num">${d}</div>`;
        if (hasEarnings) {
            cellContent += `<span class="cell-count">${earnings.length}</span>`;
            const show = earnings.slice(0, 3);
            cellContent += '<div class="cell-tickers">';
            for (const e of show) {
                cellContent += `<span class="cell-ticker">${e.ticker}</span>`;
            }
            cellContent += '</div>';
            if (earnings.length > 3) {
                cellContent += `<div class="cell-more">+${earnings.length - 3} 更多</div>`;
            }
        }

        html += `<div class="${classes}" ${onclick}>${cellContent}</div>`;
    }

    grid.innerHTML = html;
}

// ── 详情面板 ─────────────────────────────────────────────────────

function selectDate(dateStr) {
    selectedDate = dateStr;
    renderCalendarGrid();
    showDetail(dateStr);
}

function showDetail(dateStr) {
    const panel = document.getElementById('detailPanel');
    const title = document.getElementById('detailTitle');
    const list = document.getElementById('detailList');

    const earnings = calendarData[dateStr] || [];
    if (earnings.length === 0) {
        panel.classList.remove('active');
        return;
    }

    title.textContent = `📋 ${formatDateCN(dateStr)} — 共 ${earnings.length} 家公司`;
    list.innerHTML = earnings.map(item => `
        <div class="detail-item">
            <div class="ticker">${item.ticker}</div>
            <div class="info">
                <div class="name" title="${item.name}">${item.name}</div>
                <div class="meta">${item.sector && item.sector !== '—' ? item.sector + ' · ' : ''}市值 ${item.market_cap} · 分析师 ${item.num_estimates}人 · EPS预估 ${item.eps_forecast || '—'}</div>
            </div>
            <div class="badges">
                ${timingBadge(item.time, item.confirmed)}
                ${sp500Badge(item.sp500)}
            </div>
        </div>
    `).join('');

    panel.classList.add('active');
    panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function closeDetail() {
    selectedDate = null;
    document.getElementById('detailPanel').classList.remove('active');
    renderCalendarGrid();
}

// ── 月份导航 ─────────────────────────────────────────────────────

function prevMonth() {
    currentMonth--;
    if (currentMonth < 0) { currentMonth = 11; currentYear--; }
    selectedDate = null;
    document.getElementById('detailPanel').classList.remove('active');
    renderCalendarGrid();
}

function nextMonth() {
    currentMonth++;
    if (currentMonth > 11) { currentMonth = 0; currentYear++; }
    selectedDate = null;
    document.getElementById('detailPanel').classList.remove('active');
    renderCalendarGrid();
}

// ── 数据加载 ─────────────────────────────────────────────────────

async function loadCalendar() {
    const loading = document.getElementById('loading');
    const content = document.getElementById('content');
    const lastUpdated = document.getElementById('lastUpdated');

    loading.style.display = '';
    content.style.display = 'none';

    try {
        const resp = await fetch('/api/earnings/calendar');
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();

        calendarData = data.calendar || {};
        monthsFetched = data.months_fetched || {};

        const fetched = Object.values(monthsFetched);
        if (fetched.length > 0) {
            const latest = new Date(fetched.sort().at(-1));
            lastUpdated.textContent = `最后更新: ${latest.toLocaleString('zh-CN')}`;
        } else {
            lastUpdated.textContent = '尚未拉取任何数据';
        }

        renderCalendarGrid();

        loading.style.display = 'none';
        content.style.display = '';

        autoSelectNearest();
    } catch (e) {
        loading.innerHTML = `<div style="color: #f4212e;">加载失败: ${e.message}<br><br>
            <button class="refresh-btn" onclick="loadCalendar()">重试</button></div>`;
    }
}

function autoSelectNearest() {
    const today = new Date();
    const todayStr = toDateStr(today.getFullYear(), today.getMonth(), today.getDate());

    // 始终默认显示当月
    currentYear = today.getFullYear();
    currentMonth = today.getMonth();
    renderCalendarGrid();

    // 自动选中今天或之后最近有数据的日期
    const dates = Object.keys(calendarData).sort();
    const nearest = dates.find(d => d >= todayStr);
    if (nearest) {
        const d = new Date(nearest + 'T00:00:00');
        // 如果最近有数据的日期在当月，直接选中；否则只停在当月
        if (d.getFullYear() === today.getFullYear() && d.getMonth() === today.getMonth()) {
            selectDate(nearest);
        }
    }
}

async function fetchCurrentMonth() {
    const btn = document.getElementById('fetchMonthBtn');
    const progressBox = document.getElementById('progressBox');
    const progressFill = document.getElementById('progressFill');
    const progressText = document.getElementById('progressText');
    const progressPct = document.getElementById('progressPct');
    const progressSub = document.getElementById('progressSub');

    btn.disabled = true;
    btn.textContent = '拉取中...';
    progressBox.classList.add('active');
    progressFill.style.width = '0%';
    progressPct.textContent = '0%';
    progressText.textContent = '正在连接...';
    progressSub.textContent = '';

    const month = currentMonth + 1;
    const url = `/api/earnings/refresh-stream?year=${currentYear}&month=${month}`;

    return new Promise((resolve) => {
        const source = new EventSource(url);

        source.onmessage = (event) => {
            const data = JSON.parse(event.data);

            if (data.status === 'start') {
                progressText.textContent = `正在拉取 ${currentYear}年${month}月 财报数据...`;
                progressSub.textContent = `共 ${data.total} 个交易日`;

            } else if (data.status === 'progress') {
                const pct = Math.round((data.processed / data.total) * 100);
                progressFill.style.width = `${pct}%`;
                progressPct.textContent = `${pct}%`;
                progressText.textContent = `已处理 ${data.processed} / ${data.total} 个交易日`;
                const foundMsg = data.found > 0 ? `，找到 ${data.found} 家大盘股` : '';
                progressSub.textContent = `当前日期: ${data.date}${foundMsg}`;

            } else if (data.status === 'done') {
                source.close();
                progressFill.style.width = '100%';
                progressPct.textContent = '100%';
                progressText.textContent = `✓ 拉取完成，共 ${data.total_found} 家大盘股财报`;
                progressSub.textContent = '';

                calendarData = data.result.calendar || {};
                monthsFetched = data.result.months_fetched || {};

                const key = `${currentYear}-${pad(month)}`;
                if (monthsFetched[key]) {
                    const t = new Date(monthsFetched[key]);
                    document.getElementById('lastUpdated').textContent = `最后更新: ${t.toLocaleString('zh-CN')}`;
                }

                renderCalendarGrid();

                // 2秒后收起进度条
                setTimeout(() => {
                    progressBox.classList.remove('active');
                    btn.disabled = false;
                    btn.textContent = '⬇ 拉取本月数据';
                }, 2000);

                resolve();
            }
        };

        source.onerror = () => {
            source.close();
            progressBox.classList.remove('active');
            btn.disabled = false;
            btn.textContent = '⬇ 拉取本月数据';
            alert('拉取失败，请重试');
            resolve();
        };
    });
}

document.addEventListener('DOMContentLoaded', loadCalendar);
