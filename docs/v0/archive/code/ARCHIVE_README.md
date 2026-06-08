# 代码归档说明

> 归档时间: 2026-06-02
> 整理人: Claude Code — 项目冗余代码归档

## 归档原因

经全面扫描项目 import 依赖关系，以下代码被确认为未使用/冗余代码，移入此目录保留备份。

| 原路径 | 归档文件名 | 原因 |
|--------|-----------|------|
| `shared/indicators.py` | `shared_indicators.py` | **无任何文件 import**。功能已被 `analysis/prediction/technical.py::ShortTermPredictor` 完全取代（MA/MACD/RSI/布林/ATR + 更多 CCI/支撑阻力） |
| `shared/config.py` | `shared_config_deprecated.py` | 已废弃存根，只抛 `ImportError`。V2 统一使用 `config/` 包 |
| `analysis/attribution/test_l1.py` | `attribution_test_l1.py` | 一次性测试脚本，import 路径已不正确（`from attribution.xxx` 而非 `from analysis.attribution.xxx`） |
| `analysis/attribution/test_l2.py` | `attribution_test_l2.py` | 同上 |
| `analysis/attribution/test_l3.py` | `attribution_test_l3.py` | 同上 |
| `config.py.bak` | `config_py_bak` | 旧 `config.py` 备份，新 `config/` 包已正常工作 |
| `test_causal.html` | — | 根目录临时测试 HTML |
| `test_data.html` | — | 根目录临时测试 HTML |
| `test_js.html` | — | 根目录临时测试 HTML |
| `test_js_execution.html` | — | 根目录临时测试 HTML |
| `test_trend_chart.js` | — | 根目录临时测试 JS |

## 未移动的模块

以下模块虽然未被 import，但通过 `python3 -m` 方式调用，属于活跃使用，保持不变：
- `collectors/gold_silver.py` — `run_all_collectors.sh` 中调用
- `collectors/gold_silver_daily.py` — 同上
- `collectors/yahoo_finance.py` — 同上
- `collectors/daily.py` — 同上
- `collectors/rss_news.py` — 同上（且被 dashboard/app.py import）
- `collectors/backfill_2026.py` — 同上
- `collectors/cleanup.py` — 同上
- `collectors/aggregate_daily.py` — 同上
- `collectors/base_collector.py` — 被其他 collectors import
- `event_monitor/monitor.py` — 被 `feishu/handlers.py` import

## 移除后验证结果

- `shared.DataClient` / `DataSource` — ✅ 正常
- `config` 包 — ✅ 正常
- `analysis` — ✅ 正常
- `analysis.engine.Analysis` — ✅ 正常
- `analysis.prediction.engine.PredictionEngine` — ✅ 正常
- `analysis.attribution.engine.run_attribution` — ✅ 正常