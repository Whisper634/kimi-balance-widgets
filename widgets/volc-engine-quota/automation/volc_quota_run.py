"""火山方舟模型免费额度抓取（Blueprint Python Automation 入口）。

凭据：与本文件同目录的 volc_cookies.json（.volcengine.com 会话 cookie）。
返回：{"artifact": {...}}，结构对齐「火山方舟模型额度」小组件的 slots.main。
"""
import json
import os
import urllib.error
import urllib.request

API = "https://console.volcengine.com/api/top/ark/cn-beijing/2024-01-01/ListModelChargeItems"
ASSETS = os.path.dirname(os.path.abspath(__file__))


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

    return {
        "artifact": {
            "ok": True,
            "accountId": 2133281834,
            "updatedAt": d.get("ResponseMetadata", {}).get("RequestId", ""),
            "models": models,
        }
    }
