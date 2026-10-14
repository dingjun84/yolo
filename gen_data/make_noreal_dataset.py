# -*- coding: utf-8 -*-
"""构建「对照实验 A」数据集：train 只含合成图（无真实截图），val 与 B 完全一致。

为什么要单独做这一步
--------------------
要量化「训练时见过真实样本 vs 没见过」的差距，唯一干净的做法是训两个模型、
保证**除 train 是否含真实图之外所有变量一致**：

    模型 B（已训）: train = 900 合成 + 10 真实   val = 100 合成
    模型 A（本脚本）: train = 900 合成 (无真实)   val = 100 合成   ← val 必须与 B 字节一致

关键约束：val **不重新抽样**，直接复用 B 的 val 目录（同一批文件）。
若重新抽，两个模型的 early-stopping 选点标准就不同，comparison 不成立。

真实截图（shot_*）在 A 里**彻底不参与训练**，只作为两个模型共同的最终测试集，
所以它们不能出现在 A 的 train 或 val 中，否则又是泄漏。

产物：
    gen_data/splits_all20061007_noreal/
        images/train  900 张（纯合成）
        labels/train  900 个
        images/val    100 张（从 B 复制，字节一致）
        labels/val    100 个
        data_all20061007_noreal.yaml
"""

import os, shutil, sys, filecmp
from collections import Counter

BASE = os.path.dirname(os.path.abspath(__file__))
B_ROOT = os.path.join(BASE, "splits_all20061007")
A_ROOT = os.path.join(BASE, "splits_all20061007_noreal")
CLASSES = os.path.join(BASE, "classes.txt")


def main():
    if not os.path.isdir(B_ROOT):
        sys.exit(f"[错误] 找不到 B 数据集: {B_ROOT}")
    if os.path.exists(A_ROOT) and any(os.scandir(A_ROOT)):
        sys.exit(f"[错误] 输出目录已存在且非空: {A_ROOT}\n  先手动删除再跑")

    names = [l.strip() for l in open(CLASSES, encoding="utf-8") if l.strip()]
    assert len(names) == 13, f"classes.txt 应为 13 类，实际 {len(names)}"

    for split in ("train", "val"):
        for sub in ("images", "labels"):
            os.makedirs(os.path.join(A_ROOT, split, sub), exist_ok=True)

    # ---------- val：直接从 B 逐个复制，保证字节一致 ----------
    b_val_img = os.path.join(B_ROOT, "val", "images")
    val_files = sorted(os.listdir(b_val_img))
    for fn in val_files:
        stem = os.path.splitext(fn)[0]
        shutil.copy2(os.path.join(b_val_img, fn),
                     os.path.join(A_ROOT, "val", "images", fn))
        shutil.copy2(os.path.join(B_ROOT, "val", "labels", stem + ".txt"),
                     os.path.join(A_ROOT, "val", "labels", stem + ".txt"))
    print(f"[val] 从 B 复制 {len(val_files)} 张（字节一致，不重抽）")

    # ---------- train：从 B 的 train 中剔除真实截图（shot_*）----------
    b_tr_img = os.path.join(B_ROOT, "train", "images")
    n_syn, n_dropped = 0, []
    for fn in sorted(os.listdir(b_tr_img)):
        stem = os.path.splitext(fn)[0]
        if stem.startswith("shot_"):          # 真实截图排除
            n_dropped.append(stem)
            continue
        shutil.copy2(os.path.join(b_tr_img, fn),
                     os.path.join(A_ROOT, "train", "images", fn))
        shutil.copy2(os.path.join(B_ROOT, "train", "labels", stem + ".txt"),
                     os.path.join(A_ROOT, "train", "labels", stem + ".txt"))
        n_syn += 1
    print(f"[train] 合成图 {n_syn} 张；剔除真实截图 {len(n_dropped)} 张: {n_dropped}")

    # ---------- 校验：A.val 必须与 B.val 逐文件一致 ----------
    a_val = sorted(os.listdir(os.path.join(A_ROOT, "val", "images")))
    if a_val != sorted(val_files):
        sys.exit("[错误] A.val 与 B.val 文件列表不一致，对照实验无效")
    mismatch = [f for f in a_val
                if not filecmp.cmp(os.path.join(A_ROOT, "val", "images", f),
                                   os.path.join(b_val_img, f), shallow=False)]
    if mismatch:
        sys.exit(f"[错误] A.val 与 B.val 内容不一致: {mismatch}")
    print(f"[校验] ✓ A.val 与 B.val {len(a_val)} 个文件逐字节一致")

    # ---------- 校验：A.train 不得残留任何真实截图 ----------
    leak = [f for f in os.listdir(os.path.join(A_ROOT, "train", "images"))
            if f.startswith("shot_")]
    if leak:
        sys.exit(f"[错误] A.train 仍残留真实截图: {leak}")
    print(f"[校验] ✓ A.train 无真实截图泄漏")

    # ---------- 类别覆盖 ----------
    hist = Counter()
    nbox = 0
    for fn in os.listdir(os.path.join(A_ROOT, "train", "labels")):
        for line in open(os.path.join(A_ROOT, "train", "labels", fn), encoding="utf-8"):
            p = line.split()
            if p:
                hist[int(float(p[0]))] += 1
                nbox += 1
    print(f"[覆盖] A.train 框数 {nbox}，13 类全有: {sorted(hist) == list(range(13))}")
    missing = [f"{i} {names[i]}" for i in range(13) if hist[i] == 0]
    print(f"        缺失: {missing if missing else '无'}")

    # ---------- 写 yaml ----------
    yaml_path = os.path.join(A_ROOT, "data_all20061007_noreal.yaml")
    with open(yaml_path, "w", encoding="utf-8") as f:
        f.write("# 对照实验 A：train 仅合成图（无真实截图），val 与 B 字节一致\n")
        f.write("# 由 make_noreal_dataset.py 自动生成，请勿手改\n")
        f.write(f"# train {n_syn} 张 / val {len(val_files)} 张\n")
        f.write(f"# 对比对象: gen_data/splits_all20061007 (train 含 10 张真实截图)\n")
        f.write(f"path: {A_ROOT}\n")
        f.write("train: train/images\nval: val/images\nnc: 13\nnames:\n")
        for i, nm in enumerate(names):
            f.write(f"  {i}: {nm}\n")

    print(f"\n完成 → {A_ROOT}")
    print(f"  data yaml → {yaml_path}")
    print(f"  A: train {n_syn} (纯合成) / val {len(val_files)}")
    print(f"  B: train 910 (合成+真实) / val {len(val_files)}   ← val 完全相同")


if __name__ == "__main__":
    main()
