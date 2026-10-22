"""火山方舟模型免费额度抓取（Blueprint Python Automation 入口）。

凭据：与本文件同目录的 volc_cookies.json（.volcengine.com 会话 cookie）。
返回：{"artifact": {...}}，结构对齐「火山方舟模型额度」小组件的 slots.main。
"""
import json
import os
import sys
import urllib.error
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import insights

API = "https://console.volcengine.com/api/top/ark/cn-beijing/2024-01-01/ListModelChargeItems"
ASSETS = os.path.dirname(os.path.abspath(__file__))


def annotate(models, assets_dir):
    """给每个模型折算「剩余额度值多少钱」，并按价值排序出「先烧谁」。"""
    th = insights.load_thresholds(assets_dir)
    opened = [m for m in models if m["opened"]]
    for m in models:
        pct = (m["remaining"] / m["total"] * 100.0) if m["total"] else None
        m["remainingPct"] = round(pct, 1) if pct is not None else None
        m["valueOut"] = insights.tokens_value(m["remaining"], m.get("priceOut"))
        m["valueIn"] = insights.tokens_value(m["remaining"], m.get("priceIn"))

    ranked = sorted([m for m in opened if m.get("valueOut") is not None], key=lambda m: -m["valueOut"])
    for i, m in enumerate(ranked):
        m["priority"] = i + 1

    total_out = sum(m["valueOut"] for m in opened if m.get("valueOut") is not None)
    total_in = sum(m["valueIn"] for m in opened if m.get("valueIn") is not None)
    remain_all = sum(m["remaining"] for m in opened)
    tokens_all = sum(m["total"] for m in opened)

    points = insights.record_value(os.path.join(assets_dir, "history.json"), remain_all)
    rate = insights.rate_per_day(points, th["windowDays"])
    days, exhaust_at = insights.project(remain_all, rate)

    low = [m for m in opened if m["remaining"] <= th["tokensWarn"]]
    level = "warn" if low else "ok"
    if remain_all <= th["tokensWarn"]:
        level = "alert"

    parts = []
    if ranked:
        top = ranked[0]
        parts.append("合计剩余价值约 %s（按输出价）" % insights.money(total_out))
        parts.append("先用 %s（值 %s）" % (top.get("display") or top["name"], insights.money(top["valueOut"])))
    if rate:
        parts.append("日均消耗 %s tokens · 还能撑 %s" % (
            format(int(round(rate)), ","), insights.day_text(days)))
    elif rate == 0:
        parts.append("近 %d 天没动过" % int(th["windowDays"]))
    if low:
        parts.insert(0, "%d 个模型快见底" % len(low))

    return {
        "level": level,
        "totalValueOut": round(total_out, 2),
        "totalValueIn": round(total_in, 2),
        "remainAll": remain_all,
        "tokensAll": tokens_all,
        "burnPerDay": (round(rate, 1) if rate else None),
        "daysLeft": (round(days, 2) if days is not None else None),
        "exhaustAt": exhaust_at,
        "priorityName": (ranked[0].get("display") or ranked[0]["name"]) if ranked else None,
        "windowDays": int(th["windowDays"]),
        "samples": len(points),
        "hint": " · ".join(parts) if parts else "",
    }


def load_cookie_header():
    with open(os.path.join(ASSETS, "volc_cookies.json")) as f:
        cookies = json.load(f)
    seen = {}
    for c in cookies:
        seen[(c["name"], c["domain"])] = c
    header = "; ".join(f"{c['name']}={c['value']}" for c in seen.values())
    csrf = next((c["value"] for c in cookies if c["name"] == "csrfToken"), "")
    return header, csrf


def fmt_price(items, type_):
    for it in items or []:
        if it.get("Type") == type_:
            return it.get("Price")
    return None


def fetch(cookie_hdr, csrf, extra):
    body = {
        "Filter": {"FoundationModelTag": {"Domains": ["LLM"]}},
        "PageNumber": 1,
        "PageSize": 100,
    }
    body.update(extra)
    req = urllib.request.Request(
        API,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "X-Csrf-Token": csrf,
            "Cookie": cookie_hdr,
            "Origin": "https://console.volcengine.com",
            "Referer": "https://console.volcengine.com/",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def run(ctx):
    try:
        cookie_hdr, csrf = load_cookie_header()
    except Exception as e:
        return {"artifact": {"ok": False, "error": "auth", "detail": f"凭据文件缺失或损坏: {e}"[:300], "models": []}}

    try:
        d = fetch(cookie_hdr, csrf, {"Fields": ["Base", "SubServices", "FreeUsage"]})
        d_price = fetch(cookie_hdr, csrf, {})
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:300]
        kind = "auth" if e.code in (401, 403) or "NotLogin" in detail or "CSRF" in detail else f"http_{e.code}"
        if kind != "auth":
            kind = "api"
        return {"artifact": {"ok": False, "error": kind, "detail": f"HTTP {e.code}", "models": []}}
    except Exception as e:
        return {"artifact": {"ok": False, "error": "network", "detail": str(e)[:300], "models": []}}

    err = d.get("ResponseMetadata", {}).get("Error")
    if err:
        msg = err.get("Message", "")
        kind = "auth" if ("登录" in msg or "CSRF" in msg or "NotLogin" in msg) else "api"
        return {"artifact": {"ok": False, "error": kind, "detail": msg[:300], "models": []}}

    prices = {}
    for it in (d_price.get("Result") or {}).get("Items") or []:
        prices[it["FoundationModelName"]] = it.get("ChargeItems")

    models = []
    for it in d["Result"]["Items"]:
        name = it["FoundationModelName"]
        opened = it.get("State") == "Available"
        pack = None
        for rp in it.get("ResourcePackItems") or []:
            if rp.get("Type") == "FreeInference":
                pack = rp
                break
        if pack is None:
            fu = it.get("InferenceFreeUsage")
            if fu and fu.get("Total"):
                pack = {"Total": fu["Total"], "Consumed": fu.get("Consumed", 0), "SyncTime": None}
        if not opened and pack is None:
            continue
        entry = {
            "name": name,
            "display": it.get("DisplayName", name),
            "vendor": it.get("VendorName", ""),
            "opened": opened,
            "total": pack["Total"] if pack else 0,
            "consumed": pack["Consumed"] if pack else 0,
            "syncTime": pack.get("SyncTime") if pack else None,
            "priceIn": fmt_price(prices.get(name), "InferencePrompt"),
            "priceOut": fmt_price(prices.get(name), "InferenceCompletion"),
        }
        entry["remaining"] = entry["total"] - entry["consumed"]
        models.append(entry)
    models.sort(key=lambda m: (not m["opened"], -m["remaining"]))
    extra = annotate(models, ASSETS)

    artifact = {
        "ok": True,
        "accountId": 2133281834,
        "updatedAt": d.get("ResponseMetadata", {}).get("RequestId", ""),
        "models": models,
    }
    artifact.update(extra)
    return {"artifact": artifact}
