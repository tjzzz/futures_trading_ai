#!/bin/bash

# 数据采集一键执行脚本
# 统一运行所有数据采集器，支持多种执行模式

set -e

# ── 配置 ────────────────────────────────────────────────
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$PROJECT_DIR/logs"
TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")
SUMMARY_LOG="$LOG_DIR/collector_summary.log"

mkdir -p "$LOG_DIR"

# ── 颜色输出 ────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

print_step()  { echo -e "${CYAN}[$(date +%H:%M:%S)]${NC} $1"; }
print_ok()    { echo -e "  ${GREEN}✅${NC} $1"; }
print_skip()  { echo -e "  ${YELLOW}⏭️${NC} $1"; }
print_fail()  { echo -e "  ${RED}❌${NC} $1"; }

# ── 日志 ────────────────────────────────────────────────
log_result() {
    local collector=$1
    local status=$2
    local detail=$3
    echo "$TIMESTAMP | $collector | $status | $detail" >> "$SUMMARY_LOG"
}

show_banner() {
    echo ""
    echo "============================================"
    echo "  期货AI交易体系 — 数据采集中心"
    echo "  $TIMESTAMP"
    echo "============================================"
    echo ""
}


# ════════════════════════════════════════════════════════
# 采集器执行函数
# ════════════════════════════════════════════════════════

run_collector() {
    local name=$1
    local module=$2
    local desc=$3

    print_step "正在采集: $desc ($module)..."
    if python3 -m "$module" 2>"$LOG_DIR/${name}_error.log"; then
        print_ok "$desc 完成"
        log_result "$name" "OK" ""
        return 0
    else
        local err=$(tail -3 "$LOG_DIR/${name}_error.log" 2>/dev/null | tr '\n' ' ')
        print_fail "$desc 失败: $err"
        log_result "$name" "FAIL" "$err"
        return 1
    fi
}

# ── 实时采集（5分钟级）──
run_realtime() {
    echo ""
    echo "────────── 实时行情采集 ──────────"
    run_collector "gold_silver"    "collectors.gold_silver"    "金银现货 (gold-api)"
    run_collector "yahoo_finance"  "collectors.yahoo_finance"  "DXY/US10Y/VIX/期货 (Yahoo)"
}

# ── 日频采集 ──
run_daily() {
    echo ""
    echo "────────── 日频数据采集 ──────────"
    run_collector "daily"         "collectors.daily"           "美债/FRED/CBOE 日频"
    run_collector "rss_news"      "collectors.rss_news"        "RSS 新闻事件"
    run_collector "gold_silver_daily" "collectors.gold_silver_daily" "金银日频（模拟数据）"
}

# ── 历史回填（2026年）──
run_historical() {
    echo ""
    echo "────────── 2026年历史回填 ──────────"
    print_step "正在回填 Treasury/TIPS/DXY/SP500/VIX 2026年历史数据..."
    if python3 -m collectors.backfill_2026 2>"$LOG_DIR/backfill_error.log"; then
        print_ok "历史回填完成"
        log_result "backfill_2026" "OK" ""
    else
        local err=$(tail -3 "$LOG_DIR/backfill_error.log" 2>/dev/null | tr '\n' ' ')
        print_fail "历史回填失败: $err"
        log_result "backfill_2026" "FAIL" "$err"
    fi
}

# ── 全部运行 ──
run_all() {
    run_historical
    run_daily
    run_realtime
}

# ── 显示汇总 ──
show_summary() {
    echo ""
    echo "────────── 采集汇总 ──────────"
    if [ -f "$SUMMARY_LOG" ]; then
        tail -20 "$SUMMARY_LOG" | while IFS=' | ' read -r ts name status detail; do
            if [ "$status" = "OK" ]; then
                echo -e "  ${GREEN}✅${NC} $name"
            elif [ "$status" = "FAIL" ]; then
                echo -e "  ${RED}❌${NC} $name — $detail"
            fi
        done
    fi
    echo ""
    echo "  详细日志: $LOG_DIR/"
    echo "  汇总日志: $SUMMARY_LOG"
    echo ""
}


# ════════════════════════════════════════════════════════
# 主入口
# ════════════════════════════════════════════════════════

show_banner

case "${1:-}" in
    --historical|-h)
        run_historical
        ;;
    --realtime|-r)
        run_realtime
        ;;
    --daily|-d)
        run_daily
        ;;
    --all|-a)
        run_all
        ;;
    --news|-n)
        run_collector "rss_news" "collectors.rss_news" "RSS 新闻事件"
        ;;
    --backfill-only)
        # 仅回填，无实时数据，适合离线跑
        run_historical
        run_daily
        ;;
    --help|-help)
        echo "用法: ./run_all_collectors.sh [选项]"
        echo ""
        echo "选项:"
        echo "  --all, -a               执行全部（历史回填 + 日频 + 实时）"
        echo "  --historical, -h        仅回填2026年历史数据"
        echo "  --backfill-only         历史回填 + 日频（不含实时，适合离线）"
        echo "  --realtime, -r          仅实时行情（金银 + Yahoo）"
        echo "  --daily, -d             仅日频数据（美债/FRED/RSS/金银）"
        echo "  --news, -n              仅 RSS 新闻"
        echo "  --help                  显示帮助"
        echo ""
        echo "无参数时默认执行 --all"
        echo ""
        echo "示例:"
        echo "  ./run_all_collectors.sh              # 全部执行"
        echo "  ./run_all_collectors.sh --realtime   # 仅实时行情"
        echo "  ./run_all_collectors.sh --historical # 仅回填历史"
        echo "  ./run_all_collectors.sh --backfill-only  # 离线跑历史"
        exit 0
        ;;
    *)
        # 默认：全部执行
        run_all
        ;;
esac

show_summary

echo "============================================"
echo "  采集任务结束"
echo "============================================"
