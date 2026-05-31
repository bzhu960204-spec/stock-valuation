/**
 * 财报日历前端逻辑 — 日历视图
 */

let calendarData = {};      // { "2026-06-02": [...], ... }
let monthsFetched = {};     // { "2026-06": "2026-05-31T10:00:00", ... }
let currentYear = new Date().getFullYear();
let currentMonth = new Date().getMonth(); // 0-indexed
let selectedDate = null;
let activeSectors = new Set(); // empty = show all

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

function earningsResultBadge(item) {
    // 如果已经公布了实际EPS
    if (!item.reported) {
        // 如果日期已过但没有actual数据，标记为"已发布"
        const today = new Date();
        const earningsDate = new Date(item.date + 'T00:00:00');
        if (earningsDate < today) {
            return `<span class="badge badge-reported">已发布</span>`;
        }
        return '';
    }
    const forecast = parseFloat((item.eps_forecast || '').replace('$', ''));
    const actual = parseFloat((item.eps_actual || '').replace('$', ''));
    if (isNaN(actual)) return `<span class="badge badge-reported">已发布</span>`;
    if (isNaN(forecast)) {
        return `<span class="badge badge-reported">已公布 ${item.eps_actual}</span>`;
    }
    if (actual >= forecast) {
        return `<span class="badge badge-beat">EPS Beat</span>`;
    } else {
        return `<span class="badge badge-miss">EPS Miss</span>`;
    }
}

function sectorBadge(sector) {
    if (!sector || sector === '—') return '';
    return `<span class="badge badge-sector">${sector}</span>`;
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

// ── 板块过滤 ─────────────────────────────────────────────────────

function getMonthSectors() {
    const sectors = new Set();
    const daysInMonth = new Date(currentYear, currentMonth + 1, 0).getDate();
    for (let d = 1; d <= daysInMonth; d++) {
        const dateStr = toDateStr(currentYear, currentMonth, d);
        for (const e of (calendarData[dateStr] || [])) {
            if (e.sector && e.sector !== '—') sectors.add(e.sector);
        }
    }
    return [...sectors].sort();
}

function renderSectorFilter() {
    const container = document.getElementById('sectorFilter');
    const sectors = getMonthSectors();
    if (sectors.length === 0) {
        container.innerHTML = '';
        return;
    }
    const allActive = activeSectors.size === 0;
    let html = `<span class="sector-filter-label">板块:</span>`;
    html += `<span class="sector-pill all-pill ${allActive ? 'active' : ''}" onclick="toggleSectorAll()">全部</span>`;
    for (const s of sectors) {
        const active = activeSectors.has(s) ? 'active' : '';
        html += `<span class="sector-pill ${active}" onclick="toggleSector('${s}')">${s}</span>`;
    }
    container.innerHTML = html;
}

function toggleSector(sector) {
    if (activeSectors.has(sector)) {
        activeSectors.delete(sector);
    } else {
        activeSectors.add(sector);
    }
    renderSectorFilter();
    renderCalendarGrid();
    if (selectedDate) showDetail(selectedDate, false);
}

function toggleSectorAll() {
    activeSectors.clear();
    renderSectorFilter();
    renderCalendarGrid();
    if (selectedDate) showDetail(selectedDate, false);
}

function filterBySector(entries) {
    if (activeSectors.size === 0) return entries;
    return entries.filter(e => activeSectors.has(e.sector));
}

// ── 日历渲染 ─────────────────────────────────────────────────────

function renderCalendarGrid() {
    const grid = document.getElementById('calendarGrid');
    const label = document.getElementById('monthLabel');
    label.textContent = `${currentYear}年 ${MONTHS_CN[currentMonth]}`;
    updateMonthStatus();
    renderSectorFilter();

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
        const earnings = filterBySector(calendarData[dateStr] || []);
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

function showDetail(dateStr, scroll = true) {
    const panel = document.getElementById('detailPanel');
    const title = document.getElementById('detailTitle');
    const list = document.getElementById('detailList');

    const earnings = filterBySector(calendarData[dateStr] || []);
    if (earnings.length === 0) {
        panel.classList.remove('active');
        return;
    }

    title.textContent = `📋 ${formatDateCN(dateStr)} — 共 ${earnings.length} 家公司`;
    list.innerHTML = earnings.map(item => {
        const epsInfo = item.reported
            ? `EPS实际 ${item.eps_actual} (预估 ${item.eps_forecast || '—'})${item.surprise ? ' · Surprise ' + item.surprise : ''}`
            : `EPS预估 ${item.eps_forecast || '—'}`;
        const resultBadge = earningsResultBadge(item);
        // 对于已报告的财报（日期已过或有actual数据），不显示"未公布"的时间badge
        const isPast = new Date(item.date + 'T00:00:00') < new Date();
        const timeBadgeHtml = ((item.reported || isPast) && item.time === '未公布') ? '' : timingBadge(item.time, item.confirmed);
        return `
        <div class="detail-item" data-ticker="${item.ticker}" data-date="${item.date}">
            <div class="ticker">${item.ticker}</div>
            <div class="info">
                <div class="name" title="${item.name}">${item.name}</div>
                <div class="meta">市值 ${item.market_cap} · 分析师 ${item.num_estimates}人 · ${epsInfo}</div>
            </div>
            <div class="badges">
                ${resultBadge}
                ${sectorBadge(item.sector)}
                ${timeBadgeHtml}
                ${sp500Badge(item.sp500)}
            </div>
            <button class="note-btn" onclick="openNoteEditor('${item.ticker}', '${item.date}')" title="记录笔记">📝</button>
        </div>
    `}).join('');

    panel.classList.add('active');
    if (scroll) panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
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
    activeSectors.clear();
    document.getElementById('detailPanel').classList.remove('active');
    renderCalendarGrid();
}

function nextMonth() {
    currentMonth++;
    if (currentMonth > 11) { currentMonth = 0; currentYear++; }
    selectedDate = null;
    activeSectors.clear();
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

// ── Markdown 笔记功能 ────────────────────────────────────────────

let currentNoteTicker = null;
let currentNoteDate = null;

async function openNoteEditor(ticker, date) {
    currentNoteTicker = ticker;
    currentNoteDate = date;
    const modal = document.getElementById('noteModal');
    const titleEl = document.getElementById('noteModalTitle');
    const editor = document.getElementById('noteEditor');
    const preview = document.getElementById('notePreview');
    const toggleBtn = document.getElementById('noteToggleBtn');

    titleEl.textContent = `${ticker} - ${date} 财报笔记`;
    editor.value = '';
    preview.innerHTML = '';

    // 加载已有笔记
    try {
        const resp = await fetch(`/api/earnings/notes?ticker=${ticker}&date=${date}`);
        if (resp.ok) {
            const data = await resp.json();
            editor.value = data.content || '';
        }
    } catch (e) {
        console.error('加载笔记失败', e);
    }

    // 默认进入编辑模式
    editor.style.display = '';
    preview.style.display = 'none';
    toggleBtn.textContent = '预览';
    toggleBtn.setAttribute('data-mode', 'edit');

    modal.classList.add('active');
}

function closeNoteModal() {
    document.getElementById('noteModal').classList.remove('active');
}

function toggleNotePreview() {
    const editor = document.getElementById('noteEditor');
    const preview = document.getElementById('notePreview');
    const toggleBtn = document.getElementById('noteToggleBtn');
    const mode = toggleBtn.getAttribute('data-mode');

    if (mode === 'edit') {
        // 切换到预览
        preview.innerHTML = renderMarkdown(editor.value);
        editor.style.display = 'none';
        preview.style.display = '';
        toggleBtn.textContent = '编辑';
        toggleBtn.setAttribute('data-mode', 'preview');
    } else {
        // 切换到编辑
        editor.style.display = '';
        preview.style.display = 'none';
        toggleBtn.textContent = '预览';
        toggleBtn.setAttribute('data-mode', 'edit');
    }
}

async function saveNote() {
    const editor = document.getElementById('noteEditor');
    const content = editor.value;

    try {
        const resp = await fetch('/api/earnings/notes', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                ticker: currentNoteTicker,
                date: currentNoteDate,
                content: content
            })
        });
        if (resp.ok) {
            // 保存成功 → 切换到预览模式
            const preview = document.getElementById('notePreview');
            const toggleBtn = document.getElementById('noteToggleBtn');
            preview.innerHTML = renderMarkdown(content);
            document.getElementById('noteEditor').style.display = 'none';
            preview.style.display = '';
            toggleBtn.textContent = '编辑';
            toggleBtn.setAttribute('data-mode', 'preview');
            showToast('笔记已保存');
        } else {
            showToast('保存失败', true);
        }
    } catch (e) {
        showToast('保存失败: ' + e.message, true);
    }
}

function showToast(msg, isError = false) {
    let toast = document.getElementById('toast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'toast';
        document.body.appendChild(toast);
    }
    toast.textContent = msg;
    toast.className = 'toast active' + (isError ? ' error' : '');
    setTimeout(() => toast.classList.remove('active'), 2500);
}

// ── 简易 Markdown 渲染 ──────────────────────────────────────────

function renderMarkdown(text) {
    if (!text || !text.trim()) return '<p style="color:#71767b;">暂无笔记</p>';

    let html = text;

    // 代码块 (```...```)
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
        return `<pre><code class="lang-${lang}">${escapeHtml(code.trim())}</code></pre>`;
    });

    // 行内代码
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

    // 标题 (h1-h4)
    html = html.replace(/^#### (.+)$/gm, '<h4>$1</h4>');
    html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');

    // 粗体和斜体
    html = html.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');

    // 删除线
    html = html.replace(/~~(.+?)~~/g, '<del>$1</del>');

    // 无序列表
    html = html.replace(/^[-*] (.+)$/gm, '<li>$1</li>');
    html = html.replace(/(<li>.*<\/li>\n?)+/g, (match) => `<ul>${match}</ul>`);

    // 引用块
    html = html.replace(/^> (.+)$/gm, '<blockquote>$1</blockquote>');
    html = html.replace(/<\/blockquote>\n<blockquote>/g, '<br>');

    // 水平线
    html = html.replace(/^---$/gm, '<hr>');

    // 链接
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');

    // 段落（双换行）
    html = html.replace(/\n\n/g, '</p><p>');
    // 单换行转 <br>（排除已有HTML标签的行）
    html = html.replace(/\n/g, '<br>');

    // 包装
    if (!html.startsWith('<')) html = '<p>' + html + '</p>';

    return html;
}

function escapeHtml(str) {
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
