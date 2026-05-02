#!/usr/bin/env python3
"""
交易日志技能
整合自:
- futures_trading_skills/journal-skill/scripts/journal.py
- futures_trading_system/agents/trade_journal_agent.py
"""
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import json
import logging
import sqlite3
from pathlib import Path

from core import SkillAgent, Message


class TradeDirection(Enum):
    """交易方向"""
    LONG = "long"
    SHORT = "short"


class TradeErrorType(Enum):
    """交易错误类型"""
    SIGNAL_ERROR = "signal_error"
    EXECUTION_ERROR = "execution_error"
    RISK_VIOLATION = "risk_violation"
    MARKET_UNPREDICTABLE = "market_unpredictable"
    PSYCHOLOGY = "psychology"
    DISCIPLINE = "discipline"


@dataclass
class TradeRecord:
    """交易记录"""
    trade_id: str
    date: str
    symbol: str
    direction: str
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    lots: int
    gross_pnl: float
    net_pnl: float
    commission: float = 0
    slippage: float = 0
    holding_minutes: int = 0
    entry_reason: str = ""
    exit_reason: str = ""
    stop_loss: float = 0
    target_price: float = 0
    max_profit: float = 0
    max_drawdown: float = 0
    errors: List[str] = field(default_factory=list)
    notes: str = ""
    tags: List[str] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()

    def to_dict(self) -> Dict:
        return {
            "trade_id": self.trade_id,
            "date": self.date,
            "symbol": self.symbol,
            "direction": self.direction,
            "entry_time": self.entry_time,
            "exit_time": self.exit_time,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "lots": self.lots,
            "gross_pnl": self.gross_pnl,
            "net_pnl": self.net_pnl,
            "commission": self.commission,
            "slippage": self.slippage,
            "holding_minutes": self.holding_minutes,
            "entry_reason": self.entry_reason,
            "exit_reason": self.exit_reason,
            "stop_loss": self.stop_loss,
            "target_price": self.target_price,
            "max_profit": self.max_profit,
            "max_drawdown": self.max_drawdown,
            "errors": json.dumps(self.errors),
            "notes": self.notes,
            "tags": json.dumps(self.tags),
            "created_at": self.created_at
        }


@dataclass
class DailySummary:
    """每日汇总"""
    date: str
    total_pnl: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_profit: float
    avg_loss: float
    profit_loss_ratio: float
    max_single_win: float
    max_single_loss: float
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    discipline_score: int = 100
    notes: str = ""
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


class JournalSkill(SkillAgent):
    """
    交易日志技能
    功能:
    1. 交易记录存储
    2. 每日复盘报告
    3. 绩效统计
    4. 错误分析
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__("trade_journal", config)

        # 数据库路径
        self.db_path = config.get("db_path", "data/trade_journal.db")
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        # 初始化数据库
        self._init_db()

        # 注册命令
        self._register_commands()

    def _register_commands(self):
        """注册命令"""
        self.register_command("记录", self._cmd_record, "记录交易模板")
        self.register_command("添加", self._cmd_add, "添加交易记录（飞书格式）")
        self.register_command("复盘", self._cmd_review, "生成复盘报告，如: 复盘 2024-01-15")
        self.register_command("统计", self._cmd_stats, "统计信息，如: 统计 30")
        self.register_command("列表", self._cmd_list, "列出最近交易")

    # ==================== 数据库操作 ====================

    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """初始化数据库"""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    trade_id TEXT PRIMARY KEY,
                    date TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    entry_time TEXT,
                    exit_time TEXT,
                    entry_price REAL,
                    exit_price REAL,
                    lots INTEGER,
                    gross_pnl REAL,
                    net_pnl REAL,
                    commission REAL DEFAULT 0,
                    slippage REAL DEFAULT 0,
                    holding_minutes INTEGER DEFAULT 0,
                    entry_reason TEXT,
                    exit_reason TEXT,
                    stop_loss REAL,
                    target_price REAL,
                    max_profit REAL,
                    max_drawdown REAL,
                    errors TEXT,
                    notes TEXT,
                    tags TEXT,
                    created_at TEXT
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_summary (
                    date TEXT PRIMARY KEY,
                    total_pnl REAL,
                    total_trades INTEGER,
                    winning_trades INTEGER,
                    losing_trades INTEGER,
                    win_rate REAL,
                    avg_profit REAL,
                    avg_loss REAL,
                    profit_loss_ratio REAL,
                    max_single_win REAL,
                    max_single_loss REAL,
                    max_consecutive_wins INTEGER DEFAULT 0,
                    max_consecutive_losses INTEGER DEFAULT 0,
                    discipline_score INTEGER DEFAULT 100,
                    notes TEXT,
                    created_at TEXT
                )
            """)

            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol)")
            conn.commit()

    def add_trade(self, trade: TradeRecord) -> bool:
        """添加交易记录"""
        try:
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO trades VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                """, (
                    trade.trade_id, trade.date, trade.symbol, trade.direction,
                    trade.entry_time, trade.exit_time, trade.entry_price, trade.exit_price,
                    trade.lots, trade.gross_pnl, trade.net_pnl, trade.commission, trade.slippage,
                    trade.holding_minutes, trade.entry_reason, trade.exit_reason,
                    trade.stop_loss, trade.target_price, trade.max_profit, trade.max_drawdown,
                    json.dumps(trade.errors), trade.notes, json.dumps(trade.tags), trade.created_at
                ))
                conn.commit()
                return True
        except Exception as e:
            self.logger.error(f"添加交易记录失败: {e}")
            return False

    def get_trades(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[TradeRecord]:
        """获取交易记录"""
        conditions = []
        params = []

        if start_date:
            conditions.append("date >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("date <= ?")
            params.append(end_date)
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol.upper())

        sql = "SELECT * FROM trades"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY date DESC, exit_time DESC"

        if limit:
            sql += f" LIMIT {limit}"

        with self._get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_trade(row) for row in rows]

    def _row_to_trade(self, row: sqlite3.Row) -> TradeRecord:
        """将数据库行转换为TradeRecord"""
        return TradeRecord(
            trade_id=row["trade_id"],
            date=row["date"],
            symbol=row["symbol"],
            direction=row["direction"],
            entry_time=row["entry_time"] or "",
            exit_time=row["exit_time"] or "",
            entry_price=row["entry_price"] or 0,
            exit_price=row["exit_price"] or 0,
            lots=row["lots"] or 0,
            gross_pnl=row["gross_pnl"] or 0,
            net_pnl=row["net_pnl"] or 0,
            commission=row["commission"] or 0,
            slippage=row["slippage"] or 0,
            holding_minutes=row["holding_minutes"] or 0,
            entry_reason=row["entry_reason"] or "",
            exit_reason=row["exit_reason"] or "",
            stop_loss=row["stop_loss"] or 0,
            target_price=row["target_price"] or 0,
            max_profit=row["max_profit"] or 0,
            max_drawdown=row["max_drawdown"] or 0,
            errors=json.loads(row["errors"]) if row["errors"] else [],
            notes=row["notes"] or "",
            tags=json.loads(row["tags"]) if row["tags"] else [],
            created_at=row["created_at"] or ""
        )

    # ==================== 统计分析 ====================

    def get_statistics(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """获取统计信息"""
        if not start_date:
            start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")

        trades = self.get_trades(start_date=start_date, end_date=end_date)

        if not trades:
            return {"error": "该时间段无交易记录"}

        total_pnl = sum(t.net_pnl for t in trades)
        winning_trades = [t for t in trades if t.net_pnl > 0]
        losing_trades = [t for t in trades if t.net_pnl <= 0]

        # 按品种统计
        symbol_stats = {}
        for trade in trades:
            s = trade.symbol
            if s not in symbol_stats:
                symbol_stats[s] = {"trades": 0, "pnl": 0, "wins": 0}
            symbol_stats[s]["trades"] += 1
            symbol_stats[s]["pnl"] += trade.net_pnl
            if trade.net_pnl > 0:
                symbol_stats[s]["wins"] += 1

        return {
            "period": f"{start_date} ~ {end_date}",
            "total_trades": len(trades),
            "total_pnl": round(total_pnl, 2),
            "win_rate": round(len(winning_trades) / len(trades) * 100, 1),
            "profit_loss_ratio": round(
                abs(sum(t.net_pnl for t in winning_trades) / len(winning_trades)) /
                abs(sum(t.net_pnl for t in losing_trades) / len(losing_trades))
                if losing_trades and winning_trades else 0, 2
            ),
            "avg_holding_minutes": round(sum(t.holding_minutes for t in trades) / len(trades), 1),
            "symbol_stats": {
                s: {
                    "trades": v["trades"],
                    "pnl": round(v["pnl"], 2),
                    "win_rate": round(v["wins"] / v["trades"] * 100, 1)
                }
                for s, v in sorted(symbol_stats.items(), key=lambda x: -x[1]["trades"])
            }
        }

    def generate_review_report(self, date: str) -> str:
        """生成复盘报告"""
        trades = self.get_trades(start_date=date, end_date=date)

        if not trades:
            return f"## 📋 {date} 交易复盘\n\n当日无交易记录"

        # 计算统计
        total_pnl = sum(t.net_pnl for t in trades)
        winning = [t for t in trades if t.net_pnl > 0]
        losing = [t for t in trades if t.net_pnl <= 0]

        win_rate = len(winning) / len(trades) * 100 if trades else 0
        avg_profit = sum(t.net_pnl for t in winning) / len(winning) if winning else 0
        avg_loss = sum(t.net_pnl for t in losing) / len(losing) if losing else 0
        profit_loss_ratio = abs(avg_profit / avg_loss) if avg_loss != 0 else 0

        pnl_emoji = "📈" if total_pnl > 0 else "📉" if total_pnl < 0 else "➡️"

        lines = [
            f"## 📋 {date} 交易复盘报告",
            "",
            f"**当日盈亏**: {pnl_emoji} {total_pnl:+.2f}",
            f"**交易笔数**: {len(trades)} 笔",
            f"**胜率**: {win_rate:.1f}% ({len(winning)}胜/{len(losing)}负)",
            f"**盈亏比**: {profit_loss_ratio:.2f}:1",
            "",
            "### 逐笔分析",
        ]

        for i, trade in enumerate(trades, 1):
            emoji = "✅" if trade.net_pnl > 0 else "❌"
            lines.append(f"{i}. {emoji} {trade.symbol} {trade.direction}")
            lines.append(f"   盈亏: {trade.net_pnl:+.2f} | 持仓: {trade.holding_minutes}分钟")
            if trade.errors:
                lines.append(f"   问题: {', '.join(trade.errors)}")

        lines.extend([
            "",
            f"---\n生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        ])

        return "\n".join(lines)

    # ==================== 飞书命令 ====================

    async def _cmd_record(self, args: str, user_id: str, chat_id: str) -> str:
        """记录命令 - 提供模板"""
        return """## 📋 交易记录模板

请复制以下格式填写交易信息：

```
日期: 2024-01-15
品种: AU
方向: 多
入场: 750
出场: 765
手数: 2
盈亏: +30000
持仓时间: 120分钟
入场原因: MACD金叉
出场原因: 达到目标位
止损: 735
问题: 无
备注: 按计划执行
```

填写后发送给我，我将为您记录。
"""

    async def _cmd_add(self, args: str, user_id: str, chat_id: str) -> str:
        """添加交易记录"""
        # 解析文本格式
        lines = args.strip().split('\n')
        data = {}

        for line in lines:
            if ':' in line:
                key, value = line.split(':', 1)
                data[key.strip()] = value.strip()

        if not data.get('品种') or not data.get('盈亏'):
            return "❌ 格式错误，请使用「记录」查看模板"

        # 生成交易ID
        trade_id = f"T{datetime.now().strftime('%Y%m%d%H%M%S')}"

        try:
            trade = TradeRecord(
                trade_id=trade_id,
                date=data.get('日期', datetime.now().strftime('%Y-%m-%d')),
                symbol=data.get('品种', 'AU').upper(),
                direction='long' if data.get('方向') in ['多', 'long'] else 'short',
                entry_time=data.get('入场时间', '09:30'),
                exit_time=data.get('出场时间', '15:00'),
                entry_price=float(data.get('入场', 0)),
                exit_price=float(data.get('出场', 0)),
                lots=int(data.get('手数', 1)),
                gross_pnl=float(data.get('盈亏', 0)),
                net_pnl=float(data.get('盈亏', 0)),
                commission=float(data.get('手续费', 0)),
                holding_minutes=int(data.get('持仓时间', 0)),
                entry_reason=data.get('入场原因', ''),
                exit_reason=data.get('出场原因', ''),
                stop_loss=float(data.get('止损', 0)) if data.get('止损') else 0,
                errors=[data.get('问题', '')] if data.get('问题') and data.get('问题') != '无' else [],
                notes=data.get('备注', '')
            )

            if self.add_trade(trade):
                return f"✅ 交易记录已保存\nID: {trade_id}\n品种: {trade.symbol}\n盈亏: {trade.net_pnl:+.2f}"
            else:
                return "❌ 保存失败"
        except Exception as e:
            return f"❌ 解析失败: {str(e)}"

    async def _cmd_review(self, args: str, user_id: str, chat_id: str) -> str:
        """复盘命令"""
        if args:
            date = args.strip()
        else:
            date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        return self.generate_review_report(date)

    async def _cmd_stats(self, args: str, user_id: str, chat_id: str) -> str:
        """统计命令"""
        days = 30
        if args:
            try:
                days = int(args.strip())
            except:
                pass

        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        stats = self.get_statistics(start, end)

        if "error" in stats:
            return f"## 📊 交易统计\n\n{stats['error']}"

        lines = [
            f"## 📊 交易统计 ({stats['period']})",
            "",
            f"**总体表现**:",
            f"  总盈亏: {stats['total_pnl']:+.2f}",
            f"  交易笔数: {stats['total_trades']} 笔",
            f"  胜率: {stats['win_rate']}%",
            f"  盈亏比: {stats['profit_loss_ratio']}:1",
            f"  平均持仓: {stats['avg_holding_minutes']} 分钟",
            "",
            "**品种分布**:",
        ]

        for symbol, s in stats['symbol_stats'].items():
            emoji = "📈" if s['pnl'] > 0 else "📉"
            lines.append(f"  {emoji} {symbol}: {s['trades']}笔 盈亏{s['pnl']:+.2f} 胜率{s['win_rate']}%")

        # 评价
        if stats['win_rate'] >= 60 and stats['profit_loss_ratio'] >= 1.5:
            evaluation = "✅ 交易表现优秀"
        elif stats['win_rate'] >= 50 and stats['profit_loss_ratio'] >= 1:
            evaluation = "➡️ 交易表现良好"
        else:
            evaluation = "⚠️ 需优化交易系统"

        lines.extend(["", f"**评价**: {evaluation}"])

        return "\n".join(lines)

    async def _cmd_list(self, args: str, user_id: str, chat_id: str) -> str:
        """列表命令"""
        limit = 5
        if args:
            try:
                limit = int(args.strip())
            except:
                pass

        trades = self.get_trades(limit=limit)

        if not trades:
            return "暂无交易记录"

        lines = [f"## 📋 最近 {len(trades)} 笔交易", ""]

        for i, t in enumerate(trades, 1):
            emoji = "✅" if t.net_pnl > 0 else "❌"
            lines.append(f"{i}. {emoji} {t.date} {t.symbol}")
            lines.append(f"   {t.direction} | 盈亏: {t.net_pnl:+.2f} | 持仓: {t.holding_minutes}min")
            if t.errors:
                lines.append(f"   问题: {', '.join(t.errors)}")
            lines.append("")

        return "\n".join(lines)

    async def _handle_default(self, text: str, user_id: str, chat_id: str) -> str:
        """默认处理 - 尝试解析交易记录"""
        # 如果包含冒号，可能是交易记录格式
        if ':' in text and ('品种' in text or '盈亏' in text):
            return await self._cmd_add(text, user_id, chat_id)
        return await super()._handle_default(text, user_id, chat_id)

    # ==================== Agent生命周期 ====================

    async def initialize(self):
        """初始化"""
        await super().initialize()
        self.logger.info("交易日志技能初始化完成")


# 兼容旧代码
TradeJournalAgent = JournalSkill
