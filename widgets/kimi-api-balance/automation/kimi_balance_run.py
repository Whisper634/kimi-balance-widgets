"""Kimi（Moonshot 开放平台）API 账户余额查询（Blueprint Python Automation 入口）。

凭据：与本文件同目录的 kimi_key.txt（platform.kimi.com 的 API key，sk-...）。
返回：{"artifact": {...}}，结构对齐「Kimi API 余额」小组件的 slots.main。
"""
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

API = "https://api.moonshot.cn/v1/users/me/balance"
ASSETS = os.path.dirname(os.path.abspath(__file__))


def run(ctx):
    try:
        with open(os.path.join(ASSETS, "kimi_key.txt")) as f:
            key = f.read().strip()
        if not key:
            raise ValueError("empty key")
    except Exception as e:
        return {"artifact": {"ok": False, "error": "auth", "detail": f"凭据文件缺失或损坏: {e}", "updatedAt": ""}}

    req = urllib.request.Request(API, headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:300]
        kind = "auth" if e.code in (401, 403) else "api"
        return {"artifact": {"ok": False, "error": kind, "detail": f"HTTP {e.code}: {detail}", "updatedAt": ""}}
    except Exception as e:
        return {"artifact": {"ok": False, "error": "network", "detail": str(e)[:300], "updatedAt": ""}}

    data = d.get("data") or {}
    if not data:
        return {"artifact": {"ok": False, "error": "api", "detail": f"余额接口返回异常: {str(d)[:200]}", "updatedAt": ""}}

    total = float(data.get("available_balance", 0) or 0)
    voucher = float(data.get("voucher_balance", 0) or 0)
    cash = float(data.get("cash_balance", 0) or 0)
    voucher_pct = round(voucher / total * 100, 1) if total > 0 else 0.0
    cash_pct = round(cash / total * 100, 1) if total > 0 else 0.0

    return {
        "artifact": {
            "ok": bool(d.get("status")),
            "available": bool(d.get("status")),
            "currency": "CNY",
            "total": total,
            "cash": cash,
            "voucher": voucher,
            "cashPct": cash_pct,
            "voucherPct": voucher_pct,
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        }
    }
