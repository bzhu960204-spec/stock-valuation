# Stock Valuation

美股估值数据面板 - 一键拉取并展示股票估值指标。

## 快速启动

**Windows:** 双击 `start.bat` 即可，自动创建虚拟环境、安装依赖、启动服务。

启动后浏览器访问 http://localhost:5000

## 架构

- **后端**: Python Flask，提供 API 接口 + 服务前端静态文件（单进程，无需分别启动）
- **前端**: 原生 HTML/CSS/JS，由 Flask 直接托管

## 数据来源

所有数据来自 [stockanalysis.com](https://stockanalysis.com)，通过 HTTP 请求获取页面后解析 HTML 表格。

| 指标 | 来源页面 | 方法 |
|------|----------|------|
| 季度毛利率 (Gross Margin) Q1-Q4 | `/stocks/{ticker}/financials/?p=quarterly` | 解析季度利润表，Gross Profit ÷ Revenue |
| 季度净利率 (Net Margin) Q1-Q4 | `/stocks/{ticker}/financials/?p=quarterly` | 解析季度利润表，Net Income ÷ Revenue |
| TTM 毛利率 / 净利率 | 同上 | 4个季度加总后计算 |
| EV/FCF (企业价值/自由现金流) | `/stocks/{ticker}/statistics/` | 从 statistics 页面提取 Enterprise Value 和 Free Cash Flow，手动相除 |
| ROIC 历史 (4年) | `/stocks/{ticker}/financials/ratios/` | 从 ratios 页面 ROIC 行提取近4个财年数据 |

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/valuations` | 获取所有缓存的估值数据 |
| POST | `/api/fetch` | 拉取指定股票数据，body: `{"tickers": ["AAPL", "MSFT"]}` |
| POST | `/api/delete` | 删除指定股票，body: `{"ticker": "AAPL"}` |

## 项目结构

```
Stock Valuation/
├── app.py                 # Flask 后端 (API + 静态文件服务)
├── valuation_fetcher.py   # 估值数据拉取模块
├── fetch_valuations.py    # 原始参考脚本
├── requirements.txt       # Python 依赖
├── start.bat              # Windows 一键启动脚本
├── static/
│   ├── index.html         # 前端页面
│   ├── style.css          # 样式
│   └── app.js             # 前端逻辑
├── cache/
│   └── valuations.json    # 数据缓存 (自动生成)
└── README.md
```

## 依赖

- Python 3.10+
- flask
- requests
- beautifulsoup4
