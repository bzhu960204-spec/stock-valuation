"""
A股估值数据拉取模块 (cn_valuation_fetcher.py)

数据源 (直接调用 REST API，无分页，无阻塞):
  A. 季度利润率  — 东方财富 RPT_DMSK_FN_INCOME          (~2s)
  B. ROIC 历史   — 东方财富 RPT_F10_FINANCE_MAINFINADATA (~2s)
  C. PE TTM      — 百度股市通 gushitong.baidu.com        (~7s)
  D. PS TTM      — 由 PE × (年度净利润/年度营收) 推算
  E. EV/FCF, Fwd PE, Fwd PS — 暂无数据，可手动录入

支持代码格式: 600519 / 600519.SH / 000001.SZ / SH:600519 / SH600519

与 valuation_fetcher.py 返回完全相同的字段结构，兼容前端展示。

切换数据源: 修改 CN_DATA_SOURCE 常量，并实现同名 _*_<source> 系列函数。
"""

import re
import time
from datetime import date

import requests

# ── 数据源选择器 ──────────────────────────────────────────────────────────────
# 切换此值可切换数据源；当前仅实现 "eastmoney"
CN_DATA_SOURCE = "eastmoney"

# ── 网络常量 ──────────────────────────────────────────────────────────────────
_TIMEOUT = 12
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.eastmoney.com/",
}
_EM_V1  = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
_EM_GET = "https://datacenter.eastmoney.com/securities/api/data/get"
_BAIDU  = "https://gushitong.baidu.com/opendata"


# ── Ticker 格式识别与规范化 ───────────────────────────────────────────────────

_CN_RE = re.compile(
    r"^(?:(?:SH|SZ|BJ|CN):?)?(\d{6})(?:\.(?:SH|SZ|BJ))?$",
    re.IGNORECASE,
)


def is_cn_ticker(ticker: str) -> bool:
    """判断是否为A股代码（6位数字，允许交易所前/后缀）"""
    return bool(_CN_RE.match(ticker.strip()))


def _normalize(ticker: str) -> tuple:
    """
    返回 (6位纯数字代码, SECUCODE格式)
    e.g. "600519"      -> ("600519", "600519.SH")
         "000001.SZ"   -> ("000001", "000001.SZ")
         "SH:601318"   -> ("601318", "601318.SH")
    """
    m = _CN_RE.match(ticker.strip().upper())
    if not m:
        raise ValueError(f"无法识别的A股代码格式: {ticker}")
    code = m.group(1)
    first = code[0]
    if first in ("6", "9"):
        exch = "SH"
    elif first in ("0", "2", "3"):
        exch = "SZ"
    elif first in ("4", "8"):
        exch = "BJ"
    else:
        exch = "SH"
    return code, f"{code}.{exch}"


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _f(v):
    """安全转 float；None / NaN / 异常 均返回 None"""
    if v is None:
        return None
    try:
        f = float(v)
        return None if f != f else f  # NaN guard
    except (TypeError, ValueError):
        return None


def _ratio(num, denom):
    """安全除法"""
    n, d = _f(num), _f(denom)
    if n is None or d is None or d == 0:
        return None
    return n / d


# ── REST API 辅助 ─────────────────────────────────────────────────────────────

def _em_v1(report, cols, secucode, page_size=8):
    """
    东方财富 /v1/get 接口 (无分页，单次请求)
    用于: RPT_DMSK_FN_INCOME 等新版接口
    """
    params = {
        "reportName": report,
        "columns": cols,
        "filter": f'(SECUCODE="{secucode}")',
        "pageNumber": "1",
        "pageSize": str(page_size),
        "sortTypes": "-1",
        "sortColumns": "REPORT_DATE",
        "source": "HSF10",
        "client": "PC",
    }
    r = requests.get(_EM_V1, params=params, headers=_HEADERS, timeout=_TIMEOUT)
    r.raise_for_status()
    result = r.json().get("result") or {}
    return result.get("data") or []


def _em_get(type_, sty, secucode, page_size=20):
    """
    东方财富 /get 接口 (无分页，单次请求)
    用于: RPT_F10_FINANCE_MAINFINADATA 等旧版接口
    """
    params = {
        "type": type_,
        "sty": sty,
        "filter": f'(SECUCODE="{secucode}")',
        "p": "1",
        "ps": str(page_size),
        "sr": "-1",
        "st": "REPORT_DATE",
        "source": "HSF10",
        "client": "PC",
    }
    r = requests.get(_EM_GET, params=params, headers=_HEADERS, timeout=_TIMEOUT)
    r.raise_for_status()
    result = r.json().get("result") or {}
    return result.get("data") or []


# ── eastmoney: 季度利润率 ─────────────────────────────────────────────────────
#
# RPT_DMSK_FN_INCOME 返回累计YTD数据，需还原为单季度:
#   Q1 (3月): 等于本身
#   Q2 (6月): H1_累计 - Q1_累计
#   Q3 (9月): 9M_累计 - H1_累计
#   Q4 (12月): 全年_累计 - 9M_累计

def _to_single_quarters(rows):
    """将累计利润表还原为单季度，返回最新在前的列表"""
    idx = {}
    for row in rows:
        key = str(row.get("REPORT_DATE", ""))[:7]  # "2026-03"
        idx[key] = row

    COLS = ("TOTAL_OPERATE_INCOME", "OPERATE_COST", "OPERATE_PROFIT", "PARENT_NETPROFIT")
    PREV_MONTH = {"03": None, "06": "03", "09": "06", "12": "09"}

    result = []
    for row in rows:
        rd = str(row.get("REPORT_DATE", ""))[:10]
        year, mm = rd[:4], rd[5:7]
        if mm not in PREV_MONTH:
            continue
        prev_mm = PREV_MONTH[mm]
        if prev_mm is None:
            sq = {c: _f(row.get(c)) for c in COLS}
        else:
            prev = idx.get(f"{year}-{prev_mm}")
            if not prev:
                continue
            sq = {}
            for c in COLS:
                cur = _f(row.get(c))
                prv = _f(prev.get(c))
                sq[c] = (cur - prv) if cur is not None and prv is not None else None
        sq["REPORT_DATE"] = row["REPORT_DATE"]
        result.append(sq)
    return result  # newest-first


def _fetch_quarterly_margins_em(secucode):
    """
    数据源: 东方财富 RPT_DMSK_FN_INCOME (~2s)
    返回最近4个单季度的毛利率、营业利润率、净利率 (小数形式，如 0.89 = 89%)
    """
    out = {
        "grossMarginQ1": None, "grossMarginQ2": None,
        "grossMarginQ3": None, "grossMarginQ4": None,
        "opMarginQ1":    None, "opMarginQ2":    None,
        "opMarginQ3":    None, "opMarginQ4":    None,
        "netMarginQ1":   None, "netMarginQ2":   None,
        "netMarginQ3":   None, "netMarginQ4":   None,
        "quarterLabels": [],
    }
    try:
        rows = _em_v1(
            "RPT_DMSK_FN_INCOME",
            "SECUCODE,REPORT_DATE,TOTAL_OPERATE_INCOME,OPERATE_COST,OPERATE_PROFIT,PARENT_NETPROFIT",
            secucode,
            page_size=8,
        )
    except Exception:
        return out

    sq_rows = _to_single_quarters(rows)[:4]            # newest-first
    sq_oldest = list(reversed(sq_rows))                 # oldest-first → Q1..Q4

    out["quarterLabels"] = [str(r.get("REPORT_DATE", ""))[:10] for r in sq_oldest]

    for i, sq in enumerate(sq_oldest):
        q = i + 1
        rev  = sq.get("TOTAL_OPERATE_INCOME")
        cost = sq.get("OPERATE_COST")
        op   = sq.get("OPERATE_PROFIT")
        net  = sq.get("PARENT_NETPROFIT")
        gross = (rev - cost) if rev is not None and cost is not None else None
        out[f"grossMarginQ{q}"] = _ratio(gross, rev)
        out[f"opMarginQ{q}"]    = _ratio(op, rev)
        out[f"netMarginQ{q}"]   = _ratio(net, rev)

    return out


# ── eastmoney: ROIC 历史 ──────────────────────────────────────────────────────
#
# RPT_F10_FINANCE_MAINFINADATA 包含年报和季报数据
# 过滤条件: REPORT_DATE_NAME 以 "年报" 结尾 (如 "2025年报")
# 字段:
#   ROIC             — 投入资本回报率 (%) → /100 = 小数
#   TOTALOPERATEREVE — 营业总收入 (元)   用于推算 PS
#   PARENTNETPROFIT  — 归母净利润 (元)   用于推算 PS

def _fetch_roic_em(secucode):
    """
    数据源: 东方财富 RPT_F10_FINANCE_MAINFINADATA (~2s)
    返回最近4年年报的 ROIC 历史，以及最新年报的营收/净利润（用于 PS 推算）
    """
    out = {
        "roicCurrent": None,
        "ttmRoicY1": None, "ttmRoicY2": None,
        "ttmRoicY3": None, "ttmRoicY4": None,
        "roicLabels": [],
        "_rev": None,
        "_net": None,
    }
    try:
        rows = _em_get(
            "RPT_F10_FINANCE_MAINFINADATA",
            "APP_F10_MAINFINADATA",
            secucode,
            page_size=20,
        )
    except Exception:
        return out

    # Filter annual reports
    annual = [r for r in rows if str(r.get("REPORT_DATE_NAME", "")).endswith("年报")]
    if not annual:
        annual = [r for r in rows if str(r.get("REPORT_DATE", "")).endswith("12-31")]
    annual = annual[:4]  # newest-first, max 4
    if not annual:
        return out

    roic_v = _f(annual[0].get("ROIC"))
    out["roicCurrent"] = roic_v / 100.0 if roic_v is not None else None
    out["_rev"] = _f(annual[0].get("TOTALOPERATEREVE"))
    out["_net"] = _f(annual[0].get("PARENTNETPROFIT"))

    oldest_first = list(reversed(annual))
    out["roicLabels"] = [str(r.get("REPORT_DATE", ""))[:4] for r in oldest_first]
    for i, row in enumerate(oldest_first):
        v = _f(row.get("ROIC"))
        out[f"ttmRoicY{i + 1}"] = v / 100.0 if v is not None else None

    return out


# ── Baidu: PE TTM ─────────────────────────────────────────────────────────────
#
# 可用 indicator: "市盈率(TTM)", "市盈率(静)", "市净率", "总市值", "市现率"
# 返回时间序列中最新一个值

def _fetch_pe_baidu(code6):
    """
    数据源: 百度股市通 gushitong.baidu.com (~7s)
    返回最新 PE TTM，失败则返回 None（不影响其他字段）
    """
    try:
        params = {
            "openapi": "1", "dspName": "iphone", "tn": "tangram",
            "client": "app", "query": "市盈率(TTM)", "code": code6,
            "word": "", "resource_id": "51171", "market": "ab",
            "tag": "市盈率(TTM)", "chart_select": "近一年",
            "industry_select": "", "skip_industry": "1", "finClientType": "pc",
        }
        r = requests.get(_BAIDU, params=params, headers=_HEADERS, timeout=_TIMEOUT)
        body = (
            r.json()["Result"][0]["DisplayData"]["resultData"]
            ["tplData"]["result"]["chartInfo"][0]["body"]
        )
        return _f(body[-1][1]) if body else None
    except Exception:
        return None


# ── 主接口 ────────────────────────────────────────────────────────────────────

def build_valuation_cn(ticker: str) -> dict:
    """
    获取单只A股的完整估值数据。
    返回字段与 build_valuation() 完全一致，兼容前端与缓存格式。

    耗时参考 (每只股票约 11s):
      季度利润率  RPT_DMSK_FN_INCOME          ~2s
      ROIC历史    RPT_F10_FINANCE_MAINFINADATA ~2s
      PE TTM      Baidu gushitong              ~7s
    """
    if CN_DATA_SOURCE != "eastmoney":
        raise NotImplementedError(f"数据源 '{CN_DATA_SOURCE}' 尚未实现")

    code, secucode = _normalize(ticker)
    display_ticker = ticker.strip().upper()

    margins = _fetch_quarterly_margins_em(secucode)
    time.sleep(0.3)

    roic_data = _fetch_roic_em(secucode)
    time.sleep(0.3)

    pe = _fetch_pe_baidu(code)

    # PS = PE × (annual net profit / annual revenue)  [same fiscal year consistency]
    ann_rev = roic_data.pop("_rev", None)
    ann_net = roic_data.pop("_net", None)
    ps = None
    if pe is not None and ann_rev and ann_net:
        nm = _ratio(ann_net, ann_rev)
        if nm is not None:
            ps = round(pe * nm, 2)

    return {
        "ticker": display_ticker,
        # ── 季度利润率 ──
        "grossMargin":   None,
        "grossMarginQ1": margins["grossMarginQ1"],
        "grossMarginQ2": margins["grossMarginQ2"],
        "grossMarginQ3": margins["grossMarginQ3"],
        "grossMarginQ4": margins["grossMarginQ4"],
        "quarterLabels": margins["quarterLabels"],
        "opMargin":      None,
        "opMarginQ1":    margins["opMarginQ1"],
        "opMarginQ2":    margins["opMarginQ2"],
        "opMarginQ3":    margins["opMarginQ3"],
        "opMarginQ4":    margins["opMarginQ4"],
        "netMargin":     None,
        "netMarginQ1":   margins["netMarginQ1"],
        "netMarginQ2":   margins["netMarginQ2"],
        "netMarginQ3":   margins["netMarginQ3"],
        "netMarginQ4":   margins["netMarginQ4"],
        # ── 估值倍数 ──
        "fcfMultiple":   None,   # EV/FCF 暂无，可手动录入
        "peRatio":       pe,
        "fwdPe":         None,   # 前瞻数据暂无，可手动录入
        "psRatio":       ps,
        "fwdPs":         None,   # 前瞻数据暂无，可手动录入
        # ── ROIC ──
        "roicCurrent":   roic_data["roicCurrent"],
        "ttmRoicY1":     roic_data["ttmRoicY1"],
        "ttmRoicY2":     roic_data["ttmRoicY2"],
        "ttmRoicY3":     roic_data["ttmRoicY3"],
        "ttmRoicY4":     roic_data["ttmRoicY4"],
        "roicLabels":    roic_data["roicLabels"],
        "fetchDate":     date.today().isoformat(),
    }


def fetch_multiple_cn(tickers: list) -> list:
    """批量获取A股估值数据"""
    results = []
    for ticker in tickers:
        try:
            data = build_valuation_cn(ticker)
            results.append(data)
        except Exception as e:
            results.append({"ticker": ticker.strip().upper(), "error": str(e)})
    return results
