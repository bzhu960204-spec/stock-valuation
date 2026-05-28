"""
Options Chain Fetcher — 使用 CBOE 延迟行情 API 获取美股期权链数据
数据源: https://cdn.cboe.com/api/global/delayed_quotes/options/{TICKER}.json
无需 API Key，15 分钟延迟，免费公开使用。
"""

import re
import requests
from datetime import datetime

_CBOE_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{ticker}.json"
_OPTION_RE = re.compile(r"^[A-Z]+(\d{6})([CP])(\d{8})$")
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://www.cboe.com/",
}


def _parse_expiration(yymmdd: str) -> str:
    """将 CBOE 期权符号中的日期部分 (YYMMDD) 转换为 YYYY-MM-DD 字符串。"""
    return datetime.strptime(yymmdd, "%y%m%d").strftime("%Y-%m-%d")


def _parse_option(opt: dict) -> tuple | None:
    """
    解析单条 CBOE 期权记录，返回 (expiration_str, option_type, record_dict) 或 None。
    """
    symbol = opt.get("option", "")
    m = _OPTION_RE.match(symbol)
    if not m:
        return None
    yymmdd, opt_type, strike_raw = m.group(1), m.group(2), m.group(3)
    expiration = _parse_expiration(yymmdd)
    strike = int(strike_raw) / 1000.0
    iv_raw = opt.get("iv", 0) or 0
    record = {
        "strike": strike,
        "volume": int(opt.get("volume") or 0),
        "openInterest": int(opt.get("open_interest") or 0),
        "lastPrice": float(opt.get("last_trade_price") or 0),
        "impliedVolatility": round(float(iv_raw) * 100, 2),
    }
    return expiration, opt_type, record


def _fetch_raw(ticker: str) -> tuple:
    """从 CBOE 拉取原始 JSON，返回 (grouped, snapshot_time) 元组。
    grouped 格式: {expiration: {"C": [...], "P": [...]}}。
    """
    url = _CBOE_URL.format(ticker=ticker.upper())
    resp = requests.get(url, headers=_HEADERS, timeout=15)
    if resp.status_code == 404:
        raise ValueError(f"未找到 {ticker} 的期权数据，请确认代码是否为美股")
    resp.raise_for_status()
    data = resp.json()
    snapshot_time = data.get("timestamp", "")
    options_list = data.get("data", {}).get("options", [])
    grouped: dict[str, dict[str, list]] = {}
    for opt in options_list:
        parsed = _parse_option(opt)
        if parsed is None:
            continue
        expiration, opt_type, record = parsed
        if expiration not in grouped:
            grouped[expiration] = {"C": [], "P": []}
        grouped[expiration][opt_type].append(record)
    return grouped, snapshot_time


def fetch_options_chain(ticker: str) -> dict:
    """
    获取指定美股最近行权日期的期权链数据。
    返回格式:
    {
        "ticker": "AAPL",
        "expiration": "2026-05-29",
        "expirations": ["2026-05-29", "2026-06-05", ...],
        "strikes": [150.0, 155.0, ...],
        "calls": [{"strike": 150.0, "volume": 1234, "openInterest": 5678, "lastPrice": 12.3, "impliedVolatility": 35.0}, ...],
        "puts":  [...]
    }
    """
    try:
        grouped, snapshot_time = _fetch_raw(ticker)
        if not grouped:
            return {"ticker": ticker.upper(), "error": "未找到期权数据"}

        expirations = sorted(grouped.keys())
        nearest_exp = expirations[0]

        calls = sorted(grouped[nearest_exp]["C"], key=lambda x: x["strike"])
        puts = sorted(grouped[nearest_exp]["P"], key=lambda x: x["strike"])
        all_strikes = sorted(set(c["strike"] for c in calls) | set(p["strike"] for p in puts))

        # 计算各到期日的 Call/Put OI 汇总
        expiration_summary = []
        for exp in expirations:
            call_oi = sum(c["openInterest"] for c in grouped[exp]["C"])
            put_oi = sum(p["openInterest"] for p in grouped[exp]["P"])
            cpr = round(call_oi / put_oi, 2) if put_oi > 0 else None
            expiration_summary.append({
                "expiration": exp,
                "callOI": call_oi,
                "putOI": put_oi,
                "cpr": cpr,
            })

        return {
            "ticker": ticker.upper(),
            "expiration": nearest_exp,
            "expirations": expirations,
            "strikes": all_strikes,
            "calls": calls,
            "puts": puts,
            "snapshotTime": snapshot_time,
            "expirationSummary": expiration_summary,
        }

    except Exception as e:
        return {"ticker": ticker.upper(), "error": str(e)}


def fetch_options_by_expiration(ticker: str, expiration: str) -> dict:
    """获取指定行权日期的期权链"""
    try:
        grouped, snapshot_time = _fetch_raw(ticker)
        if not grouped:
            return {"ticker": ticker.upper(), "error": "未找到期权数据"}

        if expiration not in grouped:
            available = sorted(grouped.keys())
            return {"ticker": ticker.upper(), "error": f"到期日 {expiration} 无数据，可用到期日: {available[:5]}"}

        calls = sorted(grouped[expiration]["C"], key=lambda x: x["strike"])
        puts = sorted(grouped[expiration]["P"], key=lambda x: x["strike"])
        all_strikes = sorted(set(c["strike"] for c in calls) | set(p["strike"] for p in puts))

        return {
            "ticker": ticker.upper(),
            "expiration": expiration,
            "strikes": all_strikes,
            "calls": calls,
            "puts": puts,
            "snapshotTime": snapshot_time,
        }

    except Exception as e:
        return {"ticker": ticker.upper(), "error": str(e)}
