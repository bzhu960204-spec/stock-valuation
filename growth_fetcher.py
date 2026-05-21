"""
收入增速数据拉取模块

从 stockanalysis.com 爬取股票近五年年度收入数据：
  - 公司名称      → /stocks/<ticker>/
  - 年度收入      → /stocks/<ticker>/financials/

支持美股（AAPL）和非美股（STO:SIVE）格式。
"""

import time
import re

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
}


def _build_base_url(ticker: str) -> str:
    if ":" in ticker:
        exchange, symbol = ticker.split(":", 1)
        return f"https://stockanalysis.com/quote/{exchange.lower()}/{symbol.lower()}"
    return f"https://stockanalysis.com/stocks/{ticker.lower()}"


def _fetch_page(url: str, retries: int = 2) -> str:
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            if resp.status_code == 200:
                return resp.text
            elif resp.status_code == 429:
                time.sleep(5 * (attempt + 1))
            else:
                return ""
        except requests.RequestException:
            if attempt < retries:
                time.sleep(3)
            else:
                return ""
    return ""


def _parse_revenue(text: str):
    """
    解析收入数值。stockanalysis 财务表格中数值均为百万单位（无后缀），
    直接返回该数值（百万）；若有 B/T 后缀则换算回百万。
    """
    if not text or text.strip() in ("-", "n/a", ""):
        return None
    text = text.strip().replace(",", "").replace("$", "")
    multipliers = {"T": 1_000_000, "B": 1_000, "M": 1, "K": 0.001}
    for suffix, mult in multipliers.items():
        if text.upper().endswith(suffix):
            try:
                return float(text[:-1]) * mult
            except ValueError:
                return None
    try:
        return float(text)  # 已是百万单位
    except ValueError:
        return None


def _parse_pct(text: str):
    """解析百分比字符串，返回小数（如 12.5% → 0.125）"""
    if not text or text.strip() in ("-", "n/a", ""):
        return None
    text = text.strip().replace("%", "")
    try:
        return round(float(text) / 100.0, 4)
    except ValueError:
        return None


def fetch_growth(ticker: str) -> dict:
    """
    从 stockanalysis.com 拉取近五年年度收入及同比增长率。
    """
    base_url = _build_base_url(ticker)
    financials_url = f"{base_url}/financials/"

    # ── 获取公司名称（主页面 <h1> 或 <title>）──────────────────────────
    main_html = _fetch_page(base_url)
    name = ticker.upper()
    if main_html:
        soup_main = BeautifulSoup(main_html, "html.parser")
        h1 = soup_main.find("h1")
        if h1:
            raw = h1.get_text(strip=True)
            # 去掉末尾的 "(TICKER)" 部分
            name = re.sub(r"\s*\([^)]+\)\s*$", "", raw).strip() or name

    time.sleep(1)

    # ── 获取年度财务数据 ────────────────────────────────────────────────
    html = _fetch_page(financials_url)
    if not html:
        return {"ticker": ticker.upper(), "error": "无法获取财务数据"}

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        return {"ticker": ticker.upper(), "error": "未找到财务表格"}

    # 解析表头（财年标签）
    header_row = table.find("tr")
    if not header_row:
        return {"ticker": ticker.upper(), "error": "表格格式异常"}

    header_cells = [c.get_text(strip=True) for c in header_row.find_all(["td", "th"])]
    # header_cells[0] = 指标名，[1] = TTM 或最新年，[2..] = 历史年份
    # 跳过 TTM 列（如果有），只取年份列（支持 "2024" 和 "FY 2024" 两种格式）
    year_indices = []
    for i, label in enumerate(header_cells[1:], start=1):
        m = re.search(r"(\d{4})", label)
        if m and "TTM" not in label.upper():
            year_indices.append((i, m.group(1)))

    if not year_indices:
        return {"ticker": ticker.upper(), "error": "未找到年份列"}

    # 只取最近5年
    year_indices = year_indices[:5]

    # 找 Revenue 行和 Revenue Growth (YoY) 行
    revenue_values = []
    growth_row_data = {}
    for row in table.find_all("tr")[1:]:
        cells = row.find_all(["td", "th"])
        if not cells:
            continue
        row_label = cells[0].get_text(strip=True)
        if row_label in ("Revenue", "Total Revenue"):
            for idx, year in year_indices:
                val_text = cells[idx].get_text(strip=True) if idx < len(cells) else "-"
                val = _parse_revenue(val_text)
                if val is not None:
                    revenue_values.append({"year": year, "revenue": val})
        elif row_label == "Revenue Growth (YoY)":
            for idx, year in year_indices:
                val_text = cells[idx].get_text(strip=True) if idx < len(cells) else "-"
                growth_row_data[year] = _parse_pct(val_text)

    if not revenue_values:
        return {"ticker": ticker.upper(), "error": "未找到收入数据"}

    # 按年份升序排列（表格是降序）
    revenue_values.sort(key=lambda x: x["year"])

    # 优先使用页面已算好的 YoY 增长率，fallback 自行计算
    for i, item in enumerate(revenue_values):
        if item["year"] in growth_row_data and growth_row_data[item["year"]] is not None:
            item["growth"] = growth_row_data[item["year"]]
        elif i == 0:
            item["growth"] = None
        else:
            prev = revenue_values[i - 1]["revenue"]
            curr = item["revenue"]
            item["growth"] = round((curr - prev) / abs(prev), 4) if prev else None

    # 提取货币单位（如 "USD", "CNY")
    currency = "USD"
    page_text = soup.get_text(" ", strip=True)
    m = re.search(r"in millions\s+([A-Z]{3})", page_text, re.IGNORECASE)
    if m:
        currency = m.group(1).upper()

    return {
        "ticker": ticker.upper(),
        "name": name,
        "currency": currency,
        "revenue": revenue_values,
    }


def fetch_multiple_growth(tickers: list[str]) -> list[dict]:
    """批量拉取多只股票的收入增速数据"""
    results = []
    for t in tickers:
        results.append(fetch_growth(t.strip()))
    return results
