"""DeepSeek API 账户余额查询（Blueprint Python Automation 入口）。

凭据：与本文件同目录的 deepseek_key.txt（DeepSeek API key，sk-...）。
返回：{"artifact": {...}}，结构对齐「DeepSeek API 余额」小组件的 slots.main。
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import insights

API = "https://api.deepseek.com/user/balance"
ASSETS = os.path.dirname(os.path.abspath(__file__))


def build_hint(rate, days, exhaust_at, level, window_days):
    """一句话结论。JSON 里也带一份，方便脚本日志和将来的通知渠道复用。"""
    prefix = "余额告急：" if level == "alert" else ("余额偏低：" if level == "warn" else "")
    if not rate:
        return prefix + "近 %d 天没有观测到消耗" % window_days
    if days is None:
        return prefix + "样本不足，还算不出用完日期"
    if days <= 0:
        return prefix + "已经用完了"
    return prefix + "日均 %s · 还能撑 %s（约 %s 用完）" % (
        insights.money(rate), insights.day_text(days), insights.date_label(exhaust_at))


def derived(total, assets_dir):
    """记账 → 日均消耗 → 剩余天数 → 告警级别。返回可直接并进 artifact 的字段。"""
    th = insights.load_thresholds(assets_dir)
    points = insights.record_value(os.path.join(assets_dir, "history.json"), total)
    rate = insights.rate_per_day(points, th["windowDays"])
    days, exhaust_at = insights.project(total, rate)
    level = insights.level_for_money(total, th["balanceWarn"], th["balanceAlert"])
    return {
        "level": level,
        "peakShare": insights.peak_share(points),
        "burnPerDay": (round(rate, 4) if rate else None),
        "daysLeft": (round(days, 2) if days is not None else None),
        "exhaustAt": exhaust_at,
        "windowDays": int(th["windowDays"]),
        "samples": len(points),
        "series": insights.daily_usage(points, 14),
        "charts": {
            "1h": insights.chart_series(points, "1h", "money" if "balance" in 'widgets/deepseek-balance/automation/deepseek_balance_run.py' else "pct"),
            "24h": insights.chart_series(points, "24h", "money" if "balance" in 'widgets/deepseek-balance/automation/deepseek_balance_run.py' else "pct"),
            "14d": insights.chart_series(points, "14d", "money" if "balance" in 'widgets/deepseek-balance/automation/deepseek_balance_run.py' else "pct"),
            "30d": insights.chart_series(points, "30d", "money" if "balance" in 'widgets/deepseek-balance/automation/deepseek_balance_run.py' else "pct"),
        },
        "hint": build_hint(rate, days, exhaust_at, level, th["windowDays"]),
    }


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
    total = float(info.get("total_balance", 0) or 0)
    artifact = {
        "ok": True,
        "available": bool(d.get("is_available")),
        "currency": info.get("currency", ""),
        "total": total,
        "granted": float(info.get("granted_balance", 0) or 0),
        "toppedUp": float(info.get("topped_up_balance", 0) or 0),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }
    artifact.update(derived(total, ASSETS))
    return {"artifact": artifact}
