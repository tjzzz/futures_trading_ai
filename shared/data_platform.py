#!/usr/bin/env python3
"""
数据中台 - 统一的数据采集、存储、管理模块
为各 Agent 提供标准化的数据服务
"""
import os
import json
import sqlite3
import logging
from typing import Dict, Any, Optional, List, Union
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from pathlib import Path
import threading

from data_client import DataClient, AKShareDataSource


@dataclass
class BarData:
    """K线数据"""
    symbol: str
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    open_interest: int = 0
    settlement: float = 0.0
    created_at: str = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class TickData:
    """Tick数据"""
    symbol: str
    timestamp: str
    price: float
    volume: int
    bid1: float = 0.0
    ask1: float = 0.0
    bid1_vol: int = 0
    ask1_vol: int = 0
    created_at: str = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()


@dataclass
class FundamentalData:
    """基本面数据"""
    symbol: str
    date: str
    indicator: str
    value: float
    source: str
    created_at: str = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()


class DataStorage:
    """数据存储层 - SQLite实现"""

    def __init__(self, db_path: str = "data/futures_data.db"):
        self.db_path = db_path
        self.logger = logging.getLogger("DataStorage")

        # 确保目录存在
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        # 初始化数据库
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """初始化数据库表"""
        with self._get_connection() as conn:
            # K线数据表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bar_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    date TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume INTEGER NOT NULL,
                    open_interest INTEGER DEFAULT 0,
                    settlement REAL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    UNIQUE(symbol, date)
                )
            """)

            # 创建索引
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_bar_symbol_date
                ON bar_data(symbol, date)
            """)

            # Tick数据表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tick_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    price REAL NOT NULL,
                    volume INTEGER NOT NULL,
                    bid1 REAL DEFAULT 0,
                    ask1 REAL DEFAULT 0,
                    bid1_vol INTEGER DEFAULT 0,
                    ask1_vol INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)

            # 基本面数据表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS fundamental_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    date TEXT NOT NULL,
                    indicator TEXT NOT NULL,
                    value REAL NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(symbol, date, indicator)
                )
            """)

            # 数据更新日志
            conn.execute("""
                CREATE TABLE IF NOT EXISTS update_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    data_type TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    record_count INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            conn.commit()
            self.logger.info("数据库初始化完成")

    def save_bar_data(self, bars: List[BarData]) -> int:
        """保存K线数据"""
        if not bars:
            return 0

        count = 0
        with self._get_connection() as conn:
            for bar in bars:
                try:
                    conn.execute("""
                        INSERT OR REPLACE INTO bar_data
                        (symbol, date, open, high, low, close, volume, open_interest, settlement, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        bar.symbol, bar.date, bar.open, bar.high, bar.low,
                        bar.close, bar.volume, bar.open_interest, bar.settlement, bar.created_at
                    ))
                    count += 1
                except Exception as e:
                    self.logger.error(f"保存K线数据失败 {bar.symbol} {bar.date}: {e}")

            conn.commit()

        self.logger.info(f"保存 {count} 条K线数据")
        return count

    def get_bar_data(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        limit: Optional[int] = None
    ) -> List[BarData]:
        """获取K线数据"""
        with self._get_connection() as conn:
            sql = """
                SELECT * FROM bar_data
                WHERE symbol = ? AND date >= ? AND date <= ?
                ORDER BY date ASC
            """
            params = [symbol.upper(), start_date, end_date]

            if limit:
                sql += " LIMIT ?"
                params.append(limit)

            rows = conn.execute(sql, params).fetchall()

            return [
                BarData(
                    symbol=row["symbol"],
                    date=row["date"],
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    volume=row["volume"],
                    open_interest=row["open_interest"],
                    settlement=row["settlement"],
                    created_at=row["created_at"]
                )
                for row in rows
            ]

    def get_latest_bar(self, symbol: str) -> Optional[BarData]:
        """获取最新K线"""
        with self._get_connection() as conn:
            row = conn.execute("""
                SELECT * FROM bar_data
                WHERE symbol = ?
                ORDER BY date DESC
                LIMIT 1
            """, (symbol.upper(),)).fetchone()

            if row:
                return BarData(
                    symbol=row["symbol"],
                    date=row["date"],
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    volume=row["volume"],
                    open_interest=row["open_interest"],
                    settlement=row["settlement"],
                    created_at=row["created_at"]
                )
            return None

    def get_data_range(self, symbol: str) -> Optional[Dict]:
        """获取数据时间范围"""
        with self._get_connection() as conn:
            row = conn.execute("""
                SELECT MIN(date) as start_date, MAX(date) as end_date, COUNT(*) as count
                FROM bar_data
                WHERE symbol = ?
            """, (symbol.upper(),)).fetchone()

            if row and row["start_date"]:
                return {
                    "symbol": symbol.upper(),
                    "start_date": row["start_date"],
                    "end_date": row["end_date"],
                    "count": row["count"]
                }
            return None

    def log_update(
        self,
        symbol: str,
        data_type: str,
        start_date: str,
        end_date: str,
        record_count: int,
        source: str
    ):
        """记录数据更新日志"""
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO update_log
                (symbol, data_type, start_date, end_date, record_count, source, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (symbol.upper(), data_type, start_date, end_date, record_count, source, datetime.now().isoformat()))
            conn.commit()

    def get_all_symbols(self) -> List[str]:
        """获取所有已存储的品种"""
        with self._get_connection() as conn:
            rows = conn.execute("SELECT DISTINCT symbol FROM bar_data").fetchall()
            return [row["symbol"] for row in rows]


class DataCollector:
    """数据采集器"""

    def __init__(self, storage: DataStorage, source: str = "akshare"):
        self.storage = storage
        self.source = source
        self.client = DataClient(source=source)
        self.logger = logging.getLogger("DataCollector")
        self._lock = threading.Lock()

    def collect_history(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        force_update: bool = False
    ) -> int:
        """采集历史数据"""
        symbol = symbol.upper()

        # 检查已有数据范围
        existing_range = self.storage.get_data_range(symbol)

        if existing_range and not force_update:
            # 检查是否需要更新
            existing_end = datetime.strptime(existing_range["end_date"], "%Y-%m-%d")
            request_end = datetime.strptime(end_date, "%Y-%m-%d")

            if existing_end >= request_end:
                self.logger.info(f"{symbol} 数据已是最新，无需更新")
                return 0

            # 只获取缺失的数据
            start_date = (existing_end + timedelta(days=1)).strftime("%Y-%m-%d")

        self.logger.info(f"采集 {symbol} 历史数据: {start_date} ~ {end_date}")

        # 从数据源获取
        bars_data = self.client.get_bars(symbol, start_date, end_date)

        if not bars_data:
            self.logger.warning(f"未获取到 {symbol} 的数据")
            return 0

        # 转换为 BarData
        bars = [
            BarData(
                symbol=symbol,
                date=bar["date"],
                open=bar["open"],
                high=bar["high"],
                low=bar["low"],
                close=bar["close"],
                volume=bar["volume"],
                open_interest=bar.get("open_interest", 0),
                settlement=bar.get("settlement", bar["close"])
            )
            for bar in bars_data
        ]

        # 保存到数据库
        with self._lock:
            count = self.storage.save_bar_data(bars)

        # 记录日志
        if count > 0:
            self.storage.log_update(
                symbol=symbol,
                data_type="bar",
                start_date=bars[0].date,
                end_date=bars[-1].date,
                record_count=count,
                source=self.source
            )

        self.logger.info(f"{symbol} 成功保存 {count} 条数据")
        return count

    def collect_daily(self, symbols: Optional[List[str]] = None) -> Dict[str, int]:
        """每日数据更新"""
        if symbols is None:
            # 默认更新主要品种
            symbols = ["AU", "AG", "CU", "AL", "NI", "RB", "I", "J", "SC", "TA", "MA", "M", "Y", "C"]

        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        results = {}
        for symbol in symbols:
            try:
                count = self.collect_history(symbol, start, end)
                results[symbol] = count
            except Exception as e:
                self.logger.error(f"更新 {symbol} 失败: {e}")
                results[symbol] = -1

        return results

    def fill_missing_data(self, symbol: str) -> int:
        """填充缺失数据"""
        symbol = symbol.upper()
        data_range = self.storage.get_data_range(symbol)

        if not data_range:
            # 全新采集，获取2年历史
            end = datetime.now().strftime("%Y-%m-%d")
            start = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
            return self.collect_history(symbol, start, end, force_update=True)

        # 检查数据连续性，填充缺失
        # TODO: 实现数据连续性检查
        return 0


class DataService:
    """数据服务层 - 为Agent提供统一数据接口"""

    def __init__(self, db_path: str = "data/futures_data.db"):
        self.storage = DataStorage(db_path)
        self.collector = DataCollector(self.storage, source="akshare")
        self.logger = logging.getLogger("DataService")

    def get_price_data(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        auto_update: bool = True
    ) -> List[Dict]:
        """获取价格数据（自动更新缺失数据）"""
        symbol = symbol.upper()

        # 先尝试从数据库获取
        bars = self.storage.get_bar_data(symbol, start_date, end_date)

        # 如果数据不足且允许自动更新
        if auto_update and len(bars) < 10:
            self.logger.info(f"{symbol} 本地数据不足，尝试更新")
            self.collector.collect_history(symbol, start_date, end_date)
            bars = self.storage.get_bar_data(symbol, start_date, end_date)

        return [bar.to_dict() for bar in bars]

    def get_latest_price(self, symbol: str) -> Optional[Dict]:
        """获取最新价格"""
        # 先从数据库获取
        bar = self.storage.get_latest_bar(symbol.upper())

        if bar:
            return bar.to_dict()

        # 如果没有，从API获取
        quote = self.collector.client.get_quote(symbol)
        return quote

    def get_atr(self, symbol: str, period: int = 14) -> Optional[float]:
        """计算ATR"""
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=period * 2)).strftime("%Y-%m-%d")

        bars = self.get_price_data(symbol, start, end)

        if len(bars) < period + 1:
            return None

        # 计算TR
        trs = []
        for i in range(1, len(bars)):
            high = bars[i]["high"]
            low = bars[i]["low"]
            prev_close = bars[i-1]["close"]

            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            trs.append(tr)

        # 计算ATR
        if len(trs) >= period:
            return sum(trs[-period:]) / period

        return None

    def get_data_status(self) -> List[Dict]:
        """获取数据状态"""
        symbols = self.storage.get_all_symbols()
        status = []

        for symbol in symbols:
            range_info = self.storage.get_data_range(symbol)
            if range_info:
                latest = self.storage.get_latest_bar(symbol)
                status.append({
                    "symbol": symbol,
                    "data_start": range_info["start_date"],
                    "data_end": range_info["end_date"],
                    "record_count": range_info["count"],
                    "latest_price": latest.close if latest else None,
                    "latest_date": latest.date if latest else None
                })

        return status

    def update_all(self, symbols: Optional[List[str]] = None) -> Dict[str, int]:
        """更新所有数据"""
        return self.collector.collect_daily(symbols)


# 全局数据服务实例（单例模式）
_data_service: Optional[DataService] = None


def get_data_service(db_path: str = "data/futures_data.db") -> DataService:
    """获取数据服务实例"""
    global _data_service
    if _data_service is None:
        _data_service = DataService(db_path)
    return _data_service


if __name__ == "__main__":
    # 测试数据服务
    logging.basicConfig(level=logging.INFO)

    service = get_data_service()

    # 获取黄金价格数据
    print("\n获取黄金历史数据...")
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    data = service.get_price_data("AU", start, end)
    print(f"获取到 {len(data)} 条数据")
    if data:
        print(f"最新: {data[-1]['date']} 收盘={data[-1]['close']}")

    # 计算ATR
    atr = service.get_atr("AU", 14)
    print(f"\nAU 14日ATR: {atr:.2f}" if atr else "ATR计算失败")

    # 获取数据状态
    print("\n数据状态:")
    status = service.get_data_status()
    for s in status[:5]:
        print(f"  {s['symbol']}: {s['data_start']} ~ {s['data_end']} ({s['record_count']}条)")
