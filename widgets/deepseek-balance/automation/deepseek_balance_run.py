"""DeepSeek API 账户余额查询（Blueprint Python Automation 入口）。

凭据：与本文件同目录的 deepseek_key.txt（DeepSeek API key，sk-...）。
返回：{"artifact": {...}}，结构对齐「DeepSeek API 余额」小组件的 slots.main。
"""
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

API = "https://api.deepseek.com/user/balance"
ASSETS = os.path.dirname(os.path.abspath(__file__))


def run(ctx):
    try:
        with open(os.path.join(ASSETS, "deepseek_key.txt")) as f:
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

    infos = d.get("balance_infos") or []
    if not infos:
        return {"artifact": {"ok": False, "error": "api", "detail": "余额接口返回为空", "updatedAt": ""}}

    info = infos[0]
    return {
        "artifact": {
            "ok": True,
            "available": bool(d.get("is_available")),
            "currency": info.get("currency", ""),
            "total": float(info.get("total_balance", 0) or 0),
            "granted": float(info.get("granted_balance", 0) or 0),
            "toppedUp": float(info.get("topped_up_balance", 0) or 0),
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        }
    }
