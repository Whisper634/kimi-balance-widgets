"""Kimi 订阅（Allegretto）coding 用量查询（Blueprint Python Automation 入口）。

凭据：与本文件同目录的 kimi_refresh.txt（kimi.com refresh_token，长效）。
流程：refresh_token -> GET /api/auth/token/refresh 换 access_token（约 30 天有效）
      -> Connect-RPC 调用会员网关 GetSubscriptionStats / GetSubscription。
返回：{"artifact": {...}}，结构对齐「Kimi 订阅用量」小组件的 slots.main。
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


def derived(remaining_pct, reset_at, assets_dir):
    """订阅额度的记账/外推：剩余百分比 → 日均消耗几个点 → 还能撑几天 → 是否会在重置前打光。"""
    th = insights.load_thresholds(assets_dir)
    points = insights.record_value(os.path.join(assets_dir, "history.json"), remaining_pct)
    used_pct = 100.0 - float(remaining_pct) if remaining_pct is not None else None
    cyc_rate, cycle_days = insights.cycle_rate(reset_at, used_pct)
    hist_rate = insights.rate_per_day(points, th["windowDays"])
    if cyc_rate and cyc_rate > 0:
        rate, rate_basis = cyc_rate, "cycle"
    else:
        rate, rate_basis = hist_rate, "history"
    days, exhaust_at = insights.project(remaining_pct, rate)
    reset_days = insights.days_between(insights.now_utc(), reset_at)
    reset_days = reset_days if reset_days > 0 else None

    level = insights.level_for_ratio(remaining_pct, th["quotaWarnPct"], th["quotaAlertPct"])
    if days is not None and reset_days is not None and days < reset_days:
        level = insights.worst(level, "alert")

    if rate:
        if rate_basis == "cycle":
            base = "本周期日均 %.1f 个点（%.0f 天用了 %.1f%%）" % (rate, cycle_days or 0, used_pct or 0)
        else:
            base = "日均消耗 %.1f 个百分点" % rate
        if days is None:
            hint = base + "，还在攒样本"
        elif days <= 0:
            hint = "额度已打光"
        elif reset_days is not None and days < reset_days:
            hint = "%s，约 %s 打光 —— 距重置还有 %d 天，撑不到重置" % (
                base, insights.date_label(exhaust_at), int(round(reset_days)))
        elif reset_days is not None:
            hint = "%s，够用到 %s 重置（还有 %d 天）" % (
                base, insights.date_label(reset_at), int(round(reset_days)))
        else:
            hint = "%s，还能撑 %s（约 %s）" % (base, insights.day_text(days), insights.date_label(exhaust_at))
    else:
        hint = "本周期还没有消耗"

    return {
        "level": level,
        "rateBasis": rate_basis,
        "cycleDays": (round(cycle_days, 1) if cycle_days else None),
        "burnPerDay": (round(rate, 3) if rate else None),
        "daysLeft": (round(days, 2) if days is not None else None),
        "daysToReset": (int(round(reset_days)) if reset_days is not None else None),
        "exhaustAt": exhaust_at,
        "windowDays": int(th["windowDays"]),
        "samples": len(points),
        "series": insights.daily_usage(points, 14),
        "hint": hint,
    }


def post_rpc(path, token):
    req = urllib.request.Request(
        BASE + path,
        data=b"{}",
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Connect-Protocol-Version": "1",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def fail(kind, detail):
    return {"artifact": {"ok": False, "error": kind, "detail": detail, "updatedAt": ""}}


def run(ctx):
    try:
        with open(os.path.join(ASSETS, "kimi_refresh.txt")) as f:
            refresh = f.read().strip()
        if not refresh:
            raise ValueError("empty refresh token")
    except Exception as e:
        return fail("auth", f"凭据文件缺失或损坏: {e}")

    # 1) 用 refresh_token 换 access_token（该端点是 GET + Bearer）
    req = urllib.request.Request(
        BASE + "/api/auth/token/refresh",
        headers={"Authorization": f"Bearer {refresh}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            tokens = json.loads(r.read())
        access = tokens.get("access_token", "")
        if not access:
            raise ValueError("no access_token in refresh response")
        # 轮换持久化 refresh_token（每次刷新都会签发新的）
        new_refresh = tokens.get("refresh_token")
        if new_refresh:
            with open(os.path.join(ASSETS, "kimi_refresh.txt"), "w") as f:
                f.write(new_refresh.strip() + "\n")
    except urllib.error.HTTPError as e:
        return fail("auth", f"刷新令牌失败 HTTP {e.code}: {e.read().decode()[:200]}")
    except Exception as e:
        return fail("network", f"刷新令牌失败: {str(e)[:200]}")

    # 2) 调用量接口
    try:
        stats = post_rpc("/apiv2/kimi.gateway.membership.v2.MembershipService/GetSubscriptionStats", access)
    except urllib.error.HTTPError as e:
        return fail("api", f"用量接口 HTTP {e.code}: {e.read().decode()[:200]}")
    except Exception as e:
        return fail("network", f"用量接口失败: {str(e)[:200]}")

    sub = {}
    try:
        sub = post_rpc("/apiv2/kimi.gateway.membership.v2.MembershipService/GetSubscription", access)
    except Exception:
        pass

    bal = stats.get("subscriptionBalance") or {}
    ratio = float(bal.get("amountUsedRatio", 0) or 0) * 100
    code_ratio = float(bal.get("kimiCodeUsedRatio", 0) or 0) * 100

    boost_left = boost_total = boost_used = None
    wallets = stats.get("boosterWallets") or []
    if wallets:
        w = wallets[0]
        boost_left = int((w.get("moneyLeft") or {}).get("priceInCents", 0)) / 100
        boost_total = int((w.get("moneyTotal") or {}).get("priceInCents", 0)) / 100
        boost_used = int((w.get("monthlyUsed") or {}).get("priceInCents", 0)) / 100

    subscription = sub.get("subscription") or {}
    goods = subscription.get("goods") or {}

    remaining_pct = round(100 - ratio, 1)
    artifact = {
        "ok": True,
        "active": bool(subscription.get("active", True)),
        "plan": goods.get("title", ""),
        "totalPct": round(ratio, 1),
        "remainingPct": remaining_pct,
        "codePct": round(code_ratio, 1),
        "resetAt": bal.get("expireTime", ""),
        "subEnd": subscription.get("currentEndTime", ""),
        "boostLeft": boost_left,
        "boostTotal": boost_total,
        "boostMonthlyUsed": boost_used,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }
    artifact.update(derived(remaining_pct, artifact["resetAt"], ASSETS))
    return {"artifact": artifact}
