# -*- coding: utf-8 -*-
"""out_all20061007 (flat: 图片 + 同名 .txt sidecar) -> Ultralytics 标准四目录结构。

为什么要这一步
--------------
out_all20061007 是**扁平**目录：wxsyn_00000.jpg 与 wxsyn_00000.txt 同处一层。
Ultralytics 的训练器不认识这种布局 —— 它靠「镜像替换」从图片路径推导标签路径：
    .../images/train/x.jpg  ->  .../labels/train/x.txt
它**不会**去同目录找同名 .txt。所以必须落成：

    splits_all20061007/
        images/train/*.jpg   labels/train/*.txt
        images/val/*.jpg     labels/val/*.txt

划分规则
--------
1) 按前缀分组（wxsyn_* / shot_20261007_*），**组内** 90/10 随机抽 val。
   ── 不用全量随机：wxsyn 有 1000 张，全量随机会让 val 在序号轴上与 train 大量交错；
      组内抽则 val 覆盖所有页面类型，同时保持各页面的比例。

2) shot_20261007_* （10 张真实企微截图）**进 train**（按用户要求）。
   ── 这 10 张是唯一的真实域样本；放 train 是为了让模型见到真实渲染管线的纹理/抗锯齿/
      字体边缘，缓解「合成域过拟合」。代价：val 全是合成图，指标会比真实场景乐观，
      所以**真实截图的效果必须靠训练后单独跑推理来验**，不能只看 val mAP。

3) 划分后逐类统计 train/val 框数，val 缺类的类直接告警（缺类算不出 AP）。

用法：
    python split_all20061007.py
    python split_all20061007.py --force     # 输出目录已存在时覆盖
"""

import argparse
import glob
import os
import random
import shutil
import sys
from collections import Counter, defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "out_all20061007")
DST = os.path.join(BASE, "splits_all20061007")
CLASSES = os.path.join(BASE, "classes.txt")
VAL_RATIO = 0.10
SEED = 0

# 这些前缀的图**强制进 train**（真实域样本，留作训练以缓解合成域过拟合）
FORCE_TRAIN_PREFIXES = ("shot_",)


def stem_of(path):
    return os.path.basename(path).rsplit(".", 1)[0]


def group_of(stem):
    """wxsyn_00000 -> wxsyn ; shot_20261007_192649 -> shot_20261007"""
    return stem.rsplit("_", 1)[0]


def main():
    ap = argparse.ArgumentParser(description="out_all20061007 -> splits_all20061007 四目录结构")
    ap.add_argument("--val-ratio", type=float, default=VAL_RATIO)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--force", action="store_true", help="输出目录非空时也继续")
    args = ap.parse_args()

    names = [l.strip() for l in open(CLASSES, encoding="utf-8") if l.strip()]
    if len(names) != 13:
        sys.exit(f"[错误] {CLASSES} 应为 13 类，实际 {len(names)} 类")

    # ---------- 1. 收集图片（jpg + png），要求有同名 .txt ----------
    items = []  # (stem, img_path, lbl_path)
    skipped = []
    for pat in ("*.jpg", "*.jpeg", "*.png"):
        for ip in sorted(glob.glob(os.path.join(SRC, pat))):
            stem = stem_of(ip)
            lp = os.path.join(SRC, stem + ".txt")
            if not os.path.exists(lp):
                skipped.append(os.path.basename(ip))
                continue
            items.append((stem, ip, lp))

    if not items:
        sys.exit(f"[错误] {SRC} 下没有找到 任何 图片+同名txt 配对")
    if skipped:
        print(f"[警告] {len(skipped)} 张图无同名标签，已跳过: {skipped[:5]}{' ...' if len(skipped) > 5 else ''}")
    print(f"[1/5] 收集到 {len(items)} 张 图+标签 配对")

    # ---------- 2. 校验标签格式 ----------
    bad = []
    for stem, ip, lp in items:
        for ln, line in enumerate(open(lp, encoding="utf-8"), 1):
            p = line.split()
            if not p:
                continue
            if len(p) != 5:
                bad.append((stem, ln, "列数非5")); continue
            try:
                c = int(float(p[0]))
                vals = [float(v) for v in p[1:]]
            except ValueError:
                bad.append((stem, ln, "非数值")); continue
            if not (0 <= c < len(names)):
                bad.append((stem, ln, f"类别越界 {c}"))
            elif any(v < 0 or v > 1 for v in vals):
                bad.append((stem, ln, f"坐标越界 {vals}"))
    if bad:
        print(f"[2/5] ✗ 标签校验发现 {len(bad)} 处问题，前 5 条:")
        for b in bad[:5]:
            print(f"        {b}")
        sys.exit("[错误] 标签格式有问题，先修数据再划分")
    print(f"[2/5] 标签校验通过（13 类，坐标均在 0-1）")

    # ---------- 3. 分组 + 组内抽 val ----------
    groups = defaultdict(list)
    for stem, ip, lp in items:
        groups[group_of(stem)].append((stem, ip, lp))

    rng = random.Random(args.seed)
    split_of = {}
    plan = []
    for g in sorted(groups):
        gl = sorted(groups[g], key=lambda x: x[0])
        n = len(gl)
        if g.startswith(FORCE_TRAIN_PREFIXES):
            for stem, _, _ in gl:
                split_of[stem] = "train"
            plan.append((g, n, 0, "强制进 train（真实域）"))
            continue
        idx = list(range(n))
        rng.shuffle(idx)
        nv = max(1, round(n * args.val_ratio)) if n >= 2 else 0
        val_idx = set(idx[:nv])
        for i, (stem, _, _) in enumerate(gl):
            split_of[stem] = "val" if i in val_idx else "train"
        plan.append((g, n, nv, "组内随机"))

    n_train = sum(1 for v in split_of.values() if v == "train")
    n_val = sum(1 for v in split_of.values() if v == "val")
    print(f"[3/5] 划分完成: train {n_train} / val {n_val}  （val 占比 {n_val/len(items):.1%}）")
    print(f"      {'前缀':<20}{'总数':>6}{'val':>6}   方式")
    for g, tot, nv, how in plan:
        print(f"      {g:<20}{tot:>6}{nv:>6}   {how}")

    # ---------- 4. 类别覆盖校验 ----------
    hist = {"train": Counter(), "val": Counter()}
    nbox = {"train": 0, "val": 0}
    for stem, ip, lp in items:
        sp = split_of[stem]
        for line in open(lp, encoding="utf-8"):
            p = line.split()
            if not p:
                continue
            hist[sp][int(float(p[0]))] += 1
            nbox[sp] += 1

    print(f"[4/5] 类别覆盖（框数）")
    print(f"      {'id':>3} {'类别':<22}{'train':>7}{'val':>6}")
    missing = []
    for i, nm in enumerate(names):
        print(f"      {i:>3} {nm:<22}{hist['train'][i]:>7}{hist['val'][i]:>6}")
        if hist["val"][i] == 0:
            missing.append(f"{i} {nm}")
    if missing:
        print(f"      ⚠ val 缺这些类，其 AP 无法评估: {', '.join(missing)}")
    else:
        print(f"      ✓ val 13 类全覆盖")

    # ---------- 5. 落盘四目录 ----------
    if os.path.exists(DST) and any(os.scandir(DST)) and not args.force:
        sys.exit(f"\n[错误] 输出目录非空: {DST}\n  加 --force 覆盖，或先手动删除")

    for split in ("train", "val"):
        for sub in ("images", "labels"):
            os.makedirs(os.path.join(DST, split, sub), exist_ok=True)

    for stem, ip, lp in items:
        sp = split_of[stem]
        ext = os.path.splitext(ip)[1]
        shutil.copy2(ip, os.path.join(DST, sp, "images", stem + ext))
        shutil.copy2(lp, os.path.join(DST, sp, "labels", stem + ".txt"))

    print(f"\n[5/5] 完成 → {DST}")
    for split in ("train", "val"):
        ni = len(os.listdir(os.path.join(DST, split, "images")))
        nl = len(os.listdir(os.path.join(DST, split, "labels")))
        flag = "✓" if ni == nl else "✗ 数量不等！"
        print(f"      {split:<6} images {ni:>4} 张 / labels {nl:>4} 个  {flag}")

    # 同时写一份 data yaml，绝对路径避免 Windows 下相对路径解析歧义
    yaml_path = os.path.join(DST, "data_all20061007.yaml")
    with open(yaml_path, "w", encoding="utf-8") as f:
        f.write("# 由 split_all20061007.py 自动生成，请勿手改\n")
        f.write(f"# 源: {SRC}（扁平 sidecar）\n")
        f.write(f"# train {n_train} 张（含 shot_* 真实截图） / val {n_val} 张\n")
        f.write(f"# boxes: train {nbox['train']} / val {nbox['val']}\n")
        f.write(f"path: {DST}\n")
        f.write("train: train/images\n")
        f.write("val: val/images\n")
        f.write("nc: 13\nnames:\n")
        for i, nm in enumerate(names):
            f.write(f"  {i}: {nm}\n")
    print(f"      data yaml → {yaml_path}")


if __name__ == "__main__":
    main()
