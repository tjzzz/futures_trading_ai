"""
共享数据客户端 - 统一的数据获取接口
支持多种数据源：TuShare、AKShare、CTP
"""
import os
import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from abc import ABC, abstractmethod

import pandas as pd


class DataSource(ABC):
    """数据源基类"""
    
    @abstractmethod
    def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取实时行情"""
        pass
    
    @abstractmethod
    def get_bars(self, symbol: str, start: str, end: str, freq: str = "1d") -> Optional[List[Dict]]:
        """获取历史K线"""
        pass
    
    @abstractmethod
    def get_fundamental(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取基本面数据"""
        pass


class MockDataSource(DataSource):
    """模拟数据源（用于测试）"""
    
    def __init__(self):
        self.mock_data = {
            "AU": {
                "price": 750, "open": 745, "high": 755, "low": 742,
                "volume": 100000, "atr": 15, "change_pct": 0.67
            },
            "SC": {
                "price": 520, "open": 515, "high": 525, "low": 510,
                "volume": 50000, "atr": 12, "change_pct": 0.97
            },
            "CU": {
                "price": 68000, "open": 67500, "high": 68500, "low": 67000,
                "volume": 30000, "atr": 800, "change_pct": 0.74
            },
            "RB": {
                "price": 3800, "open": 3780, "high": 3850, "low": 3750,
                "volume": 200000, "atr": 50, "change_pct": 0.53
            },
            "M": {
                "price": 3200, "open": 3180, "high": 3250, "low": 3150,
                "volume": 150000, "atr": 40, "change_pct": 0.63
            }
        }
    
    def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        return self.mock_data.get(symbol.upper())
    
    def get_bars(self, symbol: str, start: str, end: str, freq: str = "1d") -> Optional[List[Dict]]:
        # 返回模拟K线数据
        base_price = self.mock_data.get(symbol.upper(), {}).get("price", 100)
        bars = []
        
        start_date = datetime.strptime(start, "%Y-%m-%d")
        end_date = datetime.strptime(end, "%Y-%m-%d")
        
        import random
        random.seed(hash(symbol))
        
        current_date = start_date
        price = base_price * 0.9
        
        while current_date <= end_date:
            change = random.uniform(-0.02, 0.02)
            price = price * (1 + change)
            
            bars.append({
                "date": current_date.strftime("%Y-%m-%d"),
                "open": price * (1 + random.uniform(-0.005, 0.005)),
                "high": price * (1 + random.uniform(0, 0.01)),
                "low": price * (1 - random.uniform(0, 0.01)),
                "close": price,
                "volume": random.randint(10000, 100000)
            })
            
            current_date += timedelta(days=1)
        
        return bars
    
    def get_fundamental(self, symbol: str) -> Optional[Dict[str, Any]]:
        return {
            "symbol": symbol,
            "score": 25,  # 偏多
            "drivers": [
                {"driver": "美元指数", "impact": "利多", "detail": "美元走弱"},
                {"driver": "实际利率", "impact": "利多", "detail": "利率下行"}
            ]
        }


class TuShareDataSource(DataSource):
    """TuShare数据源"""
    
    def __init__(self, token: str = None):
        self.token = token or os.getenv("TUSHARE_TOKEN")
        self.logger = logging.getLogger("TuShareDataSource")
        
        if self.token:
            try:
                import tushare as ts
                ts.set_token(self.token)
                self.pro = ts.pro_api()
                self.logger.info("TuShare初始化成功")
            except ImportError:
                self.logger.warning("TuShare未安装，将使用模拟数据")
                self.pro = None
        else:
            self.pro = None
            self.logger.warning("未配置TUSHARE_TOKEN，将使用模拟数据")
    
    def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        if not self.pro:
            return MockDataSource().get_quote(symbol)
        
        try:
            # 获取实时行情
            # 注意：TuShare的期货接口需要特定权限
            df = self.pro.fut_daily(ts_code=f"{symbol}.SHF", limit=1)
            if df is not None and len(df) > 0:
                row = df.iloc[0]
                return {
                    "price": row["close"],
                    "open": row["open"],
                    "high": row["high"],
                    "low": row["low"],
                    "volume": row["vol"],
                    "change_pct": (row["close"] - row["pre_close"]) / row["pre_close"] * 100
                }
        except Exception as e:
            self.logger.error(f"获取行情失败: {e}")
        
        return None
    
    def get_bars(self, symbol: str, start: str, end: str, freq: str = "1d") -> Optional[List[Dict]]:
        if not self.pro:
            return MockDataSource().get_bars(symbol, start, end, freq)
        
        try:
            df = self.pro.fut_daily(
                ts_code=f"{symbol}.SHF",
                start_date=start.replace("-", ""),
                end_date=end.replace("-", "")
            )
            
            if df is not None and len(df) > 0:
                return [
                    {
                        "date": row["trade_date"],
                        "open": row["open"],
                        "high": row["high"],
                        "low": row["low"],
                        "close": row["close"],
                        "volume": row["vol"]
                    }
                    for _, row in df.iterrows()
                ]
        except Exception as e:
            self.logger.error(f"获取K线失败: {e}")
        
        return None
    
    def get_fundamental(self, symbol: str) -> Optional[Dict[str, Any]]:
        # TuShare基本面数据需要特定接口
        return MockDataSource().get_fundamental(symbol)


class AKShareDataSource(DataSource):
    """AKShare数据源 - 免费期货数据接口"""

    # 期货主力合约代码映射
    FUTURES_MAIN_MAP = {
        # 上期所
        "AU": "AU0",    # 黄金
        "AG": "AG0",    # 白银
        "CU": "CU0",    # 铜
        "AL": "AL0",    # 铝
        "ZN": "ZN0",    # 锌
        "PB": "PB0",    # 铅
        "NI": "NI0",    # 镍
        "SN": "SN0",    # 锡
        "RB": "RB0",    # 螺纹钢
        "HC": "HC0",    # 热卷
        "SS": "SS0",    # 不锈钢
        "RU": "RU0",    # 橡胶
        "BU": "BU0",    # 沥青
        "SP": "SP0",    # 纸浆
        "FU": "FU0",    # 燃油
        # 能源中心
        "SC": "SC0",    # 原油
        "LU": "LU0",    # 低硫燃油
        # 大商所
        "M": "M0",      # 豆粕
        "Y": "Y0",      # 豆油
        "P": "P0",      # 棕榈油
        "C": "C0",      # 玉米
        "CS": "CS0",    # 淀粉
        "A": "A0",      # 豆一
        "B": "B0",      # 豆二
        "I": "I0",      # 铁矿石
        "J": "J0",      # 焦炭
        "JM": "JM0",    # 焦煤
        "L": "L0",      # 塑料
        "PP": "PP0",    # 聚丙烯
        "EG": "EG0",    # 乙二醇
        "EB": "EB0",    # 苯乙烯
        "PG": "PG0",    # 液化气
        "V": "V0",      # PVC
        # 郑商所
        "SR": "SR0",    # 白糖
        "CF": "CF0",    # 棉花
        "TA": "TA0",    # PTA
        "MA": "MA0",    # 甲醇
        "RM": "RM0",    # 菜粕
        "OI": "OI0",    # 菜油
        "ZC": "ZC0",    # 动力煤
        "FG": "FG0",    # 玻璃
        "SA": "SA0",    # 纯碱
        "UR": "UR0",    # 尿素
        "SF": "SF0",    # 硅铁
        "SM": "SM0",    # 锰硅
        "AP": "AP0",    # 苹果
        "CJ": "CJ0",    # 红枣
        # 广期所
        "LC": "LC0",    # 碳酸锂
        "SI": "SI0",    # 工业硅
    }

    def __init__(self):
        self.logger = logging.getLogger("AKShareDataSource")

        try:
            import akshare as ak
            self.ak = ak
            self.logger.info("AKShare初始化成功")
        except ImportError:
            self.ak = None
            self.logger.warning("AKShare未安装，将使用模拟数据")
            self.logger.warning("请安装: pip install akshare")

    def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取实时行情（延迟15分钟）"""
        if not self.ak:
            return MockDataSource().get_quote(symbol)

        try:
            # 获取主力合约代码
            main_symbol = self.FUTURES_MAIN_MAP.get(symbol.upper())
            if not main_symbol:
                self.logger.warning(f"不支持的品种: {symbol}")
                return MockDataSource().get_quote(symbol)

            # 获取行情数据
            df = self.ak.futures_main_sina(symbol=main_symbol)

            if df is None or len(df) == 0:
                return MockDataSource().get_quote(symbol)

            # 获取最新一行数据
            latest = df.iloc[-1]

            # 解析数据
            return {
                "symbol": symbol.upper(),
                "main_contract": main_symbol,
                "price": float(latest["收盘价"]),
                "open": float(latest["开盘价"]),
                "high": float(latest["最高价"]),
                "low": float(latest["最低价"]),
                "volume": int(latest["成交量"]),
                "change_pct": float(latest.get("涨跌幅", 0)),
                "settlement": float(latest.get("结算价", latest["收盘价"])),
                "open_interest": int(latest.get("持仓量", 0)),
                "timestamp": datetime.now().isoformat(),
                "source": "akshare"
            }

        except Exception as e:
            self.logger.error(f"获取行情失败: {e}")
            return MockDataSource().get_quote(symbol)

    def get_bars(self, symbol: str, start: str, end: str, freq: str = "1d") -> Optional[List[Dict]]:
        """获取历史K线数据"""
        if not self.ak:
            return MockDataSource().get_bars(symbol, start, end, freq)

        try:
            main_symbol = self.FUTURES_MAIN_MAP.get(symbol.upper())
            if not main_symbol:
                return MockDataSource().get_bars(symbol, start, end, freq)

            # 获取历史数据
            df = self.ak.futures_main_sina(symbol=main_symbol)

            if df is None or len(df) == 0:
                return MockDataSource().get_bars(symbol, start, end, freq)

            # 转换列名
            df = df.rename(columns={
                "日期": "date",
                "开盘价": "open",
                "最高价": "high",
                "最低价": "low",
                "收盘价": "close",
                "成交量": "volume",
                "持仓量": "open_interest",
                "结算价": "settlement"
            })

            # 确保日期列格式正确
            df["date"] = pd.to_datetime(df["date"])
            start_date = pd.to_datetime(start)
            end_date = pd.to_datetime(end)

            mask = (df["date"] >= start_date) & (df["date"] <= end_date)
            filtered = df[mask]

            # 转换为列表
            bars = []
            for _, row in filtered.iterrows():
                bars.append({
                    "date": row["date"].strftime("%Y-%m-%d"),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": int(row["volume"]),
                    "open_interest": int(row.get("open_interest", 0)),
                    "settlement": float(row.get("settlement", row["close"]))
                })

            return bars

        except Exception as e:
            self.logger.error(f"获取K线失败: {e}")
            return MockDataSource().get_bars(symbol, start, end, freq)

    def get_fundamental(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取基本面数据（AKShare暂不支持，返回模拟）"""
        return MockDataSource().get_fundamental(symbol)

    def get_all_futures_list(self) -> List[Dict]:
        """获取所有期货品种列表"""
        if not self.ak:
            return []

        try:
            df = self.ak.futures_display_main_sina()
            return [
                {
                    "symbol": row["symbol"],
                    "name": row["name"],
                    "exchange": row.get("exchange", "")
                }
                for _, row in df.iterrows()
            ]
        except Exception as e:
            self.logger.error(f"获取品种列表失败: {e}")
            return []


class DataClient:
    """统一数据客户端"""
    
    def __init__(self, source: str = "mock", config: Dict = None):
        self.config = config or {}
        self.logger = logging.getLogger("DataClient")
        
        # 选择数据源
        if source == "tushare":
            self.source = TuShareDataSource(self.config.get("tushare_token"))
        elif source == "akshare":
            self.source = AKShareDataSource()
        else:
            self.source = MockDataSource()
        
        self.logger.info(f"数据源: {source}")
    
    def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取实时行情"""
        return self.source.get_quote(symbol)
    
    def get_bars(self, symbol: str, start: str, end: str, freq: str = "1d") -> Optional[List[Dict]]:
        """获取历史K线"""
        return self.source.get_bars(symbol, start, end, freq)
    
    def get_fundamental(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取基本面数据"""
        return self.source.get_fundamental(symbol)
    
    def get_atr(self, symbol: str, period: int = 14) -> Optional[float]:
        """计算ATR"""
        bars = self.get_bars(
            symbol,
            (datetime.now() - timedelta(days=period * 2)).strftime("%Y-%m-%d"),
            datetime.now().strftime("%Y-%m-%d")
        )
        
        if not bars or len(bars) < period:
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


# 使用示例
if __name__ == "__main__":
    # 使用模拟数据源
    client = DataClient(source="mock")
    
    # 获取行情
    quote = client.get_quote("AU")
    print("黄金行情:", quote)
    
    # 获取ATR
    atr = client.get_atr("AU")
    print("黄金ATR:", atr)
