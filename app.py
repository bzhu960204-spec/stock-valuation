"""
Stock Valuation - Flask Backend

提供 API 接口获取股票估值数据，同时服务前端静态文件。
一个进程同时处理前端和后端。
"""

import json
import sqlite3
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory

from valuation_fetcher import fetch_multiple
from cn_valuation_fetcher import fetch_multiple_cn
from growth_fetcher import fetch_multiple_growth
from lhb_fetcher import fetch_latest_lhb, fetch_range, get_history_dates, get_lhb_by_date
from options_fetcher import fetch_options_chain, fetch_options_by_expiration

app = Flask(__name__, static_folder="static", static_url_path="")

# ── 缓存文件路径 ──────────────────────────────────────────────────────────────
CACHE_FILE        = Path(__file__).parent / "cache" / "valuations.json"
CACHE_FILE_CN     = Path(__file__).parent / "cache" / "cn_valuations.json"
CACHE_FILE_GROWTH = Path(__file__).parent / "cache" / "growth.json"
CACHE_FILE_OPTIONS = Path(__file__).parent / "cache" / "options_history.json"  # legacy, migrated to SQLite
DB_OPTIONS        = Path(__file__).parent / "cache" / "options.db"


def _load(path: Path) -> list:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return []


def _save(path: Path, data: list):
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_cache() -> list:
    return _load(CACHE_FILE)


def save_cache(data: list):
    _save(CACHE_FILE, data)


def load_cn_cache() -> list:
    return _load(CACHE_FILE_CN)


def save_cn_cache(data: list):
    _save(CACHE_FILE_CN, data)


def load_growth_cache() -> list:
    return _load(CACHE_FILE_GROWTH)


def save_growth_cache(data: list):
    _save(CACHE_FILE_GROWTH, data)


@app.route("/")
def portal():
    return send_from_directory("static", "portal.html")


@app.route("/valuation")
def valuation_page():
    return send_from_directory("static", "index.html")


@app.route("/growth")
def growth_page():
    return send_from_directory("static", "growth.html")


@app.route("/lhb")
def lhb_page():
    return send_from_directory("static", "lhb.html")


@app.route("/api/valuations", methods=["GET"])
def get_valuations():
    """获取缓存的所有估值数据"""
    data = load_cache()
    return jsonify(data)


@app.route("/api/fetch", methods=["POST"])
def fetch_valuations():
    """拉取指定股票的估值数据"""
    body = request.get_json()
    if not body or "tickers" not in body:
        return jsonify({"error": "请提供 tickers 列表"}), 400

    tickers = body["tickers"]
    if not isinstance(tickers, list) or len(tickers) == 0:
        return jsonify({"error": "tickers 必须是非空数组"}), 400

    # 限制单次请求最多10只
    if len(tickers) > 10:
        return jsonify({"error": "单次最多拉取10只股票"}), 400

    results = fetch_multiple(tickers)

    # 合并到缓存
    cache = load_cache()
    cache_map = {item["ticker"]: item for item in cache}
    for item in results:
        if "error" not in item:
            cache_map[item["ticker"]] = item

    updated_cache = list(cache_map.values())
    save_cache(updated_cache)

    return jsonify(results)


@app.route("/api/delete", methods=["POST"])
def delete_valuation():
    """从缓存中删除指定股票"""
    body = request.get_json()
    if not body or "ticker" not in body:
        return jsonify({"error": "请提供 ticker"}), 400

    ticker = body["ticker"].upper()
    cache = load_cache()
    cache = [item for item in cache if item["ticker"] != ticker]
    save_cache(cache)

    return jsonify({"success": True})


@app.route("/api/update", methods=["POST"])
def update_valuation():
    """手动更新某只股票的单个字段值"""
    body = request.get_json(force=True)
    ticker = (body.get("ticker") or "").upper()
    field = body.get("field") or ""
    raw_value = body.get("value")  # number | null

    if not ticker or not field:
        return jsonify({"error": "需要提供 ticker 和 field"}), 400

    # Convert to float or None
    if raw_value is None or str(raw_value).strip() == "":
        value = None
    else:
        try:
            value = float(str(raw_value).strip())
        except (ValueError, TypeError):
            return jsonify({"error": "无效数值"}), 400

    cache = load_cache()
    for item in cache:
        if item.get("ticker") == ticker:
            item[field] = value
            save_cache(cache)
            return jsonify({"ok": True})

    return jsonify({"error": "未找到该股票"}), 404


# ════════════════════════════════════════════════════════════════
#  A股模块  /api/cn/*
# ════════════════════════════════════════════════════════════════

@app.route("/api/cn/valuations", methods=["GET"])
def cn_get_valuations():
    return jsonify(load_cn_cache())


@app.route("/api/cn/fetch", methods=["POST"])
def cn_fetch_valuations():
    body = request.get_json()
    if not body or "tickers" not in body:
        return jsonify({"error": "请提供 tickers 列表"}), 400

    tickers = body["tickers"]
    if not isinstance(tickers, list) or len(tickers) == 0:
        return jsonify({"error": "tickers 必须是非空数组"}), 400

    if len(tickers) > 10:
        return jsonify({"error": "单次最多拉取10只股票"}), 400

    results = fetch_multiple_cn(tickers)

    cache = load_cn_cache()
    cache_map = {item["ticker"]: item for item in cache}
    for item in results:
        if "error" not in item:
            cache_map[item["ticker"]] = item
    save_cn_cache(list(cache_map.values()))

    return jsonify(results)


@app.route("/api/cn/delete", methods=["POST"])
def cn_delete_valuation():
    body = request.get_json()
    if not body or "ticker" not in body:
        return jsonify({"error": "请提供 ticker"}), 400

    ticker = body["ticker"].upper()
    cache = load_cn_cache()
    cache = [item for item in cache if item["ticker"] != ticker]
    save_cn_cache(cache)
    return jsonify({"success": True})


@app.route("/api/cn/update", methods=["POST"])
def cn_update_valuation():
    body = request.get_json(force=True)
    ticker = (body.get("ticker") or "").upper()
    field = body.get("field") or ""
    raw_value = body.get("value")

    if not ticker or not field:
        return jsonify({"error": "需要提供 ticker 和 field"}), 400

    if raw_value is None or str(raw_value).strip() == "":
        value = None
    else:
        try:
            value = float(str(raw_value).strip())
        except (ValueError, TypeError):
            return jsonify({"error": "无效数值"}), 400

    cache = load_cn_cache()
    for item in cache:
        if item.get("ticker") == ticker:
            item[field] = value
            save_cn_cache(cache)
            return jsonify({"ok": True})

    return jsonify({"error": "未找到该股票"}), 404


# ════════════════════════════════════════════════════════════════
#  增速模块  /api/growth/*
# ════════════════════════════════════════════════════════════════

@app.route("/api/growth/fetch", methods=["POST"])
def growth_fetch():
    """拉取指定美股的近五年收入及增长率"""
    body = request.get_json()
    if not body or "tickers" not in body:
        return jsonify({"error": "请提供 tickers 列表"}), 400

    tickers = body["tickers"]
    if not isinstance(tickers, list) or len(tickers) == 0:
        return jsonify({"error": "tickers 必须是非空数组"}), 400

    if len(tickers) > 10:
        return jsonify({"error": "单次最多查询10只股票"}), 400

    results = fetch_multiple_growth(tickers)

    # 合并到缓存
    cache = load_growth_cache()
    cache_map = {item["ticker"]: item for item in cache}
    for item in results:
        if "error" not in item:
            cache_map[item["ticker"]] = item
    save_growth_cache(list(cache_map.values()))

    return jsonify(results)


@app.route("/api/growth/data", methods=["GET"])
def growth_get_data():
    """返回缓存的所有增速数据"""
    return jsonify(load_growth_cache())


@app.route("/api/growth/delete", methods=["POST"])
def growth_delete():
    """从缓存中删除指定股票"""
    body = request.get_json()
    if not body or "ticker" not in body:
        return jsonify({"error": "请提供 ticker"}), 400
    ticker = body["ticker"].upper()
    cache = [item for item in load_growth_cache() if item["ticker"] != ticker]
    save_growth_cache(cache)
    return jsonify({"success": True})


# ════════════════════════════════════════════════════════════════
#  龙虎榜模块  /api/lhb/*
# ════════════════════════════════════════════════════════════════

@app.route("/api/lhb/fetch", methods=["POST"])
def lhb_fetch():
    """抓取最新交易日的龙虎榜数据"""
    result = fetch_latest_lhb()
    return jsonify(result)


@app.route("/api/lhb/fetch-range", methods=["POST"])
def lhb_fetch_range():
    """抓取指定日期区间的龙虎榜数据"""
    body = request.get_json()
    start_date = (body or {}).get("start_date", "").strip()
    end_date = (body or {}).get("end_date", "").strip()
    if not start_date or not end_date:
        return jsonify({"error": "请提供 start_date 和 end_date"}), 400
    result = fetch_range(start_date, end_date)
    return jsonify(result)


@app.route("/api/lhb/dates", methods=["GET"])
def lhb_dates():
    """获取已存储的所有交易日列表"""
    dates = get_history_dates()
    return jsonify(dates)


@app.route("/api/lhb/data", methods=["GET"])
def lhb_data():
    """按日期查询龙虎榜数据，参数 ?date=2024-05-20"""
    trade_date = request.args.get("date")
    if not trade_date:
        return jsonify({"error": "请提供 date 参数"}), 400
    items = get_lhb_by_date(trade_date)
    return jsonify({"trade_date": trade_date, "items": items, "count": len(items)})


# ════════════════════════════════════════════════════════════════
#  期权模块  /api/options/*
# ════════════════════════════════════════════════════════════════

def _get_options_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_OPTIONS))
    conn.row_factory = sqlite3.Row
    return conn


def _init_options_db():
    """建表 + 从旧 JSON 迁移数据（一次性）"""
    DB_OPTIONS.parent.mkdir(exist_ok=True)
    with _get_options_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS options_snapshots (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker        TEXT NOT NULL,
                snapshot_time TEXT NOT NULL,
                data_json     TEXT NOT NULL,
                UNIQUE(ticker, snapshot_time)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_options_ticker ON options_snapshots(ticker)")
        conn.commit()
    # 一次性迁移旧 JSON
    if CACHE_FILE_OPTIONS.exists():
        try:
            old = json.loads(CACHE_FILE_OPTIONS.read_text(encoding="utf-8"))
            with _get_options_db() as conn:
                for tkr, snaps in old.items():
                    for snap in snaps:
                        conn.execute(
                            "INSERT OR IGNORE INTO options_snapshots (ticker, snapshot_time, data_json) VALUES (?, ?, ?)",
                            (tkr.upper(), snap.get("snapshotTime", ""), json.dumps(snap, ensure_ascii=False))
                        )
                conn.commit()
            CACHE_FILE_OPTIONS.rename(CACHE_FILE_OPTIONS.with_suffix(".json.migrated"))
            print("[options] Migrated history from JSON to SQLite")
        except Exception as e:
            print(f"[options] Migration warning: {e}")


@app.route("/options")
def options_page():
    return send_from_directory("static", "options.html")


@app.route("/api/options/chain", methods=["POST"])
def options_chain():
    """获取指定股票最近行权日的期权链，并保存快照"""
    body = request.get_json()
    if not body or "ticker" not in body:
        return jsonify({"error": "请提供 ticker"}), 400

    ticker = body["ticker"].strip().upper()
    if not ticker:
        return jsonify({"error": "ticker 不能为空"}), 400

    result = fetch_options_chain(ticker)

    # 保存快照到 SQLite
    if "error" not in result and result.get("expirationSummary"):
        snapshot = {
            "snapshotTime": result.get("snapshotTime", ""),
            "expirationSummary": result["expirationSummary"],
            "expirationData": result.get("expirationData", {}),
        }
        try:
            with _get_options_db() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO options_snapshots (ticker, snapshot_time, data_json) VALUES (?, ?, ?)",
                    (ticker, snapshot["snapshotTime"], json.dumps(snapshot, ensure_ascii=False))
                )
                conn.commit()
        except Exception as e:
            print(f"[options] Snapshot save error: {e}")

    return jsonify(result)


@app.route("/api/options/chain-by-date", methods=["POST"])
def options_chain_by_date():
    """获取指定行权日期的期权链"""
    body = request.get_json()
    if not body or "ticker" not in body or "expiration" not in body:
        return jsonify({"error": "请提供 ticker 和 expiration"}), 400

    ticker = body["ticker"].strip().upper()
    expiration = body["expiration"].strip()

    if not ticker or not expiration:
        return jsonify({"error": "参数不能为空"}), 400

    result = fetch_options_by_expiration(ticker, expiration)
    return jsonify(result)


@app.route("/api/options/history", methods=["GET"])
def options_history_list():
    """返回所有已缓存的期权快照列表 (ticker -> 快照数量 + 最近时间)"""
    with _get_options_db() as conn:
        rows = conn.execute("""
            SELECT ticker, COUNT(*) as count, MAX(snapshot_time) as latest_time
            FROM options_snapshots
            GROUP BY ticker
            ORDER BY latest_time DESC
        """).fetchall()
    return jsonify([{"ticker": r["ticker"], "count": r["count"], "latestTime": r["latest_time"]} for r in rows])


@app.route("/api/options/history/<ticker>", methods=["GET"])
def options_history_detail(ticker):
    """返回指定股票的全部快照历史（按时间升序）"""
    ticker = ticker.strip().upper()
    with _get_options_db() as conn:
        rows = conn.execute(
            "SELECT data_json FROM options_snapshots WHERE ticker=? ORDER BY snapshot_time ASC",
            (ticker,)
        ).fetchall()
    snapshots = [json.loads(r["data_json"]) for r in rows]
    return jsonify({"ticker": ticker, "snapshots": snapshots})


@app.route("/api/options/delete-history", methods=["POST"])
def options_delete_history():
    """删除指定股票的快照历史"""
    body = request.get_json()
    if not body or "ticker" not in body:
        return jsonify({"error": "请提供 ticker"}), 400
    ticker = body["ticker"].strip().upper()
    with _get_options_db() as conn:
        conn.execute("DELETE FROM options_snapshots WHERE ticker=?", (ticker,))
        conn.commit()
    return jsonify({"success": True})


_init_options_db()

if __name__ == "__main__":
    print("\n  Stock Tools 服务启动中...")
    print("  打开浏览器访问: http://localhost:5000\n")
    app.run(host="127.0.0.1", port=5000, debug=True)
