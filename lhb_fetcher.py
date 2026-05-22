"""
龙虎榜数据拉取模块 (lhb_fetcher.py)

数据源: 东方财富 datacenter-web API
报表: RPT_DAILYBILLBOARD_DETAILSNEW

功能:
  - 抓取最新一个交易日的龙虎榜数据
  - 使用 SQLite 持久化存储历史数据
"""

import sqlite3
from datetime import datetime
from pathlib import Path

import requests

# ── 常量 ──────────────────────────────────────────────────────────────────────
_TIMEOUT = 15
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Referer": "https://data.eastmoney.com/",
}
_API_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

DB_PATH = Path(__file__).parent / "cache" / "lhb.db"


# ── 数据库初始化 ──────────────────────────────────────────────────────────────

def _get_db() -> sqlite3.Connection:
    """获取数据库连接，不存在则自动创建表"""
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS lhb (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date TEXT NOT NULL,
            security_code TEXT NOT NULL,
            security_name TEXT NOT NULL,
            explanation TEXT,
            explain_info TEXT,
            change_rate REAL,
            fetched_at TEXT NOT NULL,
            UNIQUE(trade_date, security_code, explanation)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_lhb_trade_date
        ON lhb(trade_date)
    """)
    conn.commit()
    return conn


# ── 数据抓取 ──────────────────────────────────────────────────────────────────

def fetch_latest_lhb() -> dict:
    """
    抓取最新一个交易日的龙虎榜数据并存入数据库。

    返回: {
        "trade_date": "2024-05-20",
        "items": [
            {"code": "000001", "name": "平安银行", "explanation": "...", "change_rate": 5.12},
            ...
        ],
        "count": 50
    }
    """
    # 不指定日期筛选，按日期倒序，取第一页即是最新交易日数据
    # 先获取最新交易日
    params = {
        "sortColumns": "TRADE_DATE,SECURITY_CODE",
        "sortTypes": "-1,1",
        "pageSize": "1",
        "pageNumber": "1",
        "reportName": "RPT_DAILYBILLBOARD_DETAILSNEW",
        "columns": "TRADE_DATE,SECURITY_CODE,SECURITY_NAME_ABBR,EXPLANATION,EXPLAIN,CHANGE_RATE",
        "source": "WEB",
        "client": "WEB",
    }

    resp = requests.get(_API_URL, params=params, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    if not data.get("result") or not data["result"].get("data"):
        return {"trade_date": None, "items": [], "count": 0}

    # 取到最新交易日
    latest_date_str = data["result"]["data"][0]["TRADE_DATE"]  # "2024-05-20 00:00:00"
    trade_date = latest_date_str.split(" ")[0]  # "2024-05-20"

    # 用该日期筛选，抓取全部数据（分页）
    all_items = []
    page = 1
    while True:
        params2 = {
            "sortColumns": "SECURITY_CODE",
            "sortTypes": "1",
            "pageSize": "200",
            "pageNumber": str(page),
            "reportName": "RPT_DAILYBILLBOARD_DETAILSNEW",
            "columns": "TRADE_DATE,SECURITY_CODE,SECURITY_NAME_ABBR,EXPLANATION,EXPLAIN,CHANGE_RATE",
            "source": "WEB",
            "client": "WEB",
            "filter": f"(TRADE_DATE='{trade_date}')",
        }
        resp2 = requests.get(_API_URL, params=params2, headers=_HEADERS, timeout=_TIMEOUT)
        resp2.raise_for_status()
        page_data = resp2.json()

        if not page_data.get("result") or not page_data["result"].get("data"):
            break

        rows = page_data["result"]["data"]
        for row in rows:
            all_items.append({
                "code": row["SECURITY_CODE"],
                "name": row["SECURITY_NAME_ABBR"],
                "explanation": row["EXPLANATION"] or "",
                "explain_info": row.get("EXPLAIN") or "",
                "change_rate": row["CHANGE_RATE"],
            })

        # 检查是否还有下一页
        total_pages = page_data["result"].get("pages", 1)
        if page >= total_pages:
            break
        page += 1

    # 存入数据库
    _save_to_db(trade_date, all_items)

    return {
        "trade_date": trade_date,
        "items": all_items,
        "count": len(all_items),
    }


def _save_to_db(trade_date: str, items: list):
    """将数据存入 SQLite，重复数据跳过"""
    conn = _get_db()
    now = datetime.now().isoformat(timespec="seconds")
    for item in items:
        conn.execute(
            """
            INSERT OR IGNORE INTO lhb (trade_date, security_code, security_name, explanation, explain_info, change_rate, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (trade_date, item["code"], item["name"], item["explanation"], item["explain_info"], item["change_rate"], now),
        )
    conn.commit()
    conn.close()


# ── 查询历史 ──────────────────────────────────────────────────────────────────

def fetch_range(start_date: str, end_date: str) -> dict:
    """
    抓取指定日期区间内所有交易日的龙虎榜数据并存入数据库。

    返回: {
        "dates_fetched": ["2024-05-19", "2024-05-20"],
        "total_records": 160
    }
    """
    all_rows = []
    page = 1
    while True:
        params = {
            "sortColumns": "TRADE_DATE,SECURITY_CODE",
            "sortTypes": "1,1",
            "pageSize": "500",
            "pageNumber": str(page),
            "reportName": "RPT_DAILYBILLBOARD_DETAILSNEW",
            "columns": "TRADE_DATE,SECURITY_CODE,SECURITY_NAME_ABBR,EXPLANATION,EXPLAIN,CHANGE_RATE",
            "source": "WEB",
            "client": "WEB",
            "filter": f"(TRADE_DATE>='{start_date}')(TRADE_DATE<='{end_date}')",
        }
        resp = requests.get(_API_URL, params=params, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        if not data.get("result") or not data["result"].get("data"):
            break

        all_rows.extend(data["result"]["data"])

        total_pages = data["result"].get("pages", 1)
        if page >= total_pages:
            break
        page += 1

    # 按交易日分组存储
    grouped: dict = {}
    for row in all_rows:
        date_str = row["TRADE_DATE"].split(" ")[0]
        grouped.setdefault(date_str, []).append({
            "code": row["SECURITY_CODE"],
            "name": row["SECURITY_NAME_ABBR"],
            "explanation": row["EXPLANATION"] or "",
            "explain_info": row.get("EXPLAIN") or "",
            "change_rate": row["CHANGE_RATE"],
        })

    for date_str, items in grouped.items():
        _save_to_db(date_str, items)

    return {
        "dates_fetched": sorted(grouped.keys()),
        "total_records": len(all_rows),
    }


def get_history_dates() -> list:
    """返回数据库中所有已存储的交易日列表（倒序）"""
    conn = _get_db()
    rows = conn.execute(
        "SELECT DISTINCT trade_date FROM lhb ORDER BY trade_date DESC"
    ).fetchall()
    conn.close()
    return [r["trade_date"] for r in rows]


def get_lhb_by_date(trade_date: str) -> list:
    """按日期查询龙虎榜数据"""
    conn = _get_db()
    rows = conn.execute(
        "SELECT security_code, security_name, explanation, explain_info, change_rate FROM lhb WHERE trade_date = ? ORDER BY security_code",
        (trade_date,),
    ).fetchall()
    conn.close()
    return [
        {
            "code": r["security_code"],
            "name": r["security_name"],
            "explanation": r["explanation"],
            "explain_info": r["explain_info"],
            "change_rate": r["change_rate"],
        }
        for r in rows
    ]
