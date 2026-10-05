#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
微信 UI 数据集划分脚本 —— 把两个扁平目录合并成 Ultralytics 标准结构。

输入（**只读**，本脚本绝不修改这两个目录）:
    chat_dataset/     个人微信截图   62 张
    wxwork_dataset/   企业微信截图   20 张
    每张 image.png 配一个同名 image.txt（YOLO 格式: cls cx cy w h，后四项已归一化到 0-1）

输出:
    datasets/wechat_ui/images/{train,val}/*.png
    datasets/wechat_ui/labels/{train,val}/*.txt

--------------------------------------------------------------------------
划分规则（三条，每条都有具体理由，不是随手定的）
--------------------------------------------------------------------------

1) 相似图强制同侧
   用 dhash 感知哈希算任意两张图的 hamming 距离，<= SIM_THRESH 的图对用并查集
   合并成「不可分割单元」，整个单元一起进 train 或一起进 val。
   理由：同一窗口的连续滚动帧，画面高度重叠。若一张进 train、一张进 val，
        val 等于在考 train 的原题，mAP 会虚高 —— 这是小数据集最常见的自欺。

2) 按文件名前缀分组，组内从**末尾**取连续段
   前缀反映采集批次（contact_ / one_chat_ / group_chat_ / wxwork_chat_ ...）。
   组内按序号升序排，从末尾取 round(n * VAL_RATIO) 张进 val。
   理由：为什么不随机抽样？随机抽样会让 val 与 train 在序号轴上大量交错，
        交界处相邻帧的泄露对数成倍增加（n 张图随机抽，交界点有 ~2n 个）。
        取「末尾连续段」时，交界点只有 1 个，泄露降到最低。

3) 划分后校验类别覆盖
   val 若缺某个类，该类在验证集上算不出 AP。脚本会直接告警并列出。

--------------------------------------------------------------------------
用法
--------------------------------------------------------------------------
    # 合并版（个人微信 + 企业微信）
    python prepare_dataset.py --yaml data.yaml

    # 企微专版（只吃 wxwork_dataset）
    python prepare_dataset.py --src wxwork_dataset --out datasets/wxwork_ui \
        --yaml data_wxwork.yaml

    python prepare_dataset.py --val-ratio 0.25
    python prepare_dataset.py --out datasets/wechat_ui --force    # 覆盖已有输出
"""

import argparse
import glob
import os
import re
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

# 类别表（14 类，0-13，与 classes.txt / server.py 一致，顺序不可改）
CLASSES = [
    "self_avatar",
    "nav_chat_icon",
    "nav_contacts_icon",
    "search_bar",
    "contact_item",
    "send_button",
    "conversation_item",
    "incoming_bubble",
    "outgoing_bubble",
    "input_bar",
    "single_chat",
    "group_chat",
    "contact_send_message",
    "nav_groups_icon",
]


# --------------------------------------------------------------------------
# 工具函数
# --------------------------------------------------------------------------
def dhash(path, size=16):
    """差值哈希：转灰度 → 缩到 (size+1, size) → 比较横向相邻像素的明暗。

    返回 bool 数组（长度 size*size）。两张图 hamming 距离越小越像。
    这里不用像素级比对，是因为 dhash 对亮度/轻微位移不敏感，
    能抓住「整体结构相同」，正好用来识别同一窗口的滚动帧。
    """
    with Image.open(path) as im:
        g = im.convert("L").resize((size + 1, size), Image.LANCZOS)
    a = np.asarray(g, dtype=np.int16)
    return (a[:, 1:] > a[:, :-1]).flatten()


def prefix_of(name):
    """从文件名提取「采集批次」前缀。

    contact_10 -> contact      group_chat1 -> group_chat
    group_chat_3 -> group_chat wxwork_chat_10 -> wxwork_chat
    wxwork_contact（无数字）-> wxwork_contact
    """
    m = re.match(r"^([A-Za-z_]+?)(\d+)$", name)
    return m.group(1).rstrip("_") if m else name


def num_of(name):
    """提取文件名末尾的序号，用于组内排序。没有序号返回 -1。"""
    m = re.search(r"(\d+)$", name)
    return int(m.group(1)) if m else -1


def write_data_yaml(yaml_path, data_root, counts, src_dirs):
    """生成 data.yaml。

    为什么不手工写：现在项目里有多份数据集（合并版 wechat_ui、企微专版 wxwork_ui），
    类别表和划分张数一旦手工维护就会漂移 —— 改了脚本忘记改 yaml 是最隐蔽的错误。
    让脚本和数据集产物同源生成，可以彻底消除这类不一致。
    """
    import yaml

    cfg = {
        "path": str(data_root),
        "train": "images/train",
        "val": "images/val",
        "nc": len(CLASSES),
        "names": {i: n for i, n in enumerate(CLASSES)},
    }
    header = f"""# 微信 UI 元素检测数据集
#
# 本文件由 prepare_dataset.py 自动生成，请勿手工编辑 ——
# 改划分或改类别请改脚本后重跑，否则会与实际文件结构不一致。
#
# 源目录（只读，脚本从未修改过它们）: {', '.join(src_dirs)}
# 本次划分: train {counts['train']} 张 / val {counts['val']} 张
#   —— 划分带「相似图强制同侧」约束：同一窗口的连续滚动帧一定落在同一侧，
#      否则 val 等于在考 train 的原题，验证指标会虚高。
#
# 类别编号 0-{len(CLASSES)-1} 与各源数据集的既有标注严格对应，顺序不可调整
# （调整会让所有标签文件的 cls 列失效）。

"""
    Path(yaml_path).parent.mkdir(parents=True, exist_ok=True)
    with open(yaml_path, "w", encoding="utf-8") as f:
        f.write(header)
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
    return Path(yaml_path)


def read_labels(lbl_path):
    """读 YOLO 标签，返回 [(cls, cx, cy, w, h), ...]。顺手做一次格式校验。"""
    out = []
    with open(lbl_path) as f:
        for lineno, line in enumerate(f, 1):
            s = line.split()
            if not s:
                continue
            if len(s) != 5:
                raise ValueError(f"{lbl_path}:{lineno} 列数应为 5，实际 {len(s)}")
            c = int(float(s[0]))
            x, y, w, h = map(float, s[1:5])
            if not (0 <= c < len(CLASSES)):
                raise ValueError(f"{lbl_path}:{lineno} 类别 {c} 越界 (0-{len(CLASSES)-1})")
            if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1):
                raise ValueError(f"{lbl_path}:{lineno} 坐标越界: {s[1:5]}")
            out.append((c, x, y, w, h))
    return out


class DSU:
    """并查集：把「必须待在同一侧」的图合并成一个单元。"""

    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]  # 路径压缩
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description="把 chat_dataset / wxwork_dataset 合并划分为 Ultralytics 数据集结构",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--src", nargs="+", default=["chat_dataset", "wxwork_dataset"],
                    help="源目录（扁平结构，png + 同名 txt）")
    ap.add_argument("--out", default="datasets/wechat_ui", help="输出根目录")
    ap.add_argument("--val-ratio", type=float, default=0.2, help="验证集比例")
    ap.add_argument("--sim-thresh", type=int, default=12,
                    help="dhash hamming 距离阈值，<= 该值视为相似图，强制同侧")
    ap.add_argument("--yaml", default=None, metavar="PATH",
                    help="同时把 data.yaml 写到该路径（如 data_wxwork.yaml）；不给则不生成")
    ap.add_argument("--keep-empty", action="store_true",
                    help="保留空标签文件。默认**排除**：UI 截图里空标签几乎必然是漏标，"
                         "留着会被当成背景负样本，等于教模型「这一页什么都没有」")
    ap.add_argument("--force", action="store_true", help="输出目录非空时也继续（会覆盖同名文件）")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent
    out_root = (root / args.out).resolve() if not os.path.isabs(args.out) else Path(args.out)

    # ---------- 1. 收集文件 ----------
    items = []  # [(name, img_path, lbl_path)]
    for d in args.src:
        dpath = (root / d) if not os.path.isabs(d) else Path(d)
        if not dpath.is_dir():
            sys.exit(f"[错误] 源目录不存在: {dpath}")
        for ip in sorted(glob.glob(str(dpath / "*.png"))):
            name = os.path.basename(ip)[:-4]
            lp = ip[:-4] + ".txt"
            if not os.path.exists(lp):
                print(f"  [跳过] 有图无标签: {os.path.basename(ip)}")
                continue
            items.append((name, ip, lp))

    if not items:
        sys.exit("[错误] 没有找到任何 png+txt 配对")

    dup = [n for n, c in Counter(x[0] for x in items).items() if c > 1]
    if dup:
        sys.exit(f"[错误] 存在重名文件，无法合并: {dup}")

    print(f"[1/5] 收集到 {len(items)} 张图")

    # ---------- 2. 读标签 ----------
    try:
        labels = [read_labels(it[2]) for it in items]
    except ValueError as e:
        sys.exit(f"[错误] 标签格式校验失败:\n  {e}")
    empty = [items[i][0] for i, lb in enumerate(labels) if not lb]
    print(f"[2/5] 标签校验通过；空标签 {len(empty)} 个 {empty if empty else ''}")
    if empty:
        if args.keep_empty:
            print("      ⚠ 按 --keep-empty 保留 → 它们会被当成「纯背景负样本」")
            print("        若原图其实有 UI 元素，那就是漏标，会直接毒化训练")
        else:
            print("      ✗ 已自动排除（UI 截图里空标签几乎必然是漏标，不是负样本）")
            print("        → 补标后重跑本脚本即可恢复；确属纯背景图请显式加 --keep-empty")
            keep = [i for i, lb in enumerate(labels) if lb]
            items = [items[i] for i in keep]
            labels = [labels[i] for i in keep]
            print(f"        排除后剩余 {len(items)} 张")

    # ---------- 3. 相似图检测 + 并查集 ----------
    print(f"[3/5] 计算 dhash 相似度（阈值 hamming <= {args.sim_thresh}）...")
    hashes = [dhash(it[1]) for it in items]
    dsu = DSU(len(items))
    similar_pairs = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            h = int(np.count_nonzero(hashes[i] != hashes[j]))
            if h <= args.sim_thresh:
                dsu.union(i, j)
                similar_pairs.append((h, items[i][0], items[j][0]))
    similar_pairs.sort()
    if similar_pairs:
        print(f"      发现 {len(similar_pairs)} 对相似图（会被强制分到同一侧）:")
        for h, a, b in similar_pairs:
            print(f"        hamming={h:3d}  {a}  <->  {b}")
    else:
        print("      未发现相似图对")

    # ---------- 4. 按前缀分组 + 组内末尾取 val ----------
    units = defaultdict(list)  # 并查集根 -> [索引]
    for i in range(len(items)):
        units[dsu.find(i)].append(i)

    by_prefix = defaultdict(list)  # 前缀 -> [(root, [索引])]
    for r, idxs in units.items():
        pfxs = sorted({prefix_of(items[i][0]) for i in idxs})
        if len(pfxs) > 1:
            print(f"      ⚠ 跨前缀的相似单元 {pfxs}，按 {pfxs[0]} 归类")
        by_prefix[pfxs[0]].append((r, idxs))

    train_idx, val_idx = set(), set()
    plan = []
    for pfx, unit_list in sorted(by_prefix.items()):
        # 单元按「单元内最小序号」升序
        unit_list.sort(key=lambda u: min(num_of(items[i][0]) for i in u[1]))
        total = sum(len(u[1]) for u in unit_list)
        quota = round(total * args.val_ratio)
        picked, taken = [], 0
        for r, idxs in reversed(unit_list):          # 从末尾往前取连续段
            if taken > 0 and taken + len(idxs) > quota:
                break
            picked.append(r)
            taken += len(idxs)
        n_val = 0
        for r, idxs in unit_list:
            if r in picked:
                val_idx.update(idxs); n_val += len(idxs)
            else:
                train_idx.update(idxs)
        plan.append((pfx, total, n_val))

    print(f"[4/5] 划分完成: train={len(train_idx)}  val={len(val_idx)} "
          f"(val 占比 {len(val_idx)/len(items):.1%})")
    print(f"      {'前缀':<16}{'总数':>6}{'val':>6}")
    for pfx, total, n_val in plan:
        print(f"      {pfx:<16}{total:>6}{n_val:>6}")

    # ---------- 5. 类别覆盖校验 ----------
    def cls_stat(idxs):
        c = Counter()
        for i in idxs:
            for lb in labels[i]:
                c[lb[0]] += 1
        return c

    tr_c, va_c = cls_stat(train_idx), cls_stat(val_idx)
    print(f"[5/5] 类别覆盖检查")
    print(f"      {'id':>3} {'类别':<20}{'train':>7}{'val':>6}")
    missing = []
    for k, name in enumerate(CLASSES):
        print(f"      {k:>3} {name:<20}{tr_c.get(k,0):>7}{va_c.get(k,0):>6}")
        if va_c.get(k, 0) == 0:
            missing.append(f"{k} {name}")
    if missing:
        print(f"      ⚠ val 缺失这些类，其 AP 无法评估: {', '.join(missing)}")

    # ---------- 复制文件 ----------
    if out_root.exists() and any(out_root.rglob("*")) and not args.force:
        sys.exit(f"\n[错误] 输出目录非空: {out_root}\n  加 --force 覆盖，或换 --out 目录")

    for split, idxs in (("train", train_idx), ("val", val_idx)):
        (out_root / "images" / split).mkdir(parents=True, exist_ok=True)
        (out_root / "labels" / split).mkdir(parents=True, exist_ok=True)
        for i in sorted(idxs, key=lambda k: items[k][0]):
            name, ip, lp = items[i]
            shutil.copy2(ip, out_root / "images" / split / f"{name}.png")
            shutil.copy2(lp, out_root / "labels" / split / f"{name}.txt")

    counts = {"train": len(train_idx), "val": len(val_idx)}
    print(f"\n完成 → {out_root}")
    print(f"  images/train {counts['train']:>3} 张   images/val {counts['val']:>3} 张")

    if args.yaml:
        yp = Path(args.yaml)
        if not yp.is_absolute():
            yp = root / yp
        write_data_yaml(yp, out_root, counts, args.src)
        print(f"  data.yaml    → {yp}")

    print(f"  源目录未做任何改动")


if __name__ == "__main__":
    main()
