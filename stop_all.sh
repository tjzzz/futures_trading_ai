#!/bin/bash

# 期货交易AI系统停止脚本
# 一键停止所有服务

set -e

echo "=========================================="
echo "  期货交易AI系统 V2 - 停止脚本"
echo "=========================================="

# 进入项目目录
cd "$(dirname "$0")"

# 停止飞书服务器
echo "停止飞书服务器..."
if pkill -f "python3.*start.py"; then
    echo "✅ 飞书服务器已停止"
else
    echo "ℹ️  没有找到飞书服务器进程"
fi

# 停止仪表盘服务器
echo "停止仪表盘服务器..."
if pkill -f "python3.*dashboard.app"; then
    echo "✅ 仪表盘服务器已停止"
else
    echo "ℹ️  没有找到仪表盘服务器进程"
fi

# 停止后台采集进程
echo "检查后台采集进程..."
if pkill -f "python3.*collectors.gold_silver"; then
    echo "✅ gold_silver 采集器已停止"
fi
if pkill -f "python3.*collectors.yahoo_finance"; then
    echo "✅ yahoo_finance 采集器已停止"
fi

# 检查端口是否释放
echo "检查端口释放..."
sleep 2

if ! lsof -i :8080 &> /dev/null; then
    echo "✅ 端口8080已释放"
else
    echo "⚠️  端口8080仍被占用，请手动检查"
    lsof -i :8080
fi

if ! lsof -i :8082 &> /dev/null; then
    echo "✅ 端口8082已释放"
else
    echo "⚠️  端口8082仍被占用，请手动检查"
    lsof -i :8082
fi

echo "------------------------------------------"
echo "所有服务已停止!"
echo ""
echo "📋 日志文件位置:"
echo "  飞书日志: feishu.log"
echo "  仪表盘日志: dashboard.log"
echo ""
echo "🔄 重新启动: ./start_all.sh"
echo "=========================================="