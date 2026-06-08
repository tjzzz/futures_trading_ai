#!/usr/bin/env python3
"""
指标加载器 — indicator_source.json 的解析器 + 查询接口

从 config/indicator_source.json 读取所有指标定义、采集器配置、数据源信息。
所有模块通过此模块获取统一配置，不再各自硬编码指标列表和文件路径。

用法:
    from config import loader

    # 单个指标
    g = loader.get("gold")
    g["name"]               # "黄金"
    g["display"]["color"]   # "#f59e0b"

    # 索引
    loader.yahoo_to_indicator       # {"GC=F": "gold_futures", ...}
    loader.snapshot_to_indicator     # {"gold_price": "gold", ...}
    loader.by_quadrant("red")        # → [gold, silver, ratio, ...]
    loader.by_category("macro")      # → [dxy, treasury_10y, ...]

    # 文件路径
    loader.minutely_path("gold")    # Path("data/.../gold_silver_minutely.csv")

    # 采集器
    loader.collectors["collectors.macro"]["indicators"]
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger("indicator_loader")

# ── 文件路径 ──
_SOURCE_FILE = Path(__file__).resolve().parent / "indicator_source.json"
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_DAILY_DIR = _DATA_DIR / "history" / "daily"
_MINUTELY_DIR = _DATA_DIR / "history" / "minutely"


class IndicatorLoader:
    """indicator_source.json 加载器 —— 所有指标配置的单一入口"""

    def __init__(self, path: Optional[Path] = None):
        self._path = path or _SOURCE_FILE

        # 核心数据（解析后填充）
        self.indicators: Dict[str, dict] = {}      # indicator_id → 指标 dict
        self.collectors: Dict[str, dict] = {}      # collector_id → 采集器 dict
        self.sources: List[dict] = []               # 数据源列表

        # 索引
        self.yahoo_to_indicator: Dict[str, str] = {}
        self.snapshot_to_indicator: Dict[str, str] = {}
        self._by_category: Dict[str, List[str]] = {}
        self._by_quadrant: Dict[str, List[str]] = {}

        self.load()

    # ── 加载 ──

    def load(self) -> "IndicatorLoader":
        if not self._path.exists():
            logger.warning(f"指标定义文件不存在: {self._path}")
            return self

        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"指标定义文件加载失败: {e}")
            return self

        self.indicators = raw.get("indicators", {})
        self.collectors = raw.get("collectors", {})
        self.sources = raw.get("sources", [])
        self._build_indexes()

        logger.info(f"加载完成: {len(self.indicators)} 指标, "
                     f"{len(self.collectors)} 采集器, {len(self.sources)} 数据源")
        return self

    def _build_indexes(self):
        for idx, ind in self.indicators.items():
            # Yahoo 符号 → indicator_id
            sym = ind.get("yahoo_symbol")
            if sym:
                self.yahoo_to_indicator[sym] = idx

            # 快照键 → indicator_id
            sk = ind.get("files", {}).get("snapshot_key")
            if sk:
                self.snapshot_to_indicator[sk] = idx

            # 分类索引
            for key, store in [("category", self._by_category),
                               ("quadrant", self._by_quadrant)]:
                vals = ind.get(key, [])
                if isinstance(vals, str):
                    vals = [vals]
                for v in vals:
                    if v not in store:
                        store[v] = []
                    store[v].append(idx)

    # ── 查询 ──

    def get(self, indicator_id: str) -> Optional[dict]:
        """获取单个指标定义（dict），不存在返回 None"""
        return self.indicators.get(indicator_id)

    def by_quadrant(self, quadrant: str) -> List[dict]:
        """按四象限筛选（green / blue / orange / red）"""
        ids = self._by_quadrant.get(quadrant, [])
        return [self.indicators[i] for i in ids if i in self.indicators]

    def by_category(self, category: str) -> List[dict]:
        """按大类筛选（macro / precious_metal / sentiment / derived）"""
        ids = self._by_category.get(category, [])
        return [self.indicators[i] for i in ids if i in self.indicators]

    def by_collector(self, collector_id: str) -> List[dict]:
        """按采集器筛选"""
        col = self.collectors.get(collector_id)
        if not col:
            return []
        ids = col.get("indicators", [])
        return [self.indicators[i] for i in ids if i in self.indicators]

    @property
    def categories(self) -> List[str]:
        return list(self._by_category.keys())

    @property
    def quadrants(self) -> List[str]:
        return list(self._by_quadrant.keys())

    def indicator_ids(self) -> List[str]:
        return list(self.indicators.keys())

    # ── 路径辅助 ──

    def minutely_path(self, indicator_id: str) -> Optional[Path]:
        """指标对应的分钟级 CSV 完整路径"""
        f = self.get(indicator_id)
        if not f:
            return None
        file = f.get("files", {}).get("minutely", {}).get("file")
        return _MINUTELY_DIR / file if file else None

    def daily_path(self, indicator_id: str) -> Optional[Path]:
        """指标对应的日频 CSV 完整路径"""
        f = self.get(indicator_id)
        if not f:
            return None
        file = f.get("files", {}).get("daily", {}).get("file")
        return _DAILY_DIR / file if file else None

    # ── 导出 ──

    def to_api_sources(self) -> List[dict]:
        """供 /api/sources 端点返回"""
        return [
            {"id": s["id"], "name": s["name"], "type": s.get("type"),
             "status": s.get("status"), "url": s.get("url"), "notes": s.get("notes")}
            for s in self.sources
        ]

    def to_api_indicators(self) -> dict:
        """供 API 返回的指标元数据（精简版）"""
        out = {}
        for idx, ind in self.indicators.items():
            d = ind.get("display", {})
            out[idx] = {
                "id": idx,
                "name": ind.get("name"),
                "name_en": ind.get("name_en"),
                "category": ind.get("category"),
                "quadrant": ind.get("quadrant"),
                "display": {
                    "icon": d.get("icon"),
                    "color": d.get("color"),
                    "group": d.get("group"),
                    "unit": d.get("unit"),
                    "precision": d.get("precision"),
                },
                "has_minutely": "minutely" in ind.get("files", {}),
                "has_daily": "daily" in ind.get("files", {}),
            }
        return {"indicators": out}


# ====================================================================
#  全局单例
# ====================================================================

_loader: Optional[IndicatorLoader] = None


def get_loader() -> IndicatorLoader:
    global _loader
    if _loader is None:
        _loader = IndicatorLoader()
    return _loader


# 推荐用法: from config import loader
loader = get_loader()
