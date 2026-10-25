"""共用的记账 / 外推 / 告警工具（单一来源）。

为什么要有这个文件：
  四个组件的自动化脚本都需要同一套「记历史 → 算日均消耗 → 外推用完日期 → 判级别」，
  各写一遍必然漂移。这里写成纯函数，可单独测（tools/selftest.py）。

部署注意：
  Kimi Work 的每个自动化只上传自己那个目录，不能跨目录 import，
  所以本文件会被 tools/sync_shared.py 复制成 widgets/*/automation/insights.py。
  改这里之后一定要跑一次 sync，否则线上还是旧逻辑。

历史文件格式（放各组件 assets/history.json，已被 .gitignore 忽略）：
  [{"t": "2026-10-22T05:00:00+00:00", "v": 96.5}, ...]
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

MAX_POINTS = 500      # 历史点上限（4 小时一次 ≈ 83 天）
KEEP_DAYS = 30        # 超过这个天数的点丢弃
MIN_SPAN_DAYS = 0.1   # 两点间隔太短算不准日均就放弃（0.1 天 = 2.4h，容得下 4h 一次的刷新）
RECHARGE_JUMP = 1.02  # 值上涨超过 2% 视为充值/重置，之前的历史不再参与斜率

DEFAULTS = {
    "balanceWarn": 20.0,    # 余额 ≤ 该值 → warn
    "balanceAlert": 10.0,   # 余额 ≤ 该值 → alert
    "quotaWarnPct": 20.0,   # 额度剩余 ≤ 该百分比 → warn
    "quotaAlertPct": 10.0,  # 额度剩余 ≤ 该百分比 → alert
    "tokensWarn": 100000,   # 单个模型剩余 tokens ≤ 该值 → warn
    "windowDays": 7,        # 算日均消耗的窗口（天）
}

LEVEL_ORDER = {"ok": 0, "warn": 1, "alert": 2}


# ---------------------------------------------------------------- 时间 / 数值

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(value):
    """把 ISO 时间串 / datetime / None 统一成带时区的 datetime（解析失败返回 None）。"""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    s = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def days_between(a, b) -> float:
    """b - a，单位天；任一解析失败返回 0。"""
    da, db = parse_ts(a), parse_ts(b)
    if not da or not db:
        return 0.0
    return (db - da).total_seconds() / 86400.0


def date_label(value, tz_hours: int = 8) -> str:
    """把时间串渲染成 '10-29'（默认按北京时间）。"""
    dt = parse_ts(value)
    if not dt:
        return "—"
    return (dt + timedelta(hours=tz_hours)).strftime("%m-%d")


def money(value, digits: int = 2) -> str:
    if value is None:
        return "—"
    return "¥{:,.{d}f}".format(float(value), d=digits)


def day_text(days) -> str:
    """把剩余天数渲染成人话（超过 999 天一律显示 999+，避免荒谬数字）。"""
    if days is None:
        return "算不出速率"
    if days <= 0:
        return "已用尽"
    if days < 1:
        return "不到 1 天"
    if days > 999:
        return "999+ 天"
    return "%d 天" % int(round(days))


# ---------------------------------------------------------------- 阈值 / 级别

def load_thresholds(assets_dir: str) -> dict:
    """读 assets/thresholds.json（可选），与 DEFAULTS 合并。坏文件不影响主流程。"""
    cfg = dict(DEFAULTS)
    path = os.path.join(assets_dir, "thresholds.json")
    try:
        with open(path, encoding="utf-8") as f:
            user = json.load(f)
        if isinstance(user, dict):
            for k, v in user.items():
                if k in DEFAULTS and isinstance(v, (int, float)):
                    cfg[k] = float(v)
    except FileNotFoundError:
        pass
    except Exception:
        pass
    return cfg


def level_for_money(amount, warn: float, alert: float) -> str:
    if amount is None:
        return "ok"
    if float(amount) <= float(alert):
        return "alert"
    if float(amount) <= float(warn):
        return "warn"
    return "ok"


def level_for_ratio(remain_pct, warn: float, alert: float) -> str:
    if remain_pct is None:
        return "ok"
    if float(remain_pct) <= float(alert):
        return "alert"
    if float(remain_pct) <= float(warn):
        return "warn"
    return "ok"


def worst(*levels) -> str:
    result = "ok"
    for lv in levels:
        if LEVEL_ORDER.get(lv, 0) > LEVEL_ORDER.get(result, 0):
            result = lv
    return result


# ---------------------------------------------------------------- 历史 / 斜率

def load_points(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [p for p in data if isinstance(p, dict) and "t" in p and "v" in p]
    except Exception:
        pass
    return []


def save_points(path: str, points) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(points, f, ensure_ascii=False)
    os.replace(tmp, path)


def record_value(path: str, value, ts=None, keep_days: int = KEEP_DAYS):
    """追加一个观测点并返回完整历史（按时间升序）。

    同一次运行里重复调用（比如脚本重试）不会产生重复点：距最后一点 <5 分钟就覆盖它。
    """
    points = load_points(path)
    t = parse_ts(ts) or now_utc()
    try:
        v = float(value)
    except (TypeError, ValueError):
        return points
    if points and days_between(points[-1]["t"], t) * 86400.0 < 300:
        points[-1] = {"t": t.isoformat(), "v": v}
    else:
        points.append({"t": t.isoformat(), "v": v})
    cutoff = t - timedelta(days=keep_days)
    points = [p for p in points if (parse_ts(p["t"]) or cutoff) >= cutoff]
    points = points[-MAX_POINTS:]
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        save_points(path, points)
    except Exception:
        pass
    return points


def rate_per_day(points, window_days: float = 7):
    """近 window_days 天的日均消耗（正数 = 平均每天掉了多少）。

    规则：
      - 只取窗口内的点；少于 2 点或跨度 < MIN_SPAN_DAYS 天 → 返回 None（外推会不可信）
      - 值明显上涨（充值 / 额度重置）时，只用上涨之后的那段，避免把充值算成负消耗
      - 算出来 ≤ 0（在涨或没动）→ 返回 0.0，表示"近期没在消耗"
    """
    pts = sorted(
        [p for p in points if parse_ts(p.get("t"))],
        key=lambda p: parse_ts(p["t"]),
    )
    if len(pts) < 2:
        return None
    last_t = parse_ts(pts[-1]["t"])
    cutoff = last_t - timedelta(days=float(window_days))
    window = [p for p in pts if parse_ts(p["t"]) >= cutoff]
    if len(window) < 2:
        window = pts[-2:]

    start = 0
    for i in range(1, len(window)):
        prev = float(window[i - 1]["v"])
        cur = float(window[i]["v"])
        if cur > prev * RECHARGE_JUMP:
            start = i
    jumped = start > 0
    window = window[start:]
    if len(window) < 2:
        # 只在充值之后还有一个点 → 不知道增速；若刚充过值，按"近期没消耗"处理
        return 0.0 if jumped else None

    span = days_between(window[0]["t"], window[-1]["t"])
    if span < MIN_SPAN_DAYS:
        return None
    drop = float(window[0]["v"]) - float(window[-1]["v"])
    if drop <= 0:
        return 0.0
    return drop / span


def project(value, rate, now=None):
    """按日均速率外推：(还剩几天, 预计用完时间 ISO)。

    速率为 None / 0 / 未知，或当前值 ≤ 0 → 天数给 None 或 0，时间给 None。
    """
    if value is None:
        return None, None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None, None
    if v <= 0:
        return 0.0, (now or now_utc()).isoformat()
    if not rate or rate <= 0:
        return None, None
    days = v / float(rate)
    at = (now or now_utc()) + timedelta(days=days)
    return days, at.isoformat()


def tokens_value(remaining_tokens, price_per_1k):
    """剩余 tokens 按某档单价折算成人民币；缺单价返回 None。

    火山引擎价格接口给的是「元 / 千 tokens」（与控制台一致），所以除以 1000 再乘单价。
    """
    if remaining_tokens is None or price_per_1k is None:
        return None
    try:
        return float(remaining_tokens) / 1000.0 * float(price_per_1k)
    except (TypeError, ValueError):
        return None

def previous_reset(reset_at):
    """上一个重置时刻：按"每月同一天"倒推；目标月没有这一天就取月末。"""
    d = parse_ts(reset_at)
    if not d:
        return None
    import calendar
    y, m, day = d.year, d.month, d.day
    pm_y, pm_m = (y, m - 1) if m > 1 else (y - 1, 12)
    last_day = calendar.monthrange(pm_y, pm_m)[1]
    prev = d.replace(year=pm_y, month=pm_m, day=min(day, last_day))
    return prev


def cycle_rate(reset_at, used_pct, now=None):
    """订阅额度的「本周期日均」：周期起点额度=100%，所以日均 = 已用百分点 / 周期已过天数。

    只看最近两个历史点会把速率算小一个数量级（跨度可能只有几小时），
    周期基线才是对的。返回 (日均, 周期已过天数) 或 (None, None)。
    """
    prev = previous_reset(reset_at)
    if prev is None or used_pct is None:
        return None, None
    now_dt = parse_ts(now) or now_utc()
    days = (now_dt - prev).total_seconds() / 86400.0
    if days <= 0.5:
        return None, None
    return float(used_pct) / days, days

