#!/usr/bin/env python3
"""
估值数据拉取脚本 (Python版)

从 stockanalysis.com 爬取美股估值数据：
  - 季度毛利率/净利率 → /financials/?p=quarterly
  - 4年历史ROIC       → /financials/ratios/
  - EV/FCF TTM        → /statistics/

输出符合应用导入格式的 JSON 文件。

用法:
  python scripts/fetch_valuations.py AAPL MSFT GOOGL NVDA META AMZN NOW TSLA
  python scripts/fetch_valuations.py AAPL --output my-output.json

依赖:
  pip install -r scripts/requirements.txt

输出:
  ./valuation-import-YYYY-MM-DD.json
"""

import sys
import json
import time
import re
from datetime import date
from pathlib import Path

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


# ── HTTP 请求 ──────────────────────────────────────────────────────────────

def fetch_page(url: str, retries: int = 2) -> str:
    """Fetch a page with retries and rate limit handling."""
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            if resp.status_code == 200:
                return resp.text
            elif resp.status_code == 429:
                wait = 5 * (attempt + 1)
                print(f"    ⏸️  Rate limited, waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"    ❌ HTTP {resp.status_code}: {url}")
                return ""
        except requests.RequestException as e:
            if attempt < retries:
                time.sleep(3)
            else:
                print(f"    ❌ Request failed: {e}")
                return ""
    return ""


# ── stockanalysis: 季度毛利率 / 净利率 ────────────────────────────────────

def fetch_quarterly_margins(ticker: str) -> dict:
    """
    从 stockanalysis.com 季度利润表获取最近4个季度的毛利率、营业利润率和净利率。
    直接读取页面预计算的百分比行：Gross Margin / Operating Margin / Profit Margin。
    返回 Q1(最早) 到 Q4(最近)。
    """
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
        print(f"    ⚠️  {ticker}: 季度财务表格未找到")
        return result

    # Parse table into a dict of {row_label: [values]}
    rows = table.find_all("tr")
    data = {}
    for row in rows:
        cells = row.find_all(["td", "th"])
        if len(cells) >= 2:
            label = cells[0].get_text(strip=True)
            values = [c.get_text(strip=True) for c in cells[1:]]
            data[label] = values

    # Header row: quarter labels, newest-first → reverse to oldest-first
    header_row = table.find("tr")
    if header_row:
        all_labels = [c.get_text(strip=True) for c in header_row.find_all(["td", "th"])]
        result["quarterLabels"] = list(reversed(all_labels[1:5]))

    # Use pre-computed percentage rows from the page
    # Note: net margin is labelled "Profit Margin" on stockanalysis.com
    gm_row = data.get("Gross Margin", [])
    om_row = data.get("Operating Margin", [])
    nm_row = data.get("Profit Margin", [])

    if not gm_row and not om_row and not nm_row:
        print(f"    ⚠️  {ticker}: 利润率行未找到")
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


# ── stockanalysis: EV/FCF ──────────────────────────────────────────────────

def _fetch_fwd_revenue(ticker: str):
    """
    从 forecast 页面解析本财年收入预期。
    用于在 statistics 页没有 Forward PS 时作为 fallback 计算。
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
            parsed = []
            for c in cells[1:]:
                v = c.get_text(strip=True)
                if v.lower() in ("upgrade", "-", "n/a", ""):
                    break
                pv = _parse_large_number(v)
                if pv is not None:
                    parsed.append(pv)
            # Layout: [...historical..., this_FY, next_FY]
            if len(parsed) >= 2:
                return parsed[-2]
            elif parsed:
                return parsed[-1]
    return None


def fetch_ev_fcf(ticker: str) -> dict:
    """
    从 stockanalysis.com statistics 页面获取 EV、FCF 和 Forward PS。
    若 Forward PS 不可得，则从 forecast 页计算 Market Cap / Forward Revenue。
    """
    result = {"fcfMultiple": None, "fwdPs": None}

    url = f"{_build_base_url(ticker)}/statistics/"
    html = fetch_page(url)
    if not html:
        return result

    soup = BeautifulSoup(html, "html.parser")

    ev = None
    fcf = None
    market_cap = None

    # Search all tables for Enterprise Value, Free Cash Flow, Forward PS, Market Cap
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
    elif fcf is not None and fcf <= 0:
        print(f"    ⚠️  {ticker}: FCF为负 ({fcf:,.0f}), fcfMultiple设为null")

    # Fallback: 若 statistics 页没有 Forward PS，尝试从 forecast 页计算
    if result["fwdPs"] is None and market_cap and market_cap > 0:
        time.sleep(1)
        fwd_rev = _fetch_fwd_revenue(ticker)
        if fwd_rev and fwd_rev > 0:
            result["fwdPs"] = round(market_cap / fwd_rev, 2)
            print(f"    ℹ️  {ticker}: Forward PS 由 MarketCap/FwdRevenue 计算得出")

    return result


# ── stockanalysis: ratios 页 (PE / Fwd PE / PS / ROIC) ──────────────────────

def fetch_roic_history(ticker: str) -> dict:
    """
    从 stockanalysis.com ratios 页面获取：
      - PE Ratio、Forward PE、PS Ratio（当前列）
      - 4年 ROIC 历史 + 当前 ROIC
    """
    result = {
        "peRatio": None, "fwdPe": None, "psRatio": None,
        "roicCurrent": None,
        "ttmRoicY1": None, "ttmRoicY2": None, "ttmRoicY3": None, "ttmRoicY4": None,
    }

    url = f"{_build_base_url(ticker)}/financials/ratios/"
    html = fetch_page(url)
    if not html:
        return result

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        print(f"    ⚠️  {ticker}: ratios表格未找到")
        return result

    # Build data dict: {label: [Current_val, FY_newest, ...]}
    data = {}
    for row in table.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) >= 2:
            label = cells[0].get_text(strip=True)
            values = [c.get_text(strip=True) for c in cells[1:]]
            data[label] = values

    # Current column = index 0 in values
    def _cur(label):
        row_vals = data.get(label, [])
        return _parse_number(row_vals[0]) if row_vals else None

    result["peRatio"] = _cur("PE Ratio")
    result["fwdPe"]   = _cur("Forward PE")
    result["psRatio"] = _cur("PS Ratio")

    # ROIC: label contains "ROIC"; values[0]=Current, values[1:]=FY newest-first
    roic_row = next((v for k, v in data.items() if "ROIC" in k), [])
    if roic_row:
        result["roicCurrent"] = _parse_pct(roic_row[0])
        fy_values = []
        for v in roic_row[1:]:
            pct = _parse_pct(v)
            if pct is not None:
                fy_values.append(round(pct, 4))
            if len(fy_values) >= 4:
                break
        fy_values.reverse()  # oldest-first
        for i, val in enumerate(fy_values):
            result[f"ttmRoicY{i + 1}"] = val

    return result


# ── 数值解析工具函数 ─────────────────────────────────────────────────────────

def _parse_number(text: str):
    """解析财务数字 (e.g. '111,184' or '-5,234' or '94.03B')"""
    if not text or text == "-" or text == "n/a":
        return None
    text = text.strip().replace(",", "")
    try:
        return float(text)
    except ValueError:
        return _parse_large_number(text)


def _parse_large_number(text: str):
    """解析带单位的数字 (e.g. '4.35T', '129.17B', '523.4M')"""
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
    """解析百分比字符串, 返回小数 (e.g. '48.24%' → 0.4824)"""
    if not text or text == "-" or text == "n/a":
        return None
    text = text.strip().replace(",", "").replace("%", "")
    try:
        return float(text) / 100.0
    except ValueError:
        return None


# ── 组装单只股票数据 ────────────────────────────────────────────────────────

def build_valuation(ticker: str) -> dict:
    """获取单只股票的所有估值数据"""
    print(f"  ⏳ {ticker} — 拉取中...")

    # 1. 季度利润率
    margins = fetch_quarterly_margins(ticker)
    time.sleep(1.5)

    # 2. EV/FCF
    ev_fcf = fetch_ev_fcf(ticker)
    time.sleep(1.5)

    # 3. 历史 ROIC
    roic = fetch_roic_history(ticker)
    time.sleep(1.5)

    # 4. 公司名称 (从 statistics 页面的 title 标签获取)
    company_name = ticker  # fallback

    # 组装
    result = {
        "ticker": ticker,
        "companyName": company_name,
        "grossMargin": margins["grossMargin"],
        "grossMarginQ1": margins["grossMarginQ1"],
        "grossMarginQ2": margins["grossMarginQ2"],
        "grossMarginQ3": margins["grossMarginQ3"],
        "grossMarginQ4": margins["grossMarginQ4"],
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
        "peRatio": roic["peRatio"],
        "fwdPe": roic["fwdPe"],
        "psRatio": roic["psRatio"],
        "fwdPs": ev_fcf["fwdPs"],
        "roicCurrent": roic["roicCurrent"],
        "ttmRoicY1": roic["ttmRoicY1"],
        "ttmRoicY2": roic["ttmRoicY2"],
        "ttmRoicY3": roic["ttmRoicY3"],
        "ttmRoicY4": roic["ttmRoicY4"],
        "notes": f"自动拉取 @ {date.today().isoformat()} | stockanalysis.com",
    }

    # 打印摘要
    gm = margins["grossMarginQ4"]
    om = margins["opMarginQ4"]
    nm = margins["netMarginQ4"]
    fcf = ev_fcf["fcfMultiple"]
    pe = roic["peRatio"]
    fpe = roic["fwdPe"]
    ps = roic["psRatio"]
    r4 = roic["ttmRoicY4"]
    print(f"  ✅ {ticker}")
    print(f"     GM={_fmt_pct(gm)} OM={_fmt_pct(om)} NM={_fmt_pct(nm)}")
    print(f"     PE={_fmt_val(pe)} FwdPE={_fmt_val(fpe)} PS={_fmt_val(ps)} EV/FCF={_fmt_val(fcf)} ROIC(Y4)={_fmt_pct(r4)}")

    return result


# ── 格式化工具函数 ────────────────────────────────────────────────────────

def _fmt_pct(v):
    return f"{v*100:.1f}%" if v is not None else "N/A"

def _fmt_val(v):
    return f"{v:.1f}" if v is not None else "N/A"


# ── CLI 参数解析 ───────────────────────────────────────────────────────────

def parse_args():
    args = sys.argv[1:]
    tickers = []
    output = None

    i = 0
    while i < len(args):
        if args[i] == "--output" and i + 1 < len(args):
            output = args[i + 1]
            i += 2
        elif args[i] == "--tickers" and i + 1 < len(args):
            tickers.extend(t.strip().upper() for t in args[i + 1].split(","))
            i += 2
        elif not args[i].startswith("--"):
            tickers.append(args[i].upper())
            i += 1
        else:
            i += 1

    return tickers, output


# ── 主流程 ─────────────────────────────────────────────────────────────────

def main():
    tickers, output_path = parse_args()

    if not tickers:
        print("""
╔══════════════════════════════════════════════════════════════╗
║  估值数据拉取工具 (stockanalysis.com)                        ║
╚══════════════════════════════════════════════════════════════╝

用法:
  python scripts/fetch_valuations.py AAPL MSFT GOOGL NVDA
  python scripts/fetch_valuations.py --tickers AAPL,MSFT,GOOGL
  python scripts/fetch_valuations.py AAPL --output my-file.json

数据来源 (全部来自 stockanalysis.com):
  • 季度毛利率/净利率 → /financials/?p=quarterly
  • EV/FCF TTM        → /statistics/
  • 历史ROIC (4年)    → /financials/ratios/

安装依赖:
  pip install -r scripts/requirements.txt
""")
        sys.exit(0)

    print(f"\n📊 开始拉取 {len(tickers)} 只股票的估值数据...\n")

    results = []
    for ticker in tickers:
        try:
            data = build_valuation(ticker)
            results.append(data)
        except Exception as e:
            print(f"  ❌ {ticker} — 拉取失败: {e}")
        print()

    if not results:
        print("⚠️  没有成功拉取到任何数据")
        sys.exit(1)

    # 输出文件
    if not output_path:
        root = Path(__file__).resolve().parent.parent
        output_path = root / f"valuation-import-{date.today().isoformat()}.json"
    else:
        output_path = Path(output_path)

    output_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    # 打印摘要
    print("═" * 72)
    print(f"  ✅ 完成！成功拉取 {len(results)} / {len(tickers)} 只股票")
    print(f"  📁 输出文件: {output_path}")
    print("═" * 72)
    print()
    print(f"{'Ticker':<8}{'GM':>8}{'NM':>8}{'EV/FCF':>10}{'ROIC(Y4)':>10}")
    print("─" * 44)
    for r in results:
        print(
            f"{r['ticker']:<8}"
            f"{_fmt_pct(r['grossMarginQ4']):>8}"
            f"{_fmt_pct(r['netMarginQ4']):>8}"
            f"{_fmt_val(r['fcfMultiple']):>10}"
            f"{_fmt_pct(r['ttmRoicY4']):>10}"
        )
    print("─" * 44)


if __name__ == "__main__":
    main()
