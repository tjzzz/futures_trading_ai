#!/bin/bash
# 数据采集一键执行脚本
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

# ── 带颜色输出 ──
RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
step() { echo -e "${CYAN}[$(date +%H:%M:%S)]${NC} $1"; }
ok()   { echo -e "  ${GREEN}✅${NC} $1"; }
fail() { echo -e "  ${RED}❌${NC} $1"; }

# ── 运行一个采集器：参数 1=标识 2=模块 3=描述 ──
run() {
    step "采集: $3"
    if python3 -m "$2" 2>"$LOG_DIR/$1_error.log"; then
        ok "$3 完成"
    else
        local e=$(tail -3 "$LOG_DIR/$1_error.log" 2>/dev/null | tr '\n' ' ')
        fail "$3 失败: $e"
    fi
}

# ── 主逻辑 ──
echo "========== 期货AI数据采集 =========="

case "${1:-}" in
    --realtime|-r)
        run gold_silver   collectors.gold_silver   "金银现货 (gold-api)"
        run yahoo_finance collectors.yahoo_finance "DXY/US10Y/VIX/期货 (Yahoo)"
        ;;
    --daily|-d)
        run daily              collectors.daily              "美债/FRED/CBOE 日频"
        run rss_news           collectors.rss_news           "RSS 新闻事件"
        run gold_silver_daily  collectors.gold_silver_daily  "金银日频（模拟数据）"
        ;;
    --historical|-h)
        step "回填 Treasury/TIPS/DXY/SP500/VIX 2026年历史数据..."
        if python3 -m collectors.backfill_2026 2>"$LOG_DIR/backfill_error.log"; then
            ok "历史回填完成"
        else
            local e=$(tail -3 "$LOG_DIR/backfill_error.log" 2>/dev/null | tr '\n' ' ')
            fail "历史回填失败: $e"
        fi
        ;;
    --help|-help)
        echo "用法: ./run_all_collectors.sh [选项]"
        echo "  --realtime, -r   仅实时行情（金银 + Yahoo）"
        echo "  --daily, -d      仅日频（美债/FRED/RSS/金银）"
        echo "  --historical, -h 仅回填 2026 年历史"
        echo "  无参数           三个都执行"
        exit 0
        ;;
    "")
        # 无参数——全部执行
        run daily              collectors.daily              "美债/FRED/CBOE 日频"
        run rss_news           collectors.rss_news           "RSS 新闻事件"
        run gold_silver_daily  collectors.gold_silver_daily  "金银日频（模拟数据）"
        step "回填 Treasury/TIPS/DXY/SP500/VIX 2026年历史数据..."
        python3 -m collectors.backfill_2026 2>"$LOG_DIR/backfill_error.log" \
            && ok "历史回填完成" || fail "历史回填失败"
        run gold_silver   collectors.gold_silver   "金银现货 (gold-api)"
        run yahoo_finance collectors.yahoo_finance "DXY/US10Y/VIX/期货 (Yahoo)"
        ;;
    *)
        echo "未知选项: $1"
        echo "使用 --help 查看帮助"
        exit 1
        ;;
esac

echo ""
echo "  日志: $LOG_DIR/"
echo "=============================="
