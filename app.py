"""
Stock Valuation - Flask Backend

提供 API 接口获取股票估值数据，同时服务前端静态文件。
一个进程同时处理前端和后端。
"""

import json
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory

from valuation_fetcher import fetch_multiple, build_valuation

app = Flask(__name__, static_folder="static", static_url_path="")

# 缓存文件路径
CACHE_FILE = Path(__file__).parent / "cache" / "valuations.json"


def load_cache() -> list:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    return []


def save_cache(data: list):
    CACHE_FILE.parent.mkdir(exist_ok=True)
    CACHE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


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


if __name__ == "__main__":
    print("\n  Stock Valuation 服务启动中...")
    print("  打开浏览器访问: http://localhost:5000\n")
    app.run(host="127.0.0.1", port=5000, debug=True)
