#!/usr/bin/env python3
"""
SHFE 实时行情查询 — 东财 API，不依赖任何第三方库

用法:
    python tools/query_shfe.py                     # 沪银+沪金全部合约
    python tools/query_shfe.py silver              # 仅沪银
    python tools/query_shfe.py gold                # 仅沪金
    python tools/query_shfe.py silver 2612         # 仅沪银2612合约

输出: JSON，包含每个合约的最新价/涨跌幅/成交量等
"""

import json
import urllib.request
import sys

# 合约代码映射
CONTRACTS = {
    "silver": {
        "2608": "113.AG2608",
        "2610": "113.AG2610",
        "2612": "113.AG2612",
    },
    "gold": {
        "2608": "113.AU2608",
        "2610": "113.AU2610",
        "2612": "113.AU2612",
    },
}

FIELDS = "f43,f44,f45,f46,f47,f48,f50,f57,f58,f60,f170,f171"
FIELD_NAMES = {
    "f43": "最新价", "f44": "最高", "f45": "最低",
    "f46": "今开", "f47": "成交量", "f48": "成交额",
    "f50": "持仓量", "f57": "代码", "f58": "开盘价",
    "f60": "昨收", "f170": "涨跌幅", "f171": "涨跌额",
}


def query_contract(code: str) -> dict | None:
    """查询单个合约"""
    url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={code}&fields={FIELDS}"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://quote.eastmoney.com/",
        })
        resp = urllib.request.urlopen(req, timeout=10)
        d = json.loads(resp.read()).get("data")
        if not d or not d.get("f43"):
            return None

        return {
            "code": d.get("f57", ""),
            "name": d.get("f58", ""),
            "price": d["f43"],
            "change": d.get("f171", 0),
            "change_pct": round((d["f43"] / d["f60"] - 1) * 100, 2) if d.get("f60") else None,
            "open": d.get("f46", 0),
            "high": d.get("f44", 0),
            "low": d.get("f45", 0),
            "prev_close": d.get("f60", 0),
            "volume": d.get("f47", 0),
            "open_interest": d.get("f50", 0),
        }
    except Exception as e:
        return {"error": str(e)}


def main():
    # 解析参数
    args = sys.argv[1:]
    target = args[0] if args else "all"
    contract = args[1] if len(args) > 1 else None

    result = {"updated_at": None, "contracts": {}}

    # 决定查询哪些合约
    if target == "all":
        targets = [("silver", CONTRACTS["silver"]), ("gold", CONTRACTS["gold"])]
    elif target == "silver":
        targets = [("silver", CONTRACTS["silver"])]
    elif target == "gold":
        targets = [("gold", CONTRACTS["gold"])]
    else:
        # 单个合约代码 (如 AG2612)
        code = f"113.{target.upper()}"
        data = query_contract(code)
        label = target.upper()
        result["contracts"][label] = data or {"error": "无数据"}
        targets = []

    for cat, cdict in targets:
        for contract_label, code in cdict.items():
            if contract and contract not in contract_label:
                continue
            data = query_contract(code)
            if data and "error" not in data:
                key = f"{cat}_{contract_label}"
                result["contracts"][key] = data
                result["updated_at"] = "实时"
    else:
        # 直接查询合约代码
        code = f"113.{target.upper()}"
        data = query_contract(code)
        result["contracts"][target] = data or {"error": "无数据"}

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()