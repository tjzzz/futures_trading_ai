#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
order_list_gen.py — 条件单清单生成器（执行装置）
v2-agent-team M4「机会探查」可移植内核（纯 Python 标准库，不依赖 WorkBuddy）。

用途：
  把「事件预案 / 交易计划」的结构化参数，转成一张可直接挂单的条件单清单
  （触发单 + 止损单 + 目标单），并做风险校验（Elder 2%）。
  解决"预案判断全对、夜盘无预埋单导致踏空"的执行缺口（R4 补充条款）。

用法：
  python skills/opportunity/scripts/order_list_gen.py --plan <plan.json> [--out <output.md>]
  python skills/opportunity/scripts/order_list_gen.py --demo   # 内置示例

plan.json 字段（全部必填，校验失败会报错）：
  plan_name      预案名称，如 "非农 B 预案"
  symbol         品种，如 "沪银连续"
  contract       合约，如 "ag2612"
  direction      方向，"多" 或 "空"
  hands          手数（int）
  trigger_low    触发价下沿（float）
  trigger_high   触发价上沿（float；与 low 相等=单点触发）
  stop           止损价（float）
  target         第一目标价（float）
  risk_per_hand  单手风险（元，= |入场参考 - 止损| × 乘数；预算内可估）
  risk_budget    单笔风险预算（元，默认 10000 = 50w 本金 × 2%）
  valid_until    挂单有效期，如 "2026-08-07 20:30 前"
  trigger_rule   触发条件说明，如 "回踩止跌确认（4h 收阳/不创新低）"

输出：Markdown 条件单清单（执行装置），含风险校验结论。
"""

import argparse
import json
import sys
from datetime import datetime


def validate(plan: dict) -> list:
    """返回错误列表，空=通过。"""
    required = [
        "plan_name", "symbol", "contract", "direction", "hands",
        "trigger_low", "trigger_high", "stop", "target", "risk_per_hand",
        "valid_until",
    ]
    errs = []
    for k in required:
        if k not in plan or plan[k] in (None, ""):
            errs.append(f"缺少必填字段: {k}")
    if errs:
        return errs
    if plan["direction"] not in ("多", "空"):
        errs.append("direction 必须为 '多' 或 '空'")
    if plan["hands"] < 1:
        errs.append("hands 必须 ≥ 1")
    if plan["trigger_low"] > plan["trigger_high"]:
        errs.append("trigger_low 不能大于 trigger_high")
    # 方向合理性：多单止损 < 触发价下沿 < 目标；空单反之
    if plan["direction"] == "多":
        if not (plan["stop"] < plan["trigger_low"] <= plan["target"]):
            errs.append("多单要求: stop < trigger_low <= target")
    else:
        if not (plan["stop"] > plan["trigger_high"] >= plan["target"]):
            errs.append("空单要求: stop > trigger_high >= target")
    risk_budget = plan.get("risk_budget", 10000)
    total_risk = plan["risk_per_hand"] * plan["hands"]
    if total_risk > risk_budget:
        errs.append(
            f"风险超预算: 单手 {plan['risk_per_hand']} × {plan['hands']}手 = "
            f"{total_risk} 元 > 预算 {risk_budget} 元（Elder 2% 违规）"
        )
    return errs


def build_list(plan: dict) -> str:
    """生成条件单清单 Markdown。"""
    d = plan
    low, high = d["trigger_low"], d["trigger_high"]
    trigger_txt = f"{low}" if low == high else f"{low} - {high}"
    total_risk = d["risk_per_hand"] * d["hands"]
    risk_budget = d.get("risk_budget", 10000)
    ok = "✅ 合规" if total_risk <= risk_budget else "❌ 超预算"

    # 赔率（多单：目标-触发 vs 触发-止损；空单反向）。区间触发 → 输出 下沿/中值/上沿 三档
    if d["direction"] == "多":
        rr_low = (d["target"] - low) / max(low - d["stop"], 1e-9)
        rr_mid = (d["target"] - (low + high) / 2) / max((low + high) / 2 - d["stop"], 1e-9)
        rr_high = (d["target"] - high) / max(high - d["stop"], 1e-9)
    else:
        rr_low = (high - d["target"]) / max(d["stop"] - high, 1e-9)
        rr_mid = ((low + high) / 2 - d["target"]) / max(d["stop"] - (low + high) / 2, 1e-9)
        rr_high = (low - d["target"]) / max(d["stop"] - low, 1e-9)
    rr_mid = (rr_low + rr_mid + rr_high) / 3  # 三档均值作汇总参考

    lines = []
    lines.append(f"# 条件单清单 · {d['plan_name']}")
    lines.append("")
    lines.append(f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"> 有效窗口：{d['valid_until']}")
    lines.append(f"> 触发规则：{d.get('trigger_rule', '—')}")
    lines.append("")
    lines.append("## 一、待挂条件单（按顺序挂）")
    lines.append("")
    lines.append("| # | 单类型 | 合约 | 方向 | 触发/价格 | 手数 | 说明 |")
    lines.append("|:-:|:--|:--|:-:|:-:|:-:|:--|")
    lines.append(f"| 1 | 触发单 | {d['contract']} | {d['direction']} | {trigger_txt} | {d['hands']} | 入场；{d.get('trigger_rule', '')} |")
    lines.append(f"| 2 | 止损单 | {d['contract']} | 反方向 | {d['stop']} | {d['hands']} | 触发单成交后随挂（R4 硬要求） |")
    lines.append(f"| 3 | 第一目标 | {d['contract']} | 反方向 | {d['target']} | {d['hands']} | 止盈；成交后视逻辑决定是否移保本 |")
    lines.append("")
    lines.append("## 二、风险校验（Elder 2%）")
    lines.append("")
    lines.append(f"- 单手风险：{d['risk_per_hand']} 元 × {d['hands']} 手 = **{total_risk} 元**")
    lines.append(f"- 风险预算：{risk_budget} 元 → {ok}")
    lines.append(f"- 赔率（第一目标）：下沿 {rr_low:.2f} / 中值 {rr_mid:.2f} / 上沿 {rr_high:.2f}"
                 + ("（区间触发，越贴近下沿越优 ✅）" if d["direction"] == "多" and rr_low >= 2 else ""))
    lines.append("")
    lines.append("## 三、失效条件")
    lines.append("")
    lines.append("- " + d.get("invalidate", "预案触发前价格跌破/突破关键位（见预案原文），或事件落地方向与预案不符 → 取消挂单"))
    lines.append("")
    lines.append("## 四、注意")
    lines.append("")
    lines.append("- 条件单触发依赖行情引擎，跳空/流动性不足时可能滑点；止损单防跳空依赖对手价，夜盘慎用市价止损")
    lines.append("- 本清单为执行装置，不构成投资建议；实盘挂单需镇哥明确授权")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="条件单清单生成器（执行装置）")
    ap.add_argument("--plan", help="预案 JSON 文件路径")
    ap.add_argument("--out", help="输出 Markdown 路径（默认 stdout）")
    ap.add_argument("--demo", action="store_true", help="输出内置示例")
    args = ap.parse_args()

    if args.demo:
        plan = {
            "plan_name": "非农 B 预案（示例）",
            "symbol": "沪银连续",
            "contract": "ag2612",
            "direction": "多",
            "hands": 1,
            "trigger_low": 15140,
            "trigger_high": 15265,
            "stop": 14825,
            "target": 15925,
            "risk_per_hand": 5696,
            "risk_budget": 10000,
            "valid_until": "2026-08-07 20:30 前",
            "trigger_rule": "回踩止跌确认（4h 收阳/不创新低）",
            "invalidate": "事件落地方向与 B 预案不符（如非农强劲、金银回踩破 59）",
        }
    else:
        if not args.plan:
            ap.error("需要 --plan <json> 或 --demo")
        with open(args.plan, encoding="utf-8") as f:
            plan = json.load(f)

    errs = validate(plan)
    if errs:
        print("❌ 预案参数校验失败：", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    out = build_list(plan)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"[written] {args.out}")
    else:
        print(out)


if __name__ == "__main__":
    main()
