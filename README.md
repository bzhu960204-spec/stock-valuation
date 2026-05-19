# Stock Valuation

全球股票 + A股估值数据面板 — 一键拉取并展示核心估值指标，支持手动录入补充数据。

## 快速启动

**Windows:** 双击 `start.bat` 即可，自动创建虚拟环境、安装依赖、启动服务。

启动后浏览器访问 http://localhost:5000

## 架构

- **后端**: Python Flask，提供 API 接口 + 服务前端静态文件（单进程，无需分别启动）
- **前端**: 原生 HTML/CSS/JS，由 Flask 直接托管
- **双模块**: 全球股票与A股完全分离，独立缓存，独立数据源

## 数据来源

### 全球 / 美股 (`valuation_fetcher.py`)

数据全部来自 [stockanalysis.com](https://stockanalysis.com)，HTTP 请求 + BeautifulSoup 解析 HTML 表格。

| 字段 | 页面 URL | 解析方式 |
|------|----------|----------|
| 季度毛利率 / 营业利润率 / 净利率 (Q1-Q4) | `.../financials/?p=quarterly` | 解析季度利润表，各利润项 ÷ Revenue |
| EV/FCF | `.../statistics/` | Enterprise Value ÷ Free Cash Flow |
| Forward PS | `.../statistics/` 或 `.../forecast/` | 直接读取，或 Market Cap ÷ 预期营收 |
| PE / Fwd PE / PS / ROIC 历史 (4年) | `.../financials/ratios/` | 解析 ratios 页面对应行 |

支持股票代码格式：`AAPL`（美股）/ `STO:SIVE`（北欧交易所）/ 其他交易所前缀格式。

每只股票约需 **5-8 秒**（3次页面请求）。

---

### A股 (`cn_valuation_fetcher.py`)

直接调用东方财富 / 百度股市通的 REST JSON API，**无分页、无阻塞**（绕开 akshare 的逐页爬取）。

| 字段 | 数据源 | API | 耗时 |
|------|--------|-----|------|
| 季度毛利率 / 营业利润率 / 净利率 (Q1-Q4) | 东方财富 | `datacenter.eastmoney.com` `RPT_DMSK_FN_INCOME` | ~2s |
| ROIC 历史 (近4年年报) | 东方财富 | `datacenter.eastmoney.com` `RPT_F10_FINANCE_MAINFINADATA` | ~2s |
| PE TTM | 百度股市通 | `gushitong.baidu.com/opendata` indicator=`市盈率(TTM)` | ~7s |
| PS TTM | 推算 | `PE × (年度净利润 / 年度营收)` | 0s |
| EV/FCF / Fwd PE / Fwd PS | — | 暂无免费实时数据源，留空可手动录入 | — |

> **备注**: `RPT_DMSK_FN_INCOME` 返回的是累计 YTD 数据，模块内部通过差值还原为单季度数据。
> ROIC 字段来自东方财富财务分析页，单位为 %（模块内已自动除以 100）。

支持A股代码格式：`600519` / `600519.SH` / `000001.SZ` / `SH:601318`。

每只股票约需 **10-12 秒**（2次东方财富请求 + 1次百度请求）。

---

## API 接口

### 全球 / 美股

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/valuations`      | 获取全部缓存数据 |
| POST | `/api/fetch`           | 拉取数据，body: `{"tickers": ["AAPL"]}` |
| POST | `/api/delete`          | 删除，body: `{"ticker": "AAPL"}` |
| POST | `/api/update`          | 手动更新字段，body: `{"ticker","field","value"}` |

### A股

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/cn/valuations`   | 获取A股缓存数据 |
| POST | `/api/cn/fetch`        | 拉取A股数据，body: `{"tickers": ["600519"]}` |
| POST | `/api/cn/delete`       | 删除，body: `{"ticker": "600519"}` |
| POST | `/api/cn/update`       | 手动更新字段，body: `{"ticker","field","value"}` |

## 项目结构

```
Stock Valuation/
├── app.py                   # Flask 后端 (全球 + A股 API + 静态文件服务)
├── valuation_fetcher.py     # 全球/美股数据拉取模块 (stockanalysis.com)
├── cn_valuation_fetcher.py  # A股数据拉取模块 (东方财富 + 百度)
├── fetch_valuations.py      # CLI 参考脚本
├── requirements.txt         # Python 依赖
├── start.bat                # Windows 一键启动脚本
├── static/
│   ├── index.html           # 前端页面 (含 全球/A股 Tab 切换)
│   ├── style.css            # 样式
│   └── app.js               # 前端逻辑
├── cache/
│   ├── valuations.json      # 全球/美股数据缓存
│   └── cn_valuations.json   # A股数据缓存
└── README.md
```

## 依赖

- Python 3.10+
- flask
- requests
- beautifulsoup4
