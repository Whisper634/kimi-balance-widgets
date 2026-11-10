"""Kimi 加油包（booster wallet）额度查询（Blueprint Python Automation 入口）。

凭据：与本文件同目录的 kimi_refresh.txt（kimi.com refresh_token，长效）。
流程：refresh_token -> GET /api/auth/token/refresh 换 access_token
      -> Connect-RPC GetSubscriptionStats -> boosterWallets[0]。
返回：{"artifact": {...}}，结构对齐「Kimi 加油包」小组件的 slots.main。
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

BASE = "https://www.kimi.com"
ASSETS = os.path.dirname(os.path.abspath(__file__))
# refresh_token 会在每次换取 access_token 时轮换；订阅用量自动化也用同一份文件。
# 优先用本目录的，其次回落到蓝图里「Kimi 订阅用量」自动化的 assets（单一令牌来源）。
SIBLING_TOKEN = os.path.join(
    os.path.dirname(os.path.dirname(ASSETS)),
    "automation_fe966618-a138-4f5e-b693-e3e762569777", "assets", "kimi_refresh.txt")


def yen(node):
    """钱包金额节点 {priceInCents: "2500"} -> 25.0 元。"""
    try:
        return round(int((node or {}).get("priceInCents", 0) or 0) / 100.0, 2)
    except Exception:
        return 0.0


def build_hint(left, used_pct, month_used, rate, days, exhaust_at, cycle_end, level, window_days):
    prefix = "加油包告急：" if level == "alert" else ("加油包偏低：" if level == "warn" else "")
    head = "余额 ¥%.2f（已用 %.1f%%）" % (left, used_pct or 0)
    if month_used:
        head += " · 本周期消费 ¥%.2f" % month_used
    if not rate:
        tail = "近 %d 天没观测到扣费" % window_days
    elif days is None:
        tail = "样本不足，还算不出用完日期"
    elif days <= 0:
        tail = "已经用完了"
    else:
        tail = "日均 ¥%.2f · 还能撑 %s（约 %s 用完）" % (rate, insights.day_text(days), insights.date_label(exhaust_at))
    if cycle_end:
        tail += " · %s 重置周期" % insights.date_label(cycle_end)
    return prefix + head + " · " + tail


def derived(left, total, month_used, cycle_end, assets_dir):
    """记账 → 日均扣费 → 剩余天数 → 告警级别。"""
    th = insights.load_thresholds(assets_dir)
    points = insights.record_value(os.path.join(assets_dir, "history.json"), left)
    rate = insights.rate_per_day(points, th["windowDays"])
    days, exhaust_at = insights.project(left, rate)
    level = insights.level_for_money(left, th["balanceWarn"], th["balanceAlert"])
    used = round(max(0.0, total - left), 2)
    used_pct = round((used / total * 100.0) if total else 0.0, 1)
    return {
        "level": level,
        "used": used,
        "usedPct": used_pct,
        "remainPct": round(100.0 - used_pct, 1),
        "peakShare": insights.peak_share(points),
        "burnPerDay": (round(rate, 4) if rate else None),
        "daysLeft": (round(days, 2) if days is not None else None),
        "exhaustAt": exhaust_at,
        "windowDays": int(th["windowDays"]),
        "samples": len(points),
        "series": insights.daily_usage(points, 14),
        "charts": {
            "hour": insights.usage_series(points, 8),
            "1h": insights.chart_series(points, "1h", "money"),
            "24h": insights.chart_series(points, "24h", "money"),
            "14d": insights.chart_series(points, "14d", "money"),
            "30d": insights.chart_series(points, "30d", "money"),
        },
        "hint": build_hint(left, used_pct, month_used, rate, days, exhaust_at, cycle_end, level, th["windowDays"]),
    }


def post_rpc(path, token):
    req = urllib.request.Request(
        BASE + path,
        data=b"{}",
        method="POST",
        headers={
            "Authorization": "Bearer %s" % token,
            "Content-Type": "application/json",
            "Connect-Protocol-Version": "1",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def fail(kind, detail):
    return {"artifact": {"ok": False, "error": kind, "detail": detail, "updatedAt": ""}}


def token_file():
    for p in (os.path.join(ASSETS, "kimi_refresh.txt"), SIBLING_TOKEN):
        if os.path.exists(p):
            return p
    return os.path.join(ASSETS, "kimi_refresh.txt")


def refresh_access_token():
    """换 access_token。令牌轮换期间可能和订阅自动化撞车，失败时重读一次文件再试。"""
    last_err = None
    for attempt in range(2):
        path = token_file()
        try:
            with open(path) as f:
                refresh = f.read().strip()
            if not refresh:
                raise ValueError("empty refresh token")
        except Exception as e:
            return None, fail("auth", "凭据文件缺失或损坏: %s" % e)
        req = urllib.request.Request(
            BASE + "/api/auth/token/refresh",
            headers={"Authorization": "Bearer %s" % refresh},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                tokens = json.loads(r.read())
            access = tokens.get("access_token", "")
            if not access:
                raise ValueError("no access_token in refresh response")
            new_refresh = tokens.get("refresh_token")
            if new_refresh:
                with open(path, "w") as f:
                    f.write(new_refresh.strip() + "\n")
            return access, None
        except urllib.error.HTTPError as e:
            last_err = fail("auth", "刷新令牌失败 HTTP %s: %s" % (e.code, e.read().decode()[:200]))
        except Exception as e:
            last_err = fail("network", "刷新令牌失败: %s" % str(e)[:200])
        if attempt == 0:
            import time
            time.sleep(2)
    return None, last_err


def run(ctx):
    access, err = refresh_access_token()
    if err:
        return err

    try:
        stats = post_rpc("/apiv2/kimi.gateway.membership.v2.MembershipService/GetSubscriptionStats", access)
    except urllib.error.HTTPError as e:
        return fail("api", "用量接口 HTTP %s: %s" % (e.code, e.read().decode()[:200]))
    except Exception as e:
        return fail("network", "用量接口失败: %s" % str(e)[:200])

    wallets = stats.get("boosterWallets") or []
    if not wallets:
        return fail("api", "账号没有加油包钱包（boosterWallets 为空）")

    w = wallets[0]
    left = yen(w.get("moneyLeft"))
    total = yen(w.get("moneyTotal"))
    month_used = yen(w.get("monthlyUsed"))
    cycle_end = w.get("monthlyCycleEnd", "") or ""
    artifact = {
        "ok": True,
        "status": w.get("status", ""),
        "currency": "CNY",
        "left": left,
        "total": total,
        "monthlyUsed": month_used,
        "topupLimit": yen(w.get("topupLimit")),
        "allowTopup": bool(w.get("allowTopup")),
        "autoRefillThreshold": yen(w.get("autoRefillThreshold")),
        "autoRefillCharge": yen(w.get("autoRefillCharge")),
        "monthlyChargeLimit": yen(w.get("monthlyChargeLimit")),
        "cycleStart": w.get("monthlyCycleStart", "") or "",
        "cycleEnd": cycle_end,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }
    artifact.update(derived(left, total, month_used, cycle_end, ASSETS))
    return {"artifact": artifact}
