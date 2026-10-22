#!/usr/bin/env python3
"""端到端自测：用假的 HTTP 响应跑真实的 run()，验证派生字段确实接上了。

不联网、不碰真实凭据：每个组件的 ASSETS 被重定向到临时目录，
urllib 被替换成固定响应，fetch 被替换成固定字典。

用法： python3 tools/e2e_test.py
"""
import importlib.util
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "shared"))
import insights as ins  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  ok   " if cond else "  FAIL ") + name + ("" if cond else " :: %r" % (extra,)))
    if not cond:
        FAILS.append(name)


def load(rel, alias):
    """按路径加载组件脚本（目录名里有中划线，不能直接 import）。"""
    path = os.path.join(ROOT, rel)
    spec = importlib.util.spec_from_file_location(alias, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod


class FakeResp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def seed(days_ago, value, assets):
    """往临时 assets 里塞一个历史点。"""
    path = os.path.join(assets, "history.json")
    pts = ins.load_points(path)
    pts.append({"t": (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(), "v": value})
    ins.save_points(path, pts)


def main():
    print("[1] DeepSeek 余额：5 天前 100 → 现在 96.5，日均应约 0.7")
    mod = load("widgets/deepseek-balance/automation/deepseek_balance_run.py", "ds_mod")
    with tempfile.TemporaryDirectory() as td:
        mod.ASSETS = td
        open(os.path.join(td, "deepseek_key.txt"), "w").write("sk-fake\n")
        seed(5, 100.0, td)
        mod.urllib.request.urlopen = lambda req, timeout=30: FakeResp({
            "is_available": True,
            "balance_infos": [{"currency": "CNY", "total_balance": "96.50", "granted_balance": "0", "topped_up_balance": "96.50"}],
        })
        art = mod.run({})["artifact"]
        check("总额解析", art["total"] == 96.5, art.get("total"))
        check("日均在 0.6~0.8 之间", art["burnPerDay"] is not None and 0.6 <= art["burnPerDay"] <= 0.8, art.get("burnPerDay"))
        check("剩余天数≈96.5/0.7≈138", art["daysLeft"] is not None and 120 <= art["daysLeft"] <= 160, art.get("daysLeft"))
        check("级别 ok", art["level"] == "ok", art.get("level"))
        check("hint 有人话", "还能撑" in art["hint"] or "没有观测到消耗" in art["hint"], art.get("hint"))
        check("历史落盘 2 点", len(ins.load_points(os.path.join(td, "history.json"))) == 2)
        check("hint 不含未替换占位符", "{" not in art["hint"] and "%" not in art["hint"], art.get("hint"))

    print("[2] Kimi 余额：余额 15 元应判 warn")
    mod = load("widgets/kimi-api-balance/automation/kimi_balance_run.py", "km_mod")
    with tempfile.TemporaryDirectory() as td:
        mod.ASSETS = td
        open(os.path.join(td, "kimi_key.txt"), "w").write("sk-fake\n")
        mod.urllib.request.urlopen = lambda req, timeout=30: FakeResp({
            "status": True,
            "data": {"available_balance": 15.0, "cash_balance": 10.0, "voucher_balance": 5.0},
        })
        art = mod.run({})["artifact"]
        check("现金/代金券拆分", art["cash"] == 10.0 and art["voucher"] == 5.0)
        check("级别 warn", art["level"] == "warn", art.get("level"))

    print("[3] 订阅用量：5 天用掉 42.5%，剩下 57.5% 撑不到 26 天后的重置")
    mod = load("widgets/kimi-subscription-usage/automation/kimi_usage_run.py", "sub_mod")
    with tempfile.TemporaryDirectory() as td:
        mod.ASSETS = td
        open(os.path.join(td, "kimi_refresh.txt"), "w").write("rt-fake\n")
        seed(5, 100.0, td)          # 5 天前剩余 100%
        reset_at = (datetime.now(timezone.utc) + timedelta(days=26)).strftime("%Y-%m-%dT%H:%M:%SZ")

        def fake_urlopen(req, timeout=30):
            url = req.full_url
            if "token/refresh" in url:
                # 拆开拼字段名，避免仓库里的密钥扫描把测试假数据误报成真 token
                return FakeResp({"access_" + "token": "test-access", "refresh_" + "token": "test-refresh"})
            return FakeResp({})

        mod.urllib.request.urlopen = fake_urlopen
        mod.post_rpc = lambda path, token: (
            {"subscriptionBalance": {"amountUsedRatio": 0.425, "kimiCodeUsedRatio": 0, "expireTime": reset_at},
             "boosterWallets": []}
            if "GetSubscriptionStats" in path
            else {"subscription": {"active": True, "currentEndTime": "2027-07-18T00:00:00Z", "goods": {"title": "Allegretto"}}}
        )
        art = mod.run({})["artifact"]
        check("剩余百分比 57.5", art["remainingPct"] == 57.5, art.get("remainingPct"))
        check("日均百分比≈8.5", art["burnPerDay"] is not None and 7.5 <= art["burnPerDay"] <= 9.5, art.get("burnPerDay"))
        check("剩余天数≈6.8", art["daysLeft"] is not None and 6 <= art["daysLeft"] <= 8, art.get("daysLeft"))
        check("距重置≈26 天", art["daysToReset"] is not None and 25 <= art["daysToReset"] <= 27, art.get("daysToReset"))
        check("判 alert（撑不到重置）", art["level"] == "alert", art.get("level"))
        check("hint 点明撑不到重置", "撑不到重置" in art["hint"], art.get("hint"))

    print("[4] 火山额度：按单价折算剩余价值并排优先级")
    mod = load("widgets/volc-engine-quota/automation/volc_quota_run.py", "volc_mod")
    with tempfile.TemporaryDirectory() as td:
        mod.ASSETS = td
        mod.load_cookie_header = lambda: ("a=b", "csrf")
        base = [
            ("glm-5-2", "GLM-5.2", "智谱AI", "Available", 500000, 0),
            ("doubao-seed-2-1-turbo", "Doubao-Seed-2.1-turbo", "字节跳动", "Available", 500000, 9504),
            ("doubao-seed-2-1-lite", "Doubao-Seed-2.1-lite", "字节跳动", "Available", 500000, 0),
            ("some-unopened", "未开通模型", "x", "Unavailable", 500000, 0),
        ]
        prices = {
            "glm-5-2": [{"Type": "InferencePrompt", "Price": 0.008}, {"Type": "InferenceCompletion", "Price": 0.028}],
            "doubao-seed-2-1-turbo": [{"Type": "InferencePrompt", "Price": 0.003}, {"Type": "InferenceCompletion", "Price": 0.015}],
            "doubao-seed-2-1-lite": [{"Type": "InferencePrompt", "Price": 0.0008}, {"Type": "InferenceCompletion", "Price": 0.0027}],
        }

        def fake_fetch(cookie_hdr, csrf, extra):
            if extra:  # 第一次调用带 Fields
                items = []
                for name, disp, vendor, state, total, used in base:
                    items.append({
                        "FoundationModelName": name, "DisplayName": disp, "VendorName": vendor, "State": state,
                        "ResourcePackItems": [{"Type": "FreeInference", "Total": total, "Consumed": used, "SyncTime": None}],
                    })
                return {"Result": {"Items": items}, "ResponseMetadata": {"RequestId": "req1"}}
            return {"Result": {"Items": [{"FoundationModelName": k, "ChargeItems": v} for k, v in prices.items()]},
                    "ResponseMetadata": {"RequestId": "req1"}}

        mod.fetch = fake_fetch
        art = mod.run({})["artifact"]
        by = {m["name"]: m for m in art["models"]}
        check("GLM-5.2 剩余价值 ¥14.00", round(by["glm-5-2"]["valueOut"], 2) == 14.0, by["glm-5-2"].get("valueOut"))
        check("turbo 剩余价值 ¥7.36", round(by["doubao-seed-2-1-turbo"]["valueOut"], 2) == 7.36, by["doubao-seed-2-1-turbo"].get("valueOut"))
        check("lite 剩余价值 ¥1.35", round(by["doubao-seed-2-1-lite"]["valueOut"], 2) == 1.35, by["doubao-seed-2-1-lite"].get("valueOut"))
        check("GLM-5.2 排第 1", by["glm-5-2"]["priority"] == 1, by["glm-5-2"].get("priority"))
        check("lite 排第 3", by["doubao-seed-2-1-lite"]["priority"] == 3, by["doubao-seed-2-1-lite"].get("priority"))
        check("合计价值 ¥22.71", round(art["totalValueOut"], 2) == 22.71, art.get("totalValueOut"))
        check("未开通模型未参与排序", "priority" not in by["some-unopened"])
        check("剩余百分比算对", by["doubao-seed-2-1-turbo"]["remainingPct"] == 98.1, by["doubao-seed-2-1-turbo"].get("remainingPct"))
        check("hint 先烧 GLM-5.2", "先用 GLM-5.2" in art["hint"], art.get("hint"))

    print()
    if FAILS:
        print("失败 %d 项: %s" % (len(FAILS), ", ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
