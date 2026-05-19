"""
A股估值数据拉取模块 (cn_valuation_fetcher.py)

数据源 (直接调用 REST API，无分页，无阻塞):
  A. 季度利润率  — 东方财富 RPT_DMSK_FN_INCOME                          (~2s)
  B. ROIC 历史   — 东方财富 RPT_F10_FINANCE_MAINFINADATA               (~2s)
                   同时获取 FCFF_BACK(TTM自由现金流) 和 INTEREST_DEBT_RATIO
  C. PE TTM      — 新浪财经 hq.sinajs.cn (实时股价) + 季报TTM净利润 + 年报EPS推算股本  (~0.1s)
                   TTM EPS = TTM净利润 ÷ 加权股本；PE TTM = 当前股价 ÷ TTM EPS
                   失败时降级为东方财富PageAjax年报PE
  D. Fwd PE/PS   — 东方财富 F10盈利预测 ProfitForecast/PageAjax             (~1s)
                   C/D 同一次请求，三路并发C/D/E
  E. 资产负债表  — 东方财富 RPT_DMSK_FN_BALANCE                              (~1-2s)
                   获取货币资金(MONETARYFUNDS) 和 总资产(TOTAL_ASSETS)
  F. PS TTM      — 由 PE × (年度净利润/年度营收) 推算
  G. EV/FCF      — EV = PE×净利润(市值) + 有息负债比×总资产 - 货币资金
                   FCF = FCFF_BACK (东方财富年报自由现金流)
                   C/D/E 三路并发执行，总耗时约 ~5s

支持代码格式: 600519 / 600519.SH / 000001.SZ / SH:600519 / SH600519

与 valuation_fetcher.py 返回完全相同的字段结构，兼容前端展示。

切换数据源: 修改 CN_DATA_SOURCE 常量，并实现同名 _*_<source> 系列函数。
"""

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
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
_EM_V1   = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
_EM_GET  = "https://datacenter.eastmoney.com/securities/api/data/get"
_EM_F10  = "https://emweb.securities.eastmoney.com/PC_HSF10/ProfitForecast/PageAjax"


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
        "_ttm_net": None,
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

    # TTM 净利润 = 最近 4 个单季度之和
    nets = [sq.get("PARENT_NETPROFIT") for sq in sq_oldest if sq.get("PARENT_NETPROFIT") is not None]
    if len(nets) == 4:
        out["_ttm_net"] = sum(nets)

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
        "_epsjb": None,
        "_fcff": None,
        "_fcff_fwd": None,
        "_int_debt_ratio": None,
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
    out["_rev"]  = _f(annual[0].get("TOTALOPERATEREVE"))
    out["_net"]  = _f(annual[0].get("PARENTNETPROFIT"))
    out["_epsjb"] = _f(annual[0].get("EPSJB"))
    out["_fcff"]          = _f(annual[0].get("FCFF_BACK"))
    out["_fcff_fwd"]      = _f(annual[0].get("FCFF_FORWARD"))
    out["_int_debt_ratio"] = _f(annual[0].get("INTEREST_DEBT_RATIO"))

    oldest_first = list(reversed(annual))
    out["roicLabels"] = [str(r.get("REPORT_DATE", ""))[:4] for r in oldest_first]
    for i, row in enumerate(oldest_first):
        v = _f(row.get("ROIC"))
        out[f"ttmRoicY{i + 1}"] = v / 100.0 if v is not None else None

    return out


# ── eastmoney: 盈利预测 (PE TTM / Fwd PE / Fwd PS) ──────────────────────────
#
# 接口: emweb.securities.eastmoney.com/PC_HSF10/ProfitForecast/PageAjax
# 响应中 yctj_chart[] 含: YEAR / YEAR_MARK(A|E) / PE / PARENT_NETPROFIT / TOTAL_OPERATE_INCOME
#
# YEAR_MARK="A" (实际年报): PE = 当前股价 ÷ 该年度实际EPS → 等价于 PE TTM（当年全年为最新年报时）
# YEAR_MARK="E" (分析师预测): 按当前财季动态混合:
#   Q1       → 100% 当年预测 E_Y0
#   Q2 / Q3  → 50% 当年 E_Y0 + 50% 次年 E_Y1
#   Q4       → 100% 次年预测 E_Y1

def _fetch_fwd_estimates_em(code6, exch):
    """
    数据源: 东方财富 F10 盈利预测 PageAjax (~1s)
    返回 (pe_ttm, fwd_pe, fwd_ps)，失败时均为 None
    pe_ttm 取最新实际年度(A)的 PE（基于当前股价），相当于 PE TTM 近似值
    """
    try:
        code_param = f"{exch}{code6}"          # e.g. "SH600519" / "SZ000001"
        r = requests.get(
            _EM_F10,
            params={"code": code_param},
            headers={**_HEADERS, "Referer": "https://emweb.securities.eastmoney.com/"},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        chart = r.json().get("yctj_chart") or []

        # PE TTM: 最新实际年度 (YEAR_MARK="A") 的 PE
        actuals = [c for c in chart if c.get("YEAR_MARK") == "A"]
        pe_ttm = _f(actuals[0].get("PE")) if actuals else None
        cur_net = _f(actuals[0].get("PARENT_NETPROFIT")) if actuals else None

        # Fwd PE / PS: 预测年度 (YEAR_MARK="E")
        estimates = [c for c in chart if c.get("YEAR_MARK") == "E"]
        if not estimates:
            return pe_ttm, None, None, None

        quarter = (date.today().month - 1) // 3 + 1

        def _pe_ps(est):
            pe  = _f(est.get("PE"))
            net = _f(est.get("PARENT_NETPROFIT"))
            rev = _f(est.get("TOTAL_OPERATE_INCOME"))
            nm  = _ratio(net, rev)
            ps  = round(pe * nm, 2) if pe is not None and nm is not None else None
            return pe, ps

        fwd_net_y0 = _f(estimates[0].get("PARENT_NETPROFIT"))

        if len(estimates) == 1 or quarter == 1:
            fwd_pe, fwd_ps = _pe_ps(estimates[0])
        elif quarter == 4:
            fwd_pe, fwd_ps = _pe_ps(estimates[1])
        else:  # Q2 / Q3
            pe0, ps0 = _pe_ps(estimates[0])
            pe1, ps1 = _pe_ps(estimates[1])
            fwd_pe = round((pe0 + pe1) / 2, 2) if pe0 is not None and pe1 is not None else (pe0 or pe1)
            fwd_ps = round((ps0 + ps1) / 2, 2) if ps0 is not None and ps1 is not None else (ps0 or ps1)

        return pe_ttm, fwd_pe, fwd_ps, fwd_net_y0
    except Exception:
        return None, None, None, None


# ── eastmoney: 资产负债表 (现金 / 总资产) ─────────────────────────────────────
#
# RPT_DMSK_FN_BALANCE 提供简化资产负债表
# 用于计算 EV = 总市值 + 有息负债 - 货币资金
#   MONETARYFUNDS  — 货币资金 (现金及现金等价物)
#   TOTAL_ASSETS   — 资产总计
#   SHORT_LOAN     — 短期借款 (部分公司有，贡献于有息负债)

def _fetch_balance_em(secucode):
    """
    数据源: 东方财富 RPT_DMSK_FN_BALANCE (~1-2s)
    返回最新期末货币资金和总资产，用于 EV 计算
    """
    out = {"monetaryfunds": None, "total_assets": None}
    try:
        rows = _em_v1(
            "RPT_DMSK_FN_BALANCE",
            "SECUCODE,REPORT_DATE,MONETARYFUNDS,TOTAL_ASSETS,SHORT_LOAN",
            secucode,
            page_size=1,
        )
        if rows:
            out["monetaryfunds"] = _f(rows[0].get("MONETARYFUNDS"))
            out["total_assets"]  = _f(rows[0].get("TOTAL_ASSETS"))
    except Exception:
        pass
    return out


# ── Sina Finance: 实时股价 ────────────────────────────────────────────────────
#
# 接口: hq.sinajs.cn/list=sh600519
# 响应: var hq_str_sh600519="贵州茅台,open,prev_close,current,high,low,...";
# fields[3] = 当前价格

def _fetch_price_sina(code6, exch):
    """
    数据源: 新浪财经实时行情 (~0.1s)
    返回当前股价，失败则返回 None
    """
    try:
        prefix = "sh" if exch == "SH" else ("sz" if exch == "SZ" else "bj")
        r = requests.get(
            f"https://hq.sinajs.cn/list={prefix}{code6}",
            headers={**_HEADERS, "Referer": "https://finance.sina.com.cn/"},
            timeout=_TIMEOUT,
        )
        data_str = r.text.split('"')[1]
        fields = data_str.split(",")
        return _f(fields[3]) if len(fields) > 3 else None
    except Exception:
        return None


# ── 主接口 ────────────────────────────────────────────────────────────────────

def build_valuation_cn(ticker: str) -> dict:
    """
    获取单只A股的完整估值数据。
    返回字段与 build_valuation() 完全一致，兼容前端与缓存格式。

    耗时参考 (每只股票约 5-6s):
      季度利润率  RPT_DMSK_FN_INCOME          ~2s  (含TTM净利润)
      ROIC历史    RPT_F10_FINANCE_MAINFINADATA ~2s  (含EPSJB/FCFF_BACK)
      ── 以下三路并发 ──
      PE TTM + Fwd PE/PS  EM ProfitForecast PageAjax  ~1s
      资产负债表          RPT_DMSK_FN_BALANCE           ~1-2s
      实时股价            新浪财经 hq.sinajs.cn          ~0.1s
    PE TTM = 当前股价 ÷ TTM EPS; 若新浪失败则降级为年报PE
    """
    if CN_DATA_SOURCE != "eastmoney":
        raise NotImplementedError(f"数据源 '{CN_DATA_SOURCE}' 尚未实现")

    code, secucode = _normalize(ticker)
    exch = secucode.split(".")[1]          # "SH" / "SZ" / "BJ"
    display_ticker = ticker.strip().upper()

    margins = _fetch_quarterly_margins_em(secucode)
    roic_data = _fetch_roic_em(secucode)

    # PageAjax (~1s), 资产负债表 (~1-2s), 新浪实时股价 (~0.1s) 并发执行
    with ThreadPoolExecutor(max_workers=3) as pool:
        f_fwd     = pool.submit(_fetch_fwd_estimates_em, code, exch)
        f_balance = pool.submit(_fetch_balance_em, secucode)
        f_price   = pool.submit(_fetch_price_sina, code, exch)
        pe_lfy, fwd_pe, fwd_ps, fwd_net_y0 = f_fwd.result()   # LFY PE (fallback)
        balance                 = f_balance.result()
        price                   = f_price.result()

    # PS = PE × (annual net profit / annual revenue)
    ann_rev = roic_data.pop("_rev", None)
    ann_net = roic_data.pop("_net", None)
    ann_eps = roic_data.pop("_epsjb", None)
    ttm_net = margins.pop("_ttm_net", None)

    # TTM PE: 当前价格 ÷ TTM EPS
    # total_shares ≈ 年报归母净利润 ÷ 年报每股收益 (加权平均股数)
    pe = pe_lfy  # default: last-fiscal-year PE from PageAjax
    if price and ann_net and ann_eps and ann_eps != 0 and ttm_net:
        total_shares = ann_net / ann_eps
        if total_shares > 0:
            ttm_eps = ttm_net / total_shares
            if ttm_eps > 0:
                pe = round(price / ttm_eps, 2)

    ps = None
    if pe is not None and ann_rev and ann_net:
        nm = _ratio(ann_net, ann_rev)
        if nm is not None:
            ps = round(pe * nm, 2)

    # PEG = Fwd PE ÷ 预期 EPS 增长率(%)
    # EPS 增长率 ≈ (预测年净利润 - 年报实际年净利润) / |年报实际年净利润| × 100
    peg = None
    if fwd_pe is not None and fwd_net_y0 is not None and ann_net and ann_net != 0:
        eps_growth = (fwd_net_y0 - ann_net) / abs(ann_net) * 100
        if eps_growth > 0:
            peg = round(fwd_pe / eps_growth, 2)

    # EV/FCF 和 Fwd EV/FCF 计算
    # EV = 总市值 + 有息负债 - 货币资金
    # 总市值 ≈ PE(TTM) × 归母净利润(最新年报)
    # 有息负债 ≈ INTEREST_DEBT_RATIO% × 总资产
    fcff          = roic_data.pop("_fcff", None)
    fcff_fwd      = roic_data.pop("_fcff_fwd", None)
    int_debt_ratio = roic_data.pop("_int_debt_ratio", None)
    ev_fcf = None
    fwd_ev_fcf = None
    if pe is not None and ann_net:
        # 总市值: 优先用实时股价×股本，其次用 PE×净利润
        if price and ann_net and ann_eps and ann_eps != 0:
            total_shares = ann_net / ann_eps
            market_cap = price * total_shares
        else:
            market_cap = pe * ann_net
        total_assets = balance.get("total_assets")
        cash         = balance.get("monetaryfunds") or 0
        if int_debt_ratio is not None and total_assets:
            interest_debt = int_debt_ratio / 100.0 * total_assets
            net_debt  = interest_debt - cash
            ev = market_cap + net_debt
        else:
            ev = market_cap  # fallback: P/FCF approximation
        if fcff and fcff != 0:
            ev_fcf = round(ev / fcff, 2)
        if fcff_fwd and fcff_fwd != 0:
            fwd_ev_fcf = round(ev / fcff_fwd, 2)

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
        "fcfMultiple":    ev_fcf,     # EV/FCF (有息负债法) 或 P/FCF 近似
        "fwdFcfMultiple": fwd_ev_fcf, # Fwd EV/FCF (基于 FCFF_FORWARD 分析师预测)
        "peRatio":        pe,
        "pegRatio":       peg,
        "fwdPe":         round(fwd_pe, 2) if fwd_pe is not None else None,
        "psRatio":       ps,
        "fwdPs":         fwd_ps,
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
