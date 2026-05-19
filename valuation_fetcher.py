"""
估值数据拉取模块

从 stockanalysis.com 爬取股票估値数据：
  - 季度毛利率/净利率 → /financials/?p=quarterly
  - EV/FCF TTM        → /statistics/
  - 4年历史ROIC       → /financials/ratios/

支持美股（AAPL）和非美股（STO:SIVE）格式。
"""

import time
import re
from datetime import date

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
}


def _build_base_url(ticker: str) -> str:
    """
    根据 ticker 格式返回 stockanalysis.com 的基础 URL。
    - 美股:  AAPL         → .../stocks/aapl
    - 非美股: STO:SIVE     → .../quote/sto/sive
    """
    if ":" in ticker:
        exchange, symbol = ticker.split(":", 1)
        return f"https://stockanalysis.com/quote/{exchange.lower()}/{symbol.lower()}"
    return f"https://stockanalysis.com/stocks/{ticker.lower()}"


def fetch_page(url: str, retries: int = 2) -> str:
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            if resp.status_code == 200:
                return resp.text
            elif resp.status_code == 429:
                wait = 5 * (attempt + 1)
                time.sleep(wait)
            else:
                return ""
        except requests.RequestException:
            if attempt < retries:
                time.sleep(3)
            else:
                return ""
    return ""


def _parse_number(text: str):
    if not text or text == "-" or text == "n/a":
        return None
    text = text.strip().replace(",", "")
    try:
        return float(text)
    except ValueError:
        return _parse_large_number(text)


def _parse_large_number(text: str):
    if not text or text == "-" or text == "n/a":
        return None
    text = text.strip().replace(",", "").replace("$", "")
    multipliers = {"T": 1e12, "B": 1e9, "M": 1e6, "K": 1e3}
    for suffix, mult in multipliers.items():
        if text.endswith(suffix):
            try:
                return float(text[:-1]) * mult
            except ValueError:
                return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_pct(text: str):
    if not text or text == "-" or text == "n/a":
        return None
    text = text.strip().replace(",", "").replace("%", "")
    try:
        return float(text) / 100.0
    except ValueError:
        return None


def fetch_quarterly_margins(ticker: str) -> dict:
    """获取最近4个季度的毛利率、营业利润率和净利率"""
    result = {
        "grossMargin": None,
        "grossMarginQ1": None, "grossMarginQ2": None,
        "grossMarginQ3": None, "grossMarginQ4": None,
        "opMargin": None,
        "opMarginQ1": None, "opMarginQ2": None,
        "opMarginQ3": None, "opMarginQ4": None,
        "netMargin": None,
        "netMarginQ1": None, "netMarginQ2": None,
        "netMarginQ3": None, "netMarginQ4": None,
        "quarterLabels": [],
    }

    url = f"{_build_base_url(ticker)}/financials/?p=quarterly"
    html = fetch_page(url)
    if not html:
        return result

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        return result

    rows = table.find_all("tr")
    data = {}
    for row in rows:
        cells = row.find_all(["td", "th"])
        if len(cells) >= 2:
            label = cells[0].get_text(strip=True)
            values = [c.get_text(strip=True) for c in cells[1:]]
            data[label] = values

    # Header row: [table_name, Q1_2026_newest, Q4_2025, Q3_2025, Q2_2025_oldest, ...]
    # No TTM column on the quarterly financials page
    header_row = table.find("tr")
    if header_row:
        all_labels = [c.get_text(strip=True) for c in header_row.find_all(["td", "th"])]
        # indices [1..4] = 4 quarter labels newest-first → reverse to oldest-first
        result["quarterLabels"] = list(reversed(all_labels[1:5]))

    gm_row = data.get("Gross Margin", [])
    om_row = data.get("Operating Margin", [])
    nm_row = data.get("Profit Margin", [])  # page label is "Profit Margin", not "Net Margin"

    if not gm_row and not om_row and not nm_row:
        return result

    n = min(4, max(len(gm_row), len(om_row), len(nm_row), 0))

    gm_vals = [_parse_pct(gm_row[i]) if i < len(gm_row) else None for i in range(n)]
    om_vals = [_parse_pct(om_row[i]) if i < len(om_row) else None for i in range(n)]
    nm_vals = [_parse_pct(nm_row[i]) if i < len(nm_row) else None for i in range(n)]

    # Reverse: newest-first → oldest-first (Q1=oldest, Q4=newest)
    gm_vals.reverse()
    om_vals.reverse()
    nm_vals.reverse()

    for i in range(n):
        q_num = i + 1
        result[f"grossMarginQ{q_num}"] = gm_vals[i] if i < len(gm_vals) else None
        result[f"opMarginQ{q_num}"] = om_vals[i] if i < len(om_vals) else None
        result[f"netMarginQ{q_num}"] = nm_vals[i] if i < len(nm_vals) else None

    return result


def _fetch_fwd_revenue(ticker: str):
    """
    从 forecast 页面解析本财年收入预期。
    用于在 statistics 页没有 Forward PS 时作为 fallback 计算。
    返回绝对值数字（与 Market Cap 同单位），失败时返回 None。
    """
    url = f"{_build_base_url(ticker)}/forecast/"
    html = fetch_page(url)
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if not cells or cells[0].get_text(strip=True) != "Revenue":
                continue
            # Collect values until we hit "Upgrade" / "-" / empty
            parsed = []
            for c in cells[1:]:
                v = c.get_text(strip=True)
                if v.lower() in ("upgrade", "-", "n/a", ""):
                    break
                pv = _parse_large_number(v)
                if pv is not None:
                    parsed.append(pv)
            # Layout: [...historical..., this_FY, next_FY]
            # Use second-to-last = current fiscal year estimate
            if len(parsed) >= 2:
                return parsed[-2]
            elif parsed:
                return parsed[-1]
    return None


def fetch_ev_fcf(ticker: str) -> dict:
    """获取 EV/FCF 和 Forward PS（来自 statistics 页，必要时从 forecast 页计算）"""
    result = {"fcfMultiple": None, "fwdPs": None}

    url = f"{_build_base_url(ticker)}/statistics/"
    html = fetch_page(url)
    if not html:
        return result

    soup = BeautifulSoup(html, "html.parser")

    ev = None
    fcf = None
    market_cap = None

    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) >= 2:
                label = cells[0].get_text(strip=True)
                value = cells[1].get_text(strip=True)

                if "Enterprise Value" in label and "EV/" not in label:
                    ev = _parse_large_number(value)
                elif label == "Free Cash Flow":
                    fcf = _parse_large_number(value)
                elif label == "Forward PS":
                    result["fwdPs"] = _parse_number(value)
                elif label == "Market Cap":
                    market_cap = _parse_large_number(value)

    if ev and fcf and fcf > 0:
        result["fcfMultiple"] = round(ev / fcf, 2)

    # Fallback: 若 statistics 页没有 Forward PS，尝试从 forecast 页计算
    if result["fwdPs"] is None and market_cap and market_cap > 0:
        time.sleep(1)
        fwd_rev = _fetch_fwd_revenue(ticker)
        if fwd_rev and fwd_rev > 0:
            result["fwdPs"] = round(market_cap / fwd_rev, 2)

    return result


def fetch_roic_history(ticker: str) -> dict:
    """从 ratios 页面获取 PE/Fwd PE/PS 及 ROIC 历史"""
    result = {
        "peRatio": None,
        "pegRatio": None,
        "fwdPe": None,
        "psRatio": None,
        "roicCurrent": None,
        "ttmRoicY1": None, "ttmRoicY2": None, "ttmRoicY3": None, "ttmRoicY4": None,
        "roicLabels": [],
    }

    url = f"{_build_base_url(ticker)}/financials/ratios/"
    html = fetch_page(url)
    if not html:
        return result

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        return result

    # Build data dict: {label: [Current, FY_newest, FY_next, ...]}
    data = {}
    for row in table.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) >= 2:
            label = cells[0].get_text(strip=True)
            values = [c.get_text(strip=True) for c in cells[1:]]
            data[label] = values

    # Header row: ["", "Current", FY_newest, FY_next, ..., FY_oldest]
    header_row = table.find("tr")
    if header_row:
        all_labels = [c.get_text(strip=True) for c in header_row.find_all(["td", "th"])]
        result["roicLabels"] = list(reversed(all_labels[2:6]))

    # Valuation ratios — "Current" column is index 0
    def _cur(label):
        row = data.get(label, [])
        return _parse_number(row[0]) if row else None

    result["peRatio"]  = _cur("PE Ratio")
    result["pegRatio"] = _cur("PEG Ratio")
    result["fwdPe"]    = _cur("Forward PE")
    result["psRatio"]  = _cur("PS Ratio")

    # ROIC row (label contains "ROIC")
    roic_row = next((v for k, v in data.items() if "ROIC" in k), [])
    if roic_row:
        result["roicCurrent"] = _parse_pct(roic_row[0])
        fy_values = []
        for v in roic_row[1:]:
            pct = _parse_pct(v)
            if pct is not None:
                fy_values.append(pct)
            if len(fy_values) >= 4:
                break
        fy_values.reverse()  # oldest-first
        for i, val in enumerate(fy_values):
            result[f"ttmRoicY{i + 1}"] = val

    return result


def build_valuation(ticker: str) -> dict:
    """获取单只股票的所有估值数据"""
    margins = fetch_quarterly_margins(ticker)
    time.sleep(1.5)

    ev_fcf = fetch_ev_fcf(ticker)
    time.sleep(1.5)

    roic = fetch_roic_history(ticker)
    time.sleep(1.5)

    return {
        "ticker": ticker,
        "grossMargin": margins["grossMargin"],
        "grossMarginQ1": margins["grossMarginQ1"],
        "grossMarginQ2": margins["grossMarginQ2"],
        "grossMarginQ3": margins["grossMarginQ3"],
        "grossMarginQ4": margins["grossMarginQ4"],
        "quarterLabels": margins["quarterLabels"],
        "opMargin": margins["opMargin"],
        "opMarginQ1": margins["opMarginQ1"],
        "opMarginQ2": margins["opMarginQ2"],
        "opMarginQ3": margins["opMarginQ3"],
        "opMarginQ4": margins["opMarginQ4"],
        "netMargin": margins["netMargin"],
        "netMarginQ1": margins["netMarginQ1"],
        "netMarginQ2": margins["netMarginQ2"],
        "netMarginQ3": margins["netMarginQ3"],
        "netMarginQ4": margins["netMarginQ4"],
        "fcfMultiple": ev_fcf["fcfMultiple"],
        "fwdFcfMultiple": None,
        "peRatio": roic["peRatio"],
        "pegRatio": roic["pegRatio"],
        "fwdPe": roic["fwdPe"],
        "psRatio": roic["psRatio"],
        "fwdPs": ev_fcf["fwdPs"],
        "roicCurrent": roic["roicCurrent"],
        "ttmRoicY1": roic["ttmRoicY1"],
        "ttmRoicY2": roic["ttmRoicY2"],
        "ttmRoicY3": roic["ttmRoicY3"],
        "ttmRoicY4": roic["ttmRoicY4"],
        "roicLabels": roic["roicLabels"],
        "fetchDate": date.today().isoformat(),
    }


def fetch_multiple(tickers: list) -> list:
    """批量获取多只股票的估值数据"""
    results = []
    for ticker in tickers:
        try:
            data = build_valuation(ticker.upper())
            results.append(data)
        except Exception as e:
            results.append({"ticker": ticker.upper(), "error": str(e)})
    return results
