#!/bin/bash

# 期货交易AI系统启动脚本
# 一键启动所有服务

set -e

echo "=========================================="
echo "  期货交易AI系统 V2 - 一键启动脚本"
echo "=========================================="

# 进入项目目录
cd "$(dirname "$0")"

# 检查Python依赖
echo "检查Python依赖..."
if ! python3 -c "import requests, flask, matplotlib, pandas, numpy" &> /dev/null; then
    echo "正在安装依赖..."
    python3 -m pip install -r requirements.txt
fi

# 检查端口占用
echo "检查端口占用..."
if lsof -i :8080 &> /dev/null; then
    echo "⚠️  端口8080已被占用，请先停止相关进程"
    lsof -i :8080
    exit 1
fi

if lsof -i :8082 &> /dev/null; then
    echo "⚠️  端口8082已被占用，请先停止相关进程"
    lsof -i :8082
    exit 1
fi

# 启动飞书服务器
echo "启动飞书Webhook服务器（端口8080）..."
nohup python3 start.py --port 8080 > feishu.log 2>&1 &
FEISHU_PID=$!
echo "飞书服务器启动成功，PID: $FEISHU_PID"

# 等待2秒
sleep 2

# 启动仪表盘服务器
echo "启动仪表盘服务器（端口8082）..."
nohup python3 -m dashboard.app --port 8082 > dashboard.log 2>&1 &
DASHBOARD_PID=$!
echo "仪表盘服务器启动成功，PID: $DASHBOARD_PID"

# 首次数据采集（确保仪表盘启动后有实时数据）
echo "执行首次数据采集..."
python3 -m collectors.gold_silver 2>/dev/null || true
python3 -m collectors.yahoo_finance 2>/dev/null || true
echo "首次数据采集完成"

# 等待服务启动
echo "等待服务启动..."
sleep 3

# 检查服务状态
echo "检查服务状态..."
echo "------------------------------------------"

# 检查飞书服务器
if curl -s http://localhost:8080/api/health > /dev/null; then
    echo "✅ 飞书服务器运行正常 (http://localhost:8080)"
else
    echo "❌ 飞书服务器启动失败，查看日志: tail -f feishu.log"
fi

# 检查仪表盘服务器
if curl -s http://localhost:8082/api/health > /dev/null; then
    echo "✅ 仪表盘服务器运行正常 (http://localhost:8082)"
    echo "   仪表盘地址: http://localhost:8082"
else
    echo "❌ 仪表盘服务器启动失败，查看日志: tail -f dashboard.log"
fi

echo "------------------------------------------"

# 显示数据状态
echo "数据状态:"
curl -s http://localhost:8082/api/data | python3 -c "
import json, sys
data = json.load(sys.stdin)
print(f'  黄金现货: ${data.get(\"gold_price\",{}).get(\"value\",\"N/A\")}')
print(f'  白银现货: ${data.get(\"silver_price\",{}).get(\"value\",\"N/A\")}')
print(f'  黄金期货: ${data.get(\"gold_futures\",{}).get(\"value\",\"N/A\")}')
print(f'  白银期货: ${data.get(\"silver_futures\",{}).get(\"value\",\"N/A\")}')
print(f'  金银比: {data.get(\"gold_silver_ratio\",{}).get(\"value\",\"N/A\")}')
print(f'  10Y美债收益率: {data.get(\"treasury_10y\",{}).get(\"value\",\"N/A\")}%')
print(f'  美元指数 DXY: {data.get(\"dxy\",{}).get(\"value\",\"N/A\")}')
print(f'  VIX: {data.get(\"vix\",{}).get(\"value\",\"N/A\")}')
"

echo "------------------------------------------"
echo "启动完成!"
echo ""
echo "📊 仪表盘: http://localhost:8082"
echo "🤖 飞书命令: 宏观 / 归因 / 趋势 / 事件 / 监控"
echo ""
echo "📋 常用命令:"
echo "  查看飞书日志: tail -f feishu.log"
echo "  查看仪表盘日志: tail -f dashboard.log"
echo "  停止所有服务: pkill -f \"python3.*(start.py|dashboard.app)\""
echo "  查看进程: ps aux | grep python"
echo ""
echo "📊 运行采集器更新数据:"
echo "  python3 -m collectors.gold_silver     # 金银现货 (5min)"
echo "  python3 -m collectors.yahoo_finance   # DXY/US10Y/VIX/期货 (5min)"
echo "  python3 -m collectors.daily           # 每日数据"
echo "  python3 -m collectors.rss_news        # RSS新闻 (30min)"
echo "  python3 -m event_monitor.monitor      # 事件监控"
echo "=========================================="