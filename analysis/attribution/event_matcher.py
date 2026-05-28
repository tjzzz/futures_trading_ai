"""
L2: 事件匹配模块

核心功能：异常波动日 ↔ S/A 事件匹配
时间窗口匹配算法（±1天）
"""

import json
import csv
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import statistics


logger = logging.getLogger(__name__)


class EventMatcher:
    """事件匹配器：匹配价格异常波动与新闻事件"""
    
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
    
    def load_events(self) -> List[Dict[str, Any]]:
        """
        加载新闻事件数据
        
        Returns:
            事件列表，每个事件包含 {date, title, level, quadrant, etc.}
        """
        events_path = self.data_dir / "events" / "latest_feed.json"
        if not events_path.exists():
            logger.warning(f"事件数据文件不存在: {events_path}")
            return []
        
        try:
            with open(events_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 处理不同格式的事件数据
            events = []
            if isinstance(data, list):
                events = data
            elif isinstance(data, dict):
                events = data.get("events", [])
            
            logger.info(f"加载事件数据: {len(events)} 个事件")
            return events
            
        except Exception as e:
            logger.error(f"加载事件数据失败: {e}")
            return []
    
    def detect_anomaly_days(self, price_series: List[Dict[str, Any]], 
                           window_size: int = 20, threshold_sigma: float = 1.5) -> List[Dict[str, Any]]:
        """
        检测价格异常波动日
        
        Args:
            price_series: 价格序列 [{date, value, timestamp}]
            window_size: 滚动窗口大小（用于计算移动标准差）
            threshold_sigma: 异常阈值（标准差倍数）
            
        Returns:
            异常日列表，每个包含 {date, price_change, price_change_pct, is_anomaly, etc.}
        """
        if len(price_series) < window_size:
            logger.warning(f"价格序列长度 {len(price_series)} 小于窗口大小 {window_size}，使用全部数据")
            window_size = len(price_series)
        
        anomaly_days = []
        
        # 计算每日收益率
        daily_returns = []
        for i in range(1, len(price_series)):
            prev_price = price_series[i-1]["value"]
            curr_price = price_series[i]["value"]
            if prev_price != 0:
                return_pct = (curr_price - prev_price) / prev_price * 100
                # 处理可能没有timestamp的情况
                date_str = price_series[i]["date"]
                try:
                    if " " in date_str:
                        timestamp = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                    else:
                        timestamp = datetime.strptime(date_str, "%Y-%m-%d")
                except:
                    timestamp = datetime.now()  # 默认值
                
                daily_returns.append({
                    "date": date_str,
                    "price_change": curr_price - prev_price,
                    "price_change_pct": return_pct,
                    "timestamp": timestamp
                })
        
        if not daily_returns:
            return anomaly_days
        
        # 计算滚动标准差
        returns_values = [r["price_change_pct"] for r in daily_returns]
        
        # 如果数据点不够，使用整体标准差
        if len(returns_values) < window_size:
            std_dev = statistics.stdev(returns_values) if len(returns_values) > 1 else 0
            mean_return = statistics.mean(returns_values) if returns_values else 0
        else:
            # 计算滚动标准差
            rolling_stds = []
            for i in range(len(returns_values) - window_size + 1):
                window = returns_values[i:i+window_size]
                std_dev = statistics.stdev(window) if len(window) > 1 else 0
                rolling_stds.append(std_dev)
            
            # 使用平均滚动标准差
            std_dev = statistics.mean(rolling_stds) if rolling_stds else 0
            mean_return = statistics.mean(returns_values)
        
        # 检测异常日
        threshold = threshold_sigma * std_dev
        
        for daily_return in daily_returns:
            return_pct = daily_return["price_change_pct"]
            anomaly_score = abs(return_pct - mean_return) / std_dev if std_dev > 0 else 0
            
            is_anomaly = abs(return_pct - mean_return) > threshold
            
            anomaly_day = {
                "date": daily_return["date"],
                "price_change": daily_return["price_change"],
                "price_change_pct": daily_return["price_change_pct"],
                "is_anomaly": is_anomaly,
                "anomaly_score": round(anomaly_score, 2),
                "threshold": round(threshold, 2),
                "mean_return": round(mean_return, 2),
                "std_dev": round(std_dev, 2)
            }
            
            if is_anomaly:
                anomaly_days.append(anomaly_day)
        
        logger.info(f"检测到 {len(anomaly_days)} 个异常波动日 (阈值: ±{threshold:.2f}%)")
        return anomaly_days
    
    def match_events_with_anomalies(self, anomaly_days: List[Dict[str, Any]], 
                                   events: List[Dict[str, Any]], 
                                   time_window_hours: int = 24) -> List[Dict[str, Any]]:
        """
        匹配异常波动日与新闻事件
        
        Args:
            anomaly_days: 异常日列表
            events: 事件列表
            time_window_hours: 时间窗口（小时），默认±24小时
            
        Returns:
            匹配的事件列表
        """
        matched_events = []
        
        for anomaly in anomaly_days:
            if not anomaly["is_anomaly"]:
                continue
            
            anomaly_date_str = anomaly["date"]
            try:
                # 解析异常日日期
                if " " in anomaly_date_str:  # 包含时间
                    anomaly_date = datetime.strptime(anomaly_date_str, "%Y-%m-%d %H:%M:%S")
                else:  # 仅日期
                    anomaly_date = datetime.strptime(anomaly_date_str, "%Y-%m-%d")
                
                # 计算时间窗口
                window_start = anomaly_date - timedelta(hours=time_window_hours)
                window_end = anomaly_date + timedelta(hours=time_window_hours)
                
                # 在时间窗口内查找事件
                for event in events:
                    event_date_str = event.get("date") or event.get("timestamp") or event.get("pubDate") or event.get("fetched_at")
                    if not event_date_str:
                        continue
                    
                    try:
                        # 尝试解析事件日期
                        event_date = None
                        for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"]:
                            try:
                                event_date = datetime.strptime(event_date_str[:19], fmt)
                                break
                            except ValueError:
                                continue
                        
                        if not event_date:
                            continue
                        
                        # 检查是否在时间窗口内
                        if window_start <= event_date <= window_end:
                            # 计算事件影响
                            price_before = anomaly.get("price_before", anomaly["price_change"] / 2)
                            price_after = anomaly.get("price_after", anomaly["price_change"] * 1.5)
                            
                            matched_event = {
                                "anomaly_date": anomaly_date_str,
                                "anomaly_price_change": anomaly["price_change"],
                                "anomaly_price_change_pct": anomaly["price_change_pct"],
                                "anomaly_score": anomaly["anomaly_score"],
                                "event_date": event_date.strftime("%Y-%m-%d %H:%M:%S"),
                                "event_title": event.get("title", "未知事件"),
                                "event_summary": event.get("summary", ""),
                                "event_level": event.get("level", "B"),  # S/A/B/C
                                "event_quadrant": event.get("quadrant", "未知"),
                                "time_diff_hours": round((event_date - anomaly_date).total_seconds() / 3600, 1),
                                "price_impact": {
                                    "before": round(price_before, 2),
                                    "after": round(price_after, 2),
                                    "change": round(anomaly["price_change"], 2)
                                },
                                "direction": "上涨" if anomaly["price_change"] > 0 else "下跌",
                                "match_confidence": self._calculate_match_confidence(
                                    anomaly["anomaly_score"],
                                    event.get("level", "B"),
                                    abs((event_date - anomaly_date).total_seconds() / 3600)
                                )
                            }
                            matched_events.append(matched_event)
                            logger.info(f"匹配事件: {anomaly_date_str} ← {event.get('title', '未知事件')}")
                            
                    except Exception as e:
                        logger.warning(f"解析事件日期失败: {event_date_str}, 错误: {e}")
                        continue
                        
            except Exception as e:
                logger.warning(f"解析异常日日期失败: {anomaly_date_str}, 错误: {e}")
                continue
        
        # 按匹配置信度排序
        matched_events.sort(key=lambda x: x["match_confidence"], reverse=True)
        
        logger.info(f"事件匹配完成: {len(matched_events)} 个匹配事件")
        return matched_events
    
    def _calculate_match_confidence(self, anomaly_score: float, event_level: str, 
                                   time_diff_hours: float) -> float:
        """
        计算匹配置信度
        
        Args:
            anomaly_score: 异常分数
            event_level: 事件等级 (S/A/B/C)
            time_diff_hours: 时间差（小时）
            
        Returns:
            匹配置信度 0-1
        """
        # 异常分数权重 (0-1)
        anomaly_weight = min(anomaly_score / 3.0, 1.0)  # 假设3σ为最大
        
        # 事件等级权重
        level_weights = {"S": 1.0, "A": 0.8, "B": 0.5, "C": 0.3}
        level_weight = level_weights.get(event_level.upper(), 0.3)
        
        # 时间差权重（时间差越小，权重越高）
        time_weight = max(0, 1.0 - (time_diff_hours / 48.0))  # 48小时内线性衰减
        
        # 综合置信度
        confidence = (anomaly_weight * 0.4 + level_weight * 0.4 + time_weight * 0.2)
        
        return round(confidence, 2)
    
    def analyze_event_impact(self, matched_events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        分析事件影响统计
        
        Args:
            matched_events: 匹配的事件列表
            
        Returns:
            事件影响统计
        """
        if not matched_events:
            return {
                "total_matched": 0,
                "by_level": {},
                "by_quadrant": {},
                "avg_confidence": 0,
                "total_price_impact": 0
            }
        
        # 按事件等级统计
        by_level = {}
        for event in matched_events:
            level = event["event_level"]
            by_level[level] = by_level.get(level, 0) + 1
        
        # 按象限统计
        by_quadrant = {}
        for event in matched_events:
            quadrant = event["event_quadrant"]
            by_quadrant[quadrant] = by_quadrant.get(quadrant, 0) + 1
        
        # 计算平均置信度
        avg_confidence = sum(e["match_confidence"] for e in matched_events) / len(matched_events)
        
        # 计算总价格影响
        total_price_impact = sum(abs(e["price_impact"]["change"]) for e in matched_events)
        
        return {
            "total_matched": len(matched_events),
            "by_level": by_level,
            "by_quadrant": by_quadrant,
            "avg_confidence": round(avg_confidence, 2),
            "total_price_impact": round(total_price_impact, 2)
        }


def match_events(target: str, start: str, end: str, 
                price_series: List[Dict[str, Any]], 
                data_dir: str = "data") -> Dict[str, Any]:
    """
    执行事件匹配分析
    
    Args:
        target: 品种 "gold" | "silver"
        start: 开始日期
        end: 结束日期
        price_series: 价格序列（来自L1）
        data_dir: 数据目录路径
        
    Returns:
        事件匹配结果
    """
    logger.info(f"开始事件匹配: {target} {start}~{end}")
    
    # 初始化事件匹配器
    matcher = EventMatcher(data_dir)
    
    # 1. 加载事件数据
    events = matcher.load_events()
    
    # 2. 检测异常波动日
    anomaly_days = matcher.detect_anomaly_days(price_series)
    
    # 3. 匹配事件
    matched_events = matcher.match_events_with_anomalies(anomaly_days, events)
    
    # 4. 分析事件影响
    impact_stats = matcher.analyze_event_impact(matched_events)
    
    # 5. 构建结果
    result = {
        "target": target,
        "period": {
            "start": start,
            "end": end
        },
        "anomaly_detection": {
            "total_days": len(price_series),
            "anomaly_days": len(anomaly_days),
            "anomaly_threshold": anomaly_days[0]["threshold"] if anomaly_days else 0,
            "details": anomaly_days
        },
        "matched_events": matched_events,
        "impact_analysis": impact_stats,
        "summary": _generate_event_summary(matched_events, impact_stats)
    }
    
    logger.info(f"事件匹配完成: {len(matched_events)} 个匹配事件")
    return result


def _generate_event_summary(matched_events: List[Dict[str, Any]], 
                           impact_stats: Dict[str, Any]) -> str:
    """生成事件匹配摘要"""
    if not matched_events:
        return "窗口内未检测到显著的事件驱动波动"
    
    total_matched = impact_stats["total_matched"]
    by_level = impact_stats.get("by_level", {})
    
    # 统计S/A级事件
    sa_events = sum(count for level, count in by_level.items() if level in ["S", "A"])
    
    # 获取最重要的事件
    if matched_events:
        top_event = matched_events[0]
        summary = f"检测到 {total_matched} 个事件匹配，其中 {sa_events} 个为S/A级重要事件。"
        summary += f" 最主要事件: {top_event['event_title']} ({top_event['event_level']}级)，"
        summary += f"导致价格{top_event['direction']} {abs(top_event['price_impact']['change']):.2f}点。"
    else:
        summary = f"检测到 {total_matched} 个事件匹配。"
    
    return summary


if __name__ == "__main__":
    # 测试代码
    import sys
    
    # 配置日志
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    print("测试事件匹配模块...")
    
    # 创建模拟价格序列
    mock_price_series = []
    base_date = datetime(2026, 5, 1)
    base_price = 4400
    
    for i in range(20):
        date = base_date + timedelta(days=i)
        # 模拟一些波动
        if i == 5:  # 第5天异常上涨
            price = base_price + 100
        elif i == 12:  # 第12天异常下跌
            price = base_price - 80
        else:
            price = base_price + (i * 2)  # 缓慢上涨
        
        mock_price_series.append({
            "date": date.strftime("%Y-%m-%d"),
            "value": price,
            "timestamp": date
        })
    
    try:
        result = match_events(
            target="gold",
            start="2026-05-01",
            end="2026-05-20",
            price_series=mock_price_series,
            data_dir="data"
        )
        
        print(f"\n事件匹配结果:")
        print(f"异常波动日: {result['anomaly_detection']['anomaly_days']} 个")
        print(f"匹配事件: {result['impact_analysis']['total_matched']} 个")
        print(f"摘要: {result['summary']}")
        
        if result['matched_events']:
            print(f"\n前3个匹配事件:")
            for i, event in enumerate(result['matched_events'][:3]):
                print(f"{i+1}. {event['event_title']} ({event['event_level']}级)")
                print(f"   日期: {event['anomaly_date']} ← {event['event_date']}")
                print(f"   价格变动: {event['direction']} {abs(event['price_impact']['change']):.2f}点")
                print(f"   置信度: {event['match_confidence']}")
        
    except Exception as e:
        print(f"测试失败: {e}")