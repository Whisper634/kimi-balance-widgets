#!/usr/bin/env python3
"""把 shared/insights.py 同步到每个组件的 automation/ 目录。

Kimi Work 的自动化只上传各自目录，跨目录 import 会在线上失败，
所以每个组件必须带一份拷贝。这里保证四份拷贝与单一来源完全一致。

用法：
    python3 tools/sync_shared.py           # 同步
    python3 tools/sync_shared.py --check   # 只检查，不一致则退出码 1（给 CI / 发版前用）
"""
import argparse
import filecmp
import glob
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "shared", "insights.py")
TARGETS = sorted(glob.glob(os.path.join(ROOT, "widgets", "*", "automation")))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只检查不写入")
    args = ap.parse_args()

    if not os.path.exists(SRC):
        print("找不到单一来源: %s" % SRC, file=sys.stderr)
        return 2
    if not TARGETS:
        print("没有找到任何 widgets/*/automation 目录", file=sys.stderr)
        return 2

    drift = []
    for target in TARGETS:
        dst = os.path.join(target, "insights.py")
        same = os.path.exists(dst) and filecmp.cmp(SRC, dst, shallow=False)
        rel = os.path.relpath(dst, ROOT)
        if same:
            print("一致  %s" % rel)
            continue
        if args.check:
            print("不一致 %s" % rel)
            drift.append(rel)
        else:
            shutil.copyfile(SRC, dst)
            print("已同步 %s" % rel)

    if args.check and drift:
        print("\n有 %d 份拷贝落后于 shared/insights.py，先跑 python3 tools/sync_shared.py" % len(drift), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
