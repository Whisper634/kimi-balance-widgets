#!/usr/bin/env python3
"""派生指标的自测（不联网、不碰凭据）。

覆盖：日均消耗计算（含充值跳变）、剩余天数外推、告警分级、
剩余价值折算与排序、历史点去重。

用法：
    python3 tools/selftest.py
退出码 0 = 全过。
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "shared"))

import insights as ins  # noqa: E402

FAILS = []


def check(name, got, want, tol=1e-6):
    ok = (abs(got - want) <= tol) if isinstance(want, (int, float)) and isinstance(got, (int, float)) else (got == want)
    print(("  ok   " if ok else "  FAIL ") + name + " => " + repr(got) + (" (want " + repr(want) + ")" if not ok else ""))
    if not ok:
        FAILS.append(name)


def points(start, values, step_hours=24):
    t0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
    return [{"t": (t0 + timedelta(hours=step_hours * i)).isoformat(), "v": v} for i, v in enumerate(values)]


def main():
    print("[1] 日均消耗")
    # 7 天从 100 掉到 90 → 每天 10/7
    rate = ins.rate_per_day(points(0, [100, 95, 90]), window_days=7)
    check("7 天掉 10 → 日均", round(rate, 6), round(10 / 2, 6))

    print("[2] 充值跳变后只用后半段")
    pts = points(0, [100, 99, 98, 150, 149])
    rate = ins.rate_per_day(pts, window_days=30)
    check("充值后 150→149 一天掉 1 → 日均 1.0", round(rate, 6), 1.0)

    print("[3] 点数不足 / 没消耗")
    check("单点 → None", ins.rate_per_day(points(0, [100])), None)
    check("在涨 → 0.0", ins.rate_per_day(points(0, [90, 95]), window_days=7), 0.0)

    print("[4] 外推")
    days, at = ins.project(96.5, 1.0, now=datetime(2026, 10, 22, tzinfo=timezone.utc))
    check("96.5 / 1.0 → 96.5 天", round(days, 6), 96.5)
    check("用完日期 = 今天 + 96.5 天", at.startswith("2027-01-26"), True)
    check("速率为 0 → 算不出", ins.project(96.5, 0)[0], None)
    check("余额已为 0 → 0 天", ins.project(0, 1.0)[0], 0.0)

    print("[5] 告警分级")
    check("¥96.5 阈值 20/10 → ok", ins.level_for_money(96.5, 20, 10), "ok")
    check("¥15 → warn", ins.level_for_money(15, 20, 10), "warn")
    check("¥8 → alert", ins.level_for_money(8, 20, 10), "alert")
    check("剩余 57.6% → ok", ins.level_for_ratio(57.6, 20, 10), "ok")
    check("剩余 15% → warn", ins.level_for_ratio(15, 20, 10), "warn")
    check("warn + alert 取最差", ins.worst("ok", "warn", "alert"), "alert")

    print("[6] 时间与文本")
    check("10-29 标签", ins.date_label("2026-10-29T01:00:00+00:00"), "10-29")
    check("天数文案", ins.day_text(6.8), "7 天")
    check("金额文案", ins.money(96.5), "¥96.50")
    check("剩余 0 文案", ins.day_text(0), "已用尽")

    print("[7] 剩余价值折算")
    # 490,496 tokens × ¥0.015/千 ≈ ¥7.36
    check("turbo 剩余价值", round(ins.tokens_value(490496, 0.015), 2), 7.36)
    check("GLM-5.2 剩余价值", round(ins.tokens_value(500000, 0.028), 2), 14.0)
    check("缺单价 → None", ins.tokens_value(500000, None), None)

    print("[8] 历史点去重 / 修剪")
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "history.json")
        t = datetime(2026, 10, 22, tzinfo=timezone.utc)
        ins.record_value(path, 100.0, t.isoformat())
        ins.record_value(path, 99.0, (t + timedelta(minutes=2)).isoformat())  # 5 分钟内 → 覆盖
        pts = json.load(open(path))
        check("5 分钟内重复观测只留一点", len(pts), 1)
        check("留下的是新值", pts[-1]["v"], 99.0)
        ins.record_value(path, 98.0, (t + timedelta(hours=4)).isoformat())
        check("超过 5 分钟则新增", len(json.load(open(path))), 2)

    print()
    if FAILS:
        print("失败 %d 项: %s" % (len(FAILS), ", ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
