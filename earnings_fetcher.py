"""
财报日历数据拉取模块

从 Nasdaq 官方 API 获取未来 30 天的财报发布日期，
过滤出大盘股（市值 > 200 亿美元、分析师覆盖 > 3），
并标记 S&P 500 成分股。
"""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_FILE = CACHE_DIR / "earnings_calendar.json"
SP500_CACHE = CACHE_DIR / "sp500_list.json"
SECTOR_CACHE = CACHE_DIR / "sectors.json"

# 筛选阈值
MIN_MARKET_CAP = 20_000_000_000  # 200 亿美元
MIN_ESTIMATES = 3                 # 至少 3 个分析师覆盖


# ── 板块/行业缓存 ─────────────────────────────────────────────────────────────

# 静态底子：常见大盘股的板块映射，避免首次额外请求
_SECTOR_STATIC = {
    "AAPL": "Technology", "MSFT": "Technology", "GOOGL": "Technology",
    "GOOG": "Technology", "AMZN": "Consumer Discretionary", "META": "Technology",
    "NVDA": "Technology", "TSLA": "Consumer Discretionary", "AVGO": "Technology",
    "AMD": "Technology", "INTC": "Technology", "CRM": "Technology",
    "ADBE": "Technology", "ORCL": "Technology", "CSCO": "Technology",
    "QCOM": "Technology", "TXN": "Technology", "AMAT": "Technology",
    "LRCX": "Technology", "MU": "Technology", "INTU": "Technology",
    "NOW": "Technology", "SNPS": "Technology", "CDNS": "Technology",
    "KLAC": "Technology", "ADI": "Technology", "MCHP": "Technology",
    "FTNT": "Technology", "PANW": "Technology", "CRWD": "Technology",
    "NET": "Technology", "PLTR": "Technology", "WDAY": "Technology",
    "JPM": "Financial", "BAC": "Financial", "GS": "Financial",
    "MS": "Financial", "WFC": "Financial", "C": "Financial",
    "BLK": "Financial", "SCHW": "Financial", "AXP": "Financial",
    "V": "Financial", "MA": "Financial", "COF": "Financial",
    "JNJ": "Healthcare", "UNH": "Healthcare", "LLY": "Healthcare",
    "PFE": "Healthcare", "MRK": "Healthcare", "ABBV": "Healthcare",
    "TMO": "Healthcare", "ABT": "Healthcare", "DHR": "Healthcare",
    "AMGN": "Healthcare", "GILD": "Healthcare", "VRTX": "Healthcare",
    "ISRG": "Healthcare", "SYK": "Healthcare", "REGN": "Healthcare",
    "BMY": "Healthcare", "MDT": "Healthcare", "ELV": "Healthcare",
    "CI": "Healthcare", "HCA": "Healthcare", "DXCM": "Healthcare",
    "XOM": "Energy", "CVX": "Energy", "COP": "Energy",
    "SLB": "Energy", "EOG": "Energy", "OXY": "Energy",
    "PSX": "Energy", "VLO": "Energy", "DVN": "Energy",
    "BKR": "Energy", "HAL": "Energy", "FANG": "Energy",
    "PG": "Consumer Staples", "KO": "Consumer Staples", "PEP": "Consumer Staples",
    "COST": "Consumer Staples", "WMT": "Consumer Staples", "PM": "Consumer Staples",
    "MO": "Consumer Staples", "CL": "Consumer Staples", "MDLZ": "Consumer Staples",
    "KDP": "Consumer Staples", "STZ": "Consumer Staples", "KHC": "Consumer Staples",
    "HD": "Consumer Discretionary", "MCD": "Consumer Discretionary",
    "NKE": "Consumer Discretionary", "LOW": "Consumer Discretionary",
    "TJX": "Consumer Discretionary", "BKNG": "Consumer Discretionary",
    "SBUX": "Consumer Discretionary", "CMG": "Consumer Discretionary",
    "LULU": "Consumer Discretionary", "ROST": "Consumer Discretionary",
    "DG": "Consumer Discretionary", "DLTR": "Consumer Discretionary",
    "ULTA": "Consumer Discretionary", "YUM": "Consumer Discretionary",
    "BA": "Industrials", "CAT": "Industrials", "GE": "Industrials",
    "HON": "Industrials", "UPS": "Industrials", "RTX": "Industrials",
    "DE": "Industrials", "UNP": "Industrials", "FDX": "Industrials",
    "LIN": "Industrials", "EMR": "Industrials", "GD": "Industrials",
    "NOC": "Industrials", "ITW": "Industrials", "WM": "Industrials",
    "NEE": "Utilities", "DUK": "Utilities", "SO": "Utilities",
    "D": "Utilities", "AEP": "Utilities", "SRE": "Utilities",
    "EXC": "Utilities", "XEL": "Utilities", "PCG": "Utilities",
    "T": "Communication Services", "TMUS": "Communication Services",
    "VZ": "Communication Services", "CMCSA": "Communication Services",
    "DIS": "Communication Services", "NFLX": "Communication Services",
    "COIN": "Financial", "UBER": "Technology", "ABNB": "Consumer Discretionary",
    "SNOW": "Technology", "DDOG": "Technology", "ZS": "Technology",
    "DELL": "Technology", "HPE": "Technology", "HPQ": "Technology",
    "SMCI": "Technology", "ARM": "Technology", "MRVL": "Technology",
    "ON": "Technology", "MPWR": "Technology", "CRDO": "Technology",
}


def _load_sector_cache() -> dict:
    """加载板块缓存"""
    if SECTOR_CACHE.exists():
        try:
            return json.loads(SECTOR_CACHE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            pass
    return {}


def _save_sector_cache(data: dict):
    """保存板块缓存"""
    CACHE_DIR.mkdir(exist_ok=True)
    SECTOR_CACHE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _fetch_sector_from_api(ticker: str) -> str | None:
    """从 Nasdaq Profile API 获取板块"""
    url = f"https://api.nasdaq.com/api/company/{ticker}/company-profile"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            data = resp.json() or {}
            profile = data.get("data") or {}
            sector = (profile.get("Sector") or {}).get("value")
            return sector if sector else None
    except Exception:
        pass
    return None


# 模块级缓存（内存），避免同一次拉取中重复读文件
_sector_mem_cache: dict = {}


def get_sector(ticker: str) -> str:
    """
    获取 ticker 的板块。优先级：内存缓存 → 静态映射 → 磁盘缓存 → API 调用。
    返回板块名或 "—"。
    """
    global _sector_mem_cache
    ticker = ticker.upper()

    # 1. 内存缓存
    if ticker in _sector_mem_cache:
        return _sector_mem_cache[ticker]

    # 2. 静态映射
    if ticker in _SECTOR_STATIC:
        _sector_mem_cache[ticker] = _SECTOR_STATIC[ticker]
        return _SECTOR_STATIC[ticker]

    # 3. 磁盘缓存
    if not _sector_mem_cache:
        _sector_mem_cache = _load_sector_cache()
    if ticker in _sector_mem_cache:
        return _sector_mem_cache[ticker]

    # 4. API 调用
    sector = _fetch_sector_from_api(ticker)
    if sector:
        _sector_mem_cache[ticker] = sector
        # 增量写入磁盘缓存
        disk_cache = _load_sector_cache()
        disk_cache[ticker] = sector
        _save_sector_cache(disk_cache)
        return sector

    # 未找到
    _sector_mem_cache[ticker] = "—"
    return "—"


# ── S&P 500 成分股列表 ─────────────────────────────────────────────────────────

# 静态回退列表：当 Wikipedia 不可达时使用（覆盖大部分知名大盘股）
_SP500_FALLBACK = {
    "AAPL", "MSFT", "AMZN", "NVDA", "GOOGL", "GOOG", "META", "BRK-B", "TSLA",
    "UNH", "XOM", "JNJ", "JPM", "V", "PG", "MA", "AVGO", "HD", "LLY", "MRK",
    "CVX", "ABBV", "COST", "PEP", "KO", "ADBE", "WMT", "MCD", "CSCO", "CRM",
    "BAC", "PFE", "TMO", "ACN", "NFLX", "AMD", "ABT", "DHR", "LIN", "ORCL",
    "CMCSA", "TXN", "DIS", "NKE", "PM", "NEE", "WFC", "UPS", "RTX", "HON",
    "QCOM", "UNP", "LOW", "INTU", "SPGI", "IBM", "BA", "BMY", "GE", "CAT",
    "AMGN", "ELV", "AMAT", "GS", "DE", "ISRG", "MDT", "MS", "BLK", "ADP",
    "GILD", "VRTX", "SYK", "ADI", "REGN", "MMC", "SCHW", "CI", "T", "CB",
    "LRCX", "ZTS", "MO", "BKNG", "MDLZ", "PGR", "AXP", "TMUS", "SO", "DUK",
    "CL", "EOG", "CME", "TGT", "SLB", "SNPS", "ITW", "CDNS", "NOC", "BDX",
    "MMM", "COP", "FDX", "USB", "WM", "TJX", "MU", "PNC", "CSX", "KLAC",
    "APD", "ORLY", "ICE", "SHW", "NSC", "MCO", "EMR", "AIG", "GD", "F",
    "GM", "PSA", "MAR", "HUM", "MCHP", "FTNT", "ROP", "MET", "KMB", "D",
    "AEP", "CTAS", "SRE", "OXY", "PANW", "DXCM", "CCI", "A", "AZO", "KDP",
    "TRV", "AFL", "ALL", "SPG", "O", "MSCI", "HLT", "PCAR", "NUE", "CARR",
    "TEL", "MNST", "GIS", "WELL", "PSX", "WMB", "VLO", "PCG", "CTVA", "CMG",
    "HCA", "DVN", "EW", "BIIB", "ROST", "DG", "DLTR", "YUM", "KHC", "FAST",
    "STZ", "PPG", "HSY", "IDXX", "ED", "PAYX", "AWK", "IQV", "MTD", "ON",
    "CPRT", "VRSK", "ODFL", "BKR", "GEHC", "FANG", "MPWR", "CSGP", "CDW",
    "EXC", "XEL", "ACGL", "HPQ", "DOW", "CTSH", "ULTA", "GWW", "HAL", "LULU",
    "HPE", "CRWD", "DECK", "SMCI", "WDAY", "ABNB", "COIN", "PLTR", "UBER",
}


def fetch_sp500_list(force=False) -> set:
    """
    从 Wikipedia 获取 S&P 500 成分股列表，缓存 7 天。
    网络失败时使用静态回退列表。
    返回 ticker 集合（大写）。
    """
    if not force and SP500_CACHE.exists():
        data = json.loads(SP500_CACHE.read_text(encoding="utf-8"))
        cached_time = datetime.fromisoformat(data.get("updated", "2000-01-01"))
        if datetime.now() - cached_time < timedelta(days=7):
            return set(data.get("tickers", []))

    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", {"id": "constituents"})
        if not table:
            table = soup.find("table", class_="wikitable")
        tickers = set()
        if table:
            for row in table.find_all("tr")[1:]:
                cols = row.find_all("td")
                if cols:
                    ticker = cols[0].get_text(strip=True).replace(".", "-")
                    tickers.add(ticker.upper())
        if tickers:
            CACHE_DIR.mkdir(exist_ok=True)
            SP500_CACHE.write_text(json.dumps({
                "updated": datetime.now().isoformat(),
                "tickers": sorted(tickers)
            }, ensure_ascii=False), encoding="utf-8")
        return tickers
    except Exception as e:
        print(f"[earnings] Wikipedia 不可达，使用静态 S&P 500 列表: {e}")
        # 优先尝试过期缓存
        if SP500_CACHE.exists():
            data = json.loads(SP500_CACHE.read_text(encoding="utf-8"))
            return set(data.get("tickers", []))
        # 最终回退：静态列表
        return _SP500_FALLBACK


# ── Nasdaq API 相关 ────────────────────────────────────────────────────────────

def parse_market_cap(cap_str: str) -> int:
    """解析 Nasdaq 格式市值 '$210,340,320,000' → 整数"""
    if not cap_str:
        return 0
    cleaned = cap_str.replace("$", "").replace(",", "").strip()
    try:
        return int(cleaned)
    except (ValueError, TypeError):
        return 0


def format_market_cap(value: int) -> str:
    """格式化市值为可读字符串 '~210B' 或 '~3.5T'"""
    if value >= 1_000_000_000_000:
        return f"~{value / 1_000_000_000_000:.1f}T"
    elif value >= 1_000_000_000:
        return f"~{value / 1_000_000_000:.0f}B"
    else:
        return f"~{value / 1_000_000:.0f}M"


def map_timing(time_str: str) -> str:
    """映射 Nasdaq time 字段为中文"""
    mapping = {
        "time-pre-market": "盘前",
        "time-after-hours": "盘后",
        "time-not-supplied": "未公布",
    }
    return mapping.get(time_str, "未公布")


def fetch_earnings_for_date(date_str: str, retries: int = 2) -> list:
    """
    调用 Nasdaq earnings calendar API 获取指定日期的财报数据。
    date_str 格式: 'YYYY-MM-DD'
    返回原始 rows 列表。
    """
    url = "https://api.nasdaq.com/api/calendar/earnings"
    params = {"date": date_str}

    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                try:
                    data = resp.json() or {}
                except Exception:
                    return []
                rows = (data.get("data") or {}).get("rows")
                return rows if rows else []
            elif resp.status_code == 429:
                time.sleep(3 * (attempt + 1))
            else:
                print(f"[earnings] {date_str} 状态码 {resp.status_code}")
                return []
        except requests.RequestException as e:
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
            else:
                print(f"[earnings] {date_str} 请求失败: {e}")
                return []
    return []


def filter_large_cap(rows: list) -> list:
    """过滤大盘股：市值 > MIN_MARKET_CAP 且分析师覆盖 > MIN_ESTIMATES"""
    result = []
    for row in rows:
        cap = parse_market_cap(row.get("marketCap", ""))
        try:
            num_ests = int(row.get("noOfEsts", "0"))
        except (ValueError, TypeError):
            num_ests = 0

        if cap >= MIN_MARKET_CAP and num_ests >= MIN_ESTIMATES:
            result.append(row)
    return result


# ── 缓存读写（按月累积，不同月份数据共存）─────────────────────────────────────

def _load_cache() -> dict:
    """
    加载缓存文件。结构：
    {
        "calendar": { "2026-06-02": [...], "2026-07-10": [...], ... },
        "months_fetched": { "2026-06": "2026-05-31T10:00:00", ... }
    }
    """
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            pass
    return {"calendar": {}, "months_fetched": {}}


def _save_cache(data: dict):
    CACHE_DIR.mkdir(exist_ok=True)
    CACHE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ── 构建日历（按月）──────────────────────────────────────────────────────────────

def _fetch_entries_for_date(date_str: str, sp500: set) -> list:
    """拉取单日数据并转换为标准条目列表（已过滤大盘股）"""
    rows = fetch_earnings_for_date(date_str)
    if not rows:
        return []
    important = filter_large_cap(rows)
    entries = []
    for row in important:
        cap_raw = parse_market_cap(row.get("marketCap", ""))
        ticker = row.get("symbol", "").upper()
        eps_actual = row.get("epsActual", "")
        surprise = row.get("surprise", "")
        entry = {
            "ticker": ticker,
            "name": row.get("name", ""),
            "date": date_str,
            "time": map_timing(row.get("time", "")),
            "market_cap": format_market_cap(cap_raw),
            "market_cap_raw": cap_raw,
            "sp500": ticker in sp500,
            "sector": get_sector(ticker),
            "eps_forecast": row.get("epsForecast", ""),
            "eps_actual": eps_actual if eps_actual else "",
            "surprise": surprise if surprise else "",
            "num_estimates": int(row.get("noOfEsts", "0") or "0"),
            "confirmed": row.get("time", "") != "time-not-supplied",
            "reported": bool(eps_actual and eps_actual.strip()),
        }
        entries.append(entry)
    entries.sort(key=lambda x: x["market_cap_raw"], reverse=True)
    return entries


def build_calendar_for_month(year: int, month: int) -> dict:
    """
    拉取指定年月的所有交易日财报数据，合并进缓存并返回完整缓存。
    """
    # 复用流式版本，但不返回生成器，直接消费完
    result = {}
    for event in stream_calendar_for_month(year, month):
        if event.get("status") == "done":
            result = event.get("result", {})
    return result


def stream_calendar_for_month(year: int, month: int):
    """
    生成器版本：逐日拉取，每处理完一天 yield 一个进度 dict。
    供 SSE 流式推送使用。

    yield 格式：
      {"status": "start",    "total": 22}
      {"status": "progress", "processed": 5, "total": 22, "date": "2026-07-08", "found": 3}
      {"status": "done",     "total_found": 47, "result": {...}}
    """
    import calendar as cal_mod
    sp500 = fetch_sp500_list()
    cache = _load_cache()
    calendar_data = cache.get("calendar", {})
    months_fetched = cache.get("months_fetched", {})

    month_key = f"{year}-{month:02d}"
    _, days_in_month = cal_mod.monthrange(year, month)

    trading_days = [
        datetime(year, month, d).strftime("%Y-%m-%d")
        for d in range(1, days_in_month + 1)
        if datetime(year, month, d).weekday() < 5
    ]
    total = len(trading_days)
    total_found = 0

    print(f"[earnings] 正在拉取 {year}年{month}月 财报数据，共 {total} 个交易日...")
    yield {"status": "start", "total": total, "processed": 0}

    for processed, date_str in enumerate(trading_days, 1):
        entries = _fetch_entries_for_date(date_str, sp500)
        if entries:
            calendar_data[date_str] = entries
            total_found += len(entries)
        elif date_str in calendar_data:
            del calendar_data[date_str]

        time.sleep(0.5)
        yield {"status": "progress", "processed": processed, "total": total,
               "date": date_str, "found": len(entries)}

    months_fetched[month_key] = datetime.now().isoformat()
    cache["calendar"] = calendar_data
    cache["months_fetched"] = months_fetched
    _save_cache(cache)

    print(f"[earnings] {month_key} 完成，共 {total_found} 家大盘股财报")
    yield {"status": "done", "total_found": total_found, "result": _build_response(cache)}


def _build_response(cache: dict) -> dict:
    """
    从缓存构造 API 响应，附带 watchlist 和 months_fetched 信息。
    """
    today = datetime.now().date()
    watchlist_cutoff = today + timedelta(days=7)
    all_entries = [e for entries in cache["calendar"].values() for e in entries]
    watchlist = [
        e for e in all_entries
        if datetime.strptime(e["date"], "%Y-%m-%d").date() >= today
        and datetime.strptime(e["date"], "%Y-%m-%d").date() <= watchlist_cutoff
    ]
    watchlist.sort(key=lambda x: (x["date"], -x["market_cap_raw"]))
    return {
        "calendar": cache.get("calendar", {}),
        "months_fetched": cache.get("months_fetched", {}),
        "watchlist": watchlist,
    }


def get_calendar() -> dict:
    """返回当前缓存数据（不自动拉取）"""
    return _build_response(_load_cache())


# 保留旧名供 app.py 兼容
def build_calendar(days: int = 30) -> dict:
    """兼容旧调用：拉取当月数据"""
    today = datetime.now()
    return build_calendar_for_month(today.year, today.month)


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3:
        y, m = int(sys.argv[1]), int(sys.argv[2])
    else:
        t = datetime.now()
        y, m = t.year, t.month
    result = build_calendar_for_month(y, m)
    print(json.dumps(result, indent=2, ensure_ascii=False))
