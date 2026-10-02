#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
微信 UI 元素检测 —— YOLO26 微调脚本（含 loss 实时曲线）

功能
----
1. 按命令行参数训练。默认值 = 需求里给的那一套，任意项都能在命令行覆盖。
2. 每个 epoch 结束后，把 train/val 的 box·cls·dfl loss、mAP、lr 追加写入
   runs/train/<name>/loss_history.csv
3. 每个 epoch 结束后重绘 runs/train/<name>/loss_curve.png —— 这就是「实时曲线」：
   训练跑着的时候用系统看图工具打开这个 PNG，它会逐个 epoch 自动刷新。
4. --live-window 额外弹一个 matplotlib 交互窗口（本机跑才有意义；服务器上
   没有 DISPLAY 会自动跳过）。

为什么用「重绘 PNG」而不是 TensorBoard
--------------------------------------
PNG 方案零额外依赖、不占端口、在远程服务器上也能拉下来看，而且不干扰
Ultralytics 自己写的 results.csv（那份仍然会正常生成，字段更全）。
想上 TensorBoard 单独装即可，不影响本脚本。

参数取值提醒（这三个和 UI 截图的特性有冲突，详见 README/讨论记录）
------------------------------------------------------------------
  --hsv-h 0.005  建议 0      ：色相是区分 incoming/outgoing 气泡的唯一判据
  --hsv-s 0.4    建议 0      ：企微我方气泡是浅蓝、对方偏白，饱和度一扰就分不开
  --mosaic 0.5   建议 0      ：mosaic 拼出的是现实中不存在的界面布局
  一键替换：见文件末尾的「建议启动命令」注释
"""

import argparse
import csv
import os
import sys
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image

ROOT = Path(__file__).resolve().parent

def csv_fields(history):
    """动态生成 CSV 列名。

    为什么不写死：YOLO26 的检测 loss 是 box / cls / **l1**（不是 YOLOv8 时代的 dfl），
    列名必须跟着 trainer 实际报出的 loss 名走，写死会整列丢数据。
    """
    keys = []
    for h in history:
        for k in h:
            if k not in keys:
                keys.append(k)

    def order(k):
        if k == "epoch":
            return (0, k)
        for i, p in enumerate(("train/", "val/", "metrics/")):
            if k.startswith(p):
                return (i + 1, k)
        return (9, k)  # lr 等收尾

    return sorted(keys, key=order)

_PLT = None  # matplotlib.pyplot 懒加载，见 get_plt()


# --------------------------------------------------------------------------
# 参数
# --------------------------------------------------------------------------
def parse_scale(v):
    """"0.2" -> 0.2（区间 [0.8,1.2]）；"0.85,1.0" -> (0.85, 1.0)（绝对区间）。

    Ultralytics 8.4 起 scale 支持元组，此时按绝对值解释。
    本项目的 UI 截图建议用元组形式只做「轻微缩小」，因为 s<1 会把小目标
    压得更小、s>1 会裁掉最左侧的导航栏。
    """
    if isinstance(v, str) and "," in v:
        a, b = v.split(",")
        return (float(a), float(b))
    return float(v)


def parse_args():
    p = argparse.ArgumentParser(
        description="YOLO26 微调（微信 UI 元素检测）+ loss 实时曲线",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    # --- 路径 ---
    p.add_argument("--model", default=str(ROOT / "yolo26n.pt"))
    p.add_argument("--data", default=None,
                   help="data*.yaml 路径。本项目两个域的数据分开训练，"
                        "没有合理的默认值，必须显式指定（不指定会列出候选项）")
    p.add_argument("--project", default=str(ROOT / "runs" / "train"))
    p.add_argument("--name", default=None,
                   help="run 名称。默认从 data.yaml 的 path 目录名推导"
                        "（datasets/wechat_ui -> wechat_ui，datasets/wxwork_ui -> wxwork_ui），"
                        "避免换 --data 时误写进上一个数据集的 run 目录")

    # --- 训练核心 ---
    p.add_argument("--epochs", type=int, default=100)
    p.add_argument("--patience", type=int, default=30)
    p.add_argument("--imgsz", type=int, default=1280)
    p.add_argument("--batch", type=int, default=4)
    p.add_argument("--lr0", type=float, default=0.001)
    p.add_argument("--cos-lr", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--freeze", type=int, default=0)
    p.add_argument("--optimizer", default="auto",
                   help="auto / SGD / Adam / AdamW / NAdam / RAdam / RMSProp")
    p.add_argument("--seed", type=int, default=0)

    # --- 几何增强（全部按 UI 截图特性设定）---
    p.add_argument("--fliplr", type=float, default=0.0, help="左右翻转，界面语义会错乱，必须 0")
    p.add_argument("--flipud", type=float, default=0.0)
    p.add_argument("--scale", default="0.2", help='float 如 "0.2" 或元组 "0.85,1.0"')
    p.add_argument("--degrees", type=float, default=0.0)
    p.add_argument("--shear", type=float, default=0.0)
    p.add_argument("--perspective", type=float, default=0.0)
    p.add_argument("--translate", type=float, default=0.1)

    # --- 拼接与色彩 ---
    p.add_argument("--mosaic", type=float, default=0.5)
    p.add_argument("--close-mosaic", type=int, default=15)
    p.add_argument("--hsv-h", type=float, default=0.005)
    p.add_argument("--hsv-s", type=float, default=0.4)
    p.add_argument("--hsv-v", type=float, default=0.3)

    # --- 运行环境 ---
    p.add_argument("--device", default="cpu")
    p.add_argument("--workers", type=int, default=0)
    p.add_argument("--cache", default="False",
                   help="False / True / ram —— 小数据集建议 ram")
    p.add_argument("--rect", action=argparse.BooleanOptionalAction, default=False,
                   help="矩形训练，省算力但形状与推理时 letterbox 不一致")
    p.add_argument("--resume", action=argparse.BooleanOptionalAction, default=False)

    # --- 调试 / 可视化 ---
    p.add_argument("--smoke", action="store_true",
                   help="冒烟模式：epochs=2 imgsz=640 batch=2，只验证链路通不通")
    p.add_argument("--live-window", action="store_true",
                   help="额外弹出 matplotlib 交互窗口（服务器上会自动跳过）")
    p.add_argument("--no-plot", action="store_true", help="不画 loss 曲线")
    return p.parse_args()


def as_cache(v):
    """cache 参数：False / True / ram / disk 四种取值都要能透传。"""
    s = str(v).strip().lower()
    if s in ("ram", "disk"):
        return s
    return s in ("1", "true", "yes")


# --------------------------------------------------------------------------
# 绘图
# --------------------------------------------------------------------------
def get_plt(live):
    """懒加载 pyplot。backend 必须在 import pyplot 之前设置，所以放在这里。"""
    global _PLT
    if _PLT is None:
        import matplotlib
        if not live:
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        _PLT = plt
    return _PLT


def draw_curves(history, out_png, live=False):
    """把 history 画成 2x3 子图并保存。每个 epoch 调用一次 = 实时刷新。"""
    plt = get_plt(live)
    ep = [h["epoch"] for h in history]

    def col(key):
        return [h.get(key, np.nan) for h in history]

    fig, axes = plt.subplots(2, 3, figsize=(15, 8))
    fig.suptitle(f"WeChat UI detection - training monitor  (epoch {ep[-1] if ep else 0})",
                 fontsize=13)

    # loss 名从 history 里发现（box/cls/l1），不写死
    loss_keys = sorted({k[len("train/"):] for h in history for k in h if k.startswith("train/")}) \
        or ["box_loss", "cls_loss", "l1_loss"]
    top_axes = [axes[0, 0], axes[0, 1], axes[0, 2]]
    for ax, key in zip(top_axes, loss_keys):
        ax.plot(ep, col(f"train/{key}"), "-o", ms=3, label="train", color="#185FA5")
        ax.plot(ep, col(f"val/{key}"), "-s", ms=3, label="val", color="#D85A30")
        ax.set_title(key.replace("_", " "), fontsize=11)
        ax.set_xlabel("epoch", fontsize=9)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=9)
    for ax in top_axes[len(loss_keys):]:
        ax.axis("off")

    ax = axes[1, 0]
    ax.plot(ep, col("metrics/mAP50(B)"), "-o", ms=3, label="mAP50", color="#3B6D11")
    ax.plot(ep, col("metrics/mAP50-95(B)"), "-s", ms=3, label="mAP50-95", color="#639922")
    ax.set_title("mAP", fontsize=11)
    ax.set_xlabel("epoch", fontsize=9)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=9)

    ax = axes[1, 1]
    ax.plot(ep, col("metrics/precision(B)"), "-o", ms=3, label="precision", color="#534AB7")
    ax.plot(ep, col("metrics/recall(B)"), "-s", ms=3, label="recall", color="#993556")
    ax.set_title("Precision / Recall", fontsize=11)
    ax.set_xlabel("epoch", fontsize=9)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=9)

    ax = axes[1, 2]
    ax.plot(ep, col("lr"), "-o", ms=3, color="#854F0B")
    ax.set_title("learning rate", fontsize=11)
    ax.set_xlabel("epoch", fontsize=9)
    ax.grid(alpha=0.3)

    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(out_png, dpi=100, bbox_inches="tight")
    if live:
        try:
            fig.canvas.draw()
            fig.canvas.flush_events()
            plt.pause(0.001)
            return  # 交互模式下保留 figure，下个 epoch 复用画布
        except Exception:
            pass
    plt.close(fig)


# --------------------------------------------------------------------------
# 回调：每个 epoch 落 CSV + 重绘曲线
# --------------------------------------------------------------------------
def make_callback(history, csv_path, png_path, live, no_plot):
    def on_fit_epoch_end(trainer):
        # 训练末尾的 final validation 会再触发一次本回调（此时 epoch == epochs，
        # tloss 已被清空）。不挡掉就会多记一条全 nan 的假 epoch。
        if int(trainer.epoch) >= int(trainer.epochs):
            return

        ep = int(trainer.epoch) + 1
        rec = {"epoch": ep}

        # train loss —— 注意 ultralytics 8.4 的 trainer.tloss 是 **dict**
        # （{'box_loss':…, 'cls_loss':…, 'l1_loss':…}），不是数组。
        # 用官方 API label_loss_items 解析最稳，它内部返回 {prefix}/{name}: value。
        try:
            if trainer.tloss:
                rec.update(trainer.label_loss_items(trainer.tloss, prefix="train"))
        except Exception as e:
            print(f"      [警告] train loss 记录失败: {type(e).__name__}: {e}")

        # val loss 与各项指标
        for k, v in (trainer.metrics or {}).items():
            if k.startswith("val/") or k.startswith("metrics/"):
                try:
                    rec[k] = float(v)
                except (TypeError, ValueError):
                    pass

        try:
            rec["lr"] = float(next(iter(trainer.lr.values())))
        except Exception:
            rec["lr"] = float("nan")

        history.append(rec)

        # 落 CSV（每轮覆盖写，文件始终完整）
        fields = csv_fields(history)
        with open(csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            for h in history:
                w.writerow({k: h.get(k, "") for k in fields})

        if not no_plot:
            try:
                draw_curves(history, png_path, live=live)
            except Exception as e:
                print(f"      [警告] 曲线绘制失败: {type(e).__name__}: {e}")

        # 终端同步一行，方便无图形环境
        g = rec.get
        print(
            f"      [epoch {ep:>3}] "
            f"box train={g('train/box_loss', float('nan')):.4f} / val={g('val/box_loss', float('nan')):.4f}   "
            f"cls val={g('val/cls_loss', float('nan')):.4f}   "
            f"mAP50={g('metrics/mAP50(B)', float('nan')):.4f}  "
            f"mAP50-95={g('metrics/mAP50-95(B)', float('nan')):.4f}"
        )

    return on_fit_epoch_end


# --------------------------------------------------------------------------
# 数据集体检 + 时间预估
# --------------------------------------------------------------------------
def inspect_data(data_yaml, imgsz):
    import yaml

    with open(data_yaml) as f:
        cfg = yaml.safe_load(f)
    base = Path(cfg.get("path", Path(data_yaml).parent))
    counts, sizes = {}, []
    for split in ("train", "val"):
        d = base / cfg[split]
        imgs = sorted(d.glob("*.png")) + sorted(d.glob("*.jpg"))
        counts[split] = len(imgs)
        if split == "train" and imgs:
            for p in imgs[:200]:
                with Image.open(p) as im:
                    sizes.append(max(im.size))
    if sizes:
        sizes.sort()
        med = sizes[len(sizes) // 2]
    else:
        med = imgsz
    return cfg, base, counts, med


def estimate_cpu_time(n_train, n_val, imgsz, batch, epochs):
    """CPU 耗时拟合。系数由本机实测校准（i7-9750H / yolo26n / ultralytics 8.4.156）：
    imgsz=640 batch=2 时实测 1.45 s/it，即训练单图约 0.72s；纯推理同理按 128ms 起算。
    """
    scale = (imgsz / 640.0) ** 1.3
    train_per_img = 0.72 * scale
    infer_per_img = 0.128 * scale
    per_epoch = n_train * train_per_img + n_val * infer_per_img
    return per_epoch, per_epoch * epochs


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def main():
    args = parse_args()

    # 不设默认 --data：个人微信与企业微信是两套数据、两个模型，
    # 给任何一方当默认值都会让人在跑另一方时误用配置。
    if not args.data:
        cands = sorted(p.name for p in ROOT.glob("data*.yaml"))
        listing = "\n".join(f"      --data {c}" for c in cands) or \
            "      （项目里还没有 data*.yaml，先跑 prepare_dataset.py 生成）"
        sys.exit("[错误] 必须用 --data 指定数据集配置（两份数据分开训练，没有默认值）。\n"
                 f"  可用：\n{listing}")

    data_path = Path(args.data)
    if not data_path.exists():
        sys.exit(f"[错误] 找不到 {data_path}\n  先跑 python prepare_dataset.py 生成数据集")
    if not Path(args.model).exists():
        sys.exit(f"[错误] 找不到预训练权重: {args.model}")

    cfg, base, counts, med_edge = inspect_data(args.data, args.imgsz)
    n_cls = cfg.get("nc", len(cfg.get("names", {})))

    # run 名称默认跟随数据集目录名。必须在读到 cfg.path 之后才能推导，
    # 也必须在 smoke 改名前完成 —— 否则 --data 一换就覆盖别的数据集的产物。
    if not args.name:
        args.name = base.name

    if args.smoke:
        args.epochs, args.imgsz, args.batch = 2, 640, 2
        args.close_mosaic = 0
        args.name += "_smoke"

    print("=" * 74)
    print("  微信 UI 元素检测 — YOLO26 微调")
    print("=" * 74)
    print(f"  权重      : {args.model}")
    print(f"  数据      : {args.data}")
    print(f"  数据集    : {base.name}   train {counts['train']} 张 / val {counts['val']} 张   "
          f"类别 {n_cls} 个")
    print(f"  run 名称  : {args.name}")
    print(f"  训练图长边中位数: {med_edge} px")
    if args.imgsz > med_edge * 1.15:
        print(f"  ⚠ imgsz={args.imgsz} 已超过训练图长边中位数 {med_edge}；"
              f"再往上只是插值放大，不会增加信息量")
    print(f"  imgsz={args.imgsz}  batch={args.batch}  epochs={args.epochs}  "
          f"patience={args.patience}  device={args.device}")
    print(f"  freeze={args.freeze}  optimizer={args.optimizer}  lr0={args.lr0}  "
          f"cos_lr={args.cos_lr}")
    sc = parse_scale(args.scale)
    print(f"  scale={sc}  mosaic={args.mosaic} (close@{args.close_mosaic})")
    print(f"  hsv_h={args.hsv_h}  hsv_s={args.hsv_s}  hsv_v={args.hsv_v}   "
          f"fliplr={args.fliplr}  flipud={args.flipud}")
    if args.hsv_s > 0.15 or args.hsv_h > 0.01 or args.mosaic > 0.2:
        print("  ⚠ 色彩/mosaic 参数偏离 UI 截图推荐值，见脚本头部说明")

    if args.device == "cpu":
        pe, tot = estimate_cpu_time(counts["train"], counts["val"], args.imgsz,
                                    args.batch, args.epochs)
        print(f"  预估      : 约 {pe:.0f} s/epoch  →  {tot/3600:.1f} 小时（{args.epochs} epoch，"
              f"CPU 拟合值，实际可能 ±30%）")
    print("=" * 74)

    # ---- 输出目录 ----
    run_dir = Path(args.project) / args.name
    run_dir.mkdir(parents=True, exist_ok=True)
    csv_path = run_dir / "loss_history.csv"
    png_path = run_dir / "loss_curve.png"
    print(f"  输出      : {run_dir}")
    print(f"  loss CSV  : {csv_path.name}")
    print(f"  loss 曲线 : {png_path.name}   ← 训练中随时打开，每 epoch 自动刷新")
    print("=" * 74)

    # ---- 模型与回调 ----
    from ultralytics import YOLO

    model = YOLO(args.model)
    history = []
    model.add_callback(
        "on_fit_epoch_end",
        make_callback(history, csv_path, png_path, args.live_window, args.no_plot),
    )

    # 先画一张空图，让用户立刻看到文件
    if not args.no_plot:
        try:
            draw_curves([], png_path, live=False)
        except Exception:
            pass

    t0 = time.time()
    results = model.train(
        data=args.data,
        epochs=args.epochs,
        patience=args.patience,
        imgsz=args.imgsz,
        batch=args.batch,
        lr0=args.lr0,
        cos_lr=args.cos_lr,
        freeze=args.freeze,
        optimizer=args.optimizer,
        seed=args.seed,
        fliplr=args.fliplr,
        flipud=args.flipud,
        scale=sc,
        degrees=args.degrees,
        shear=args.shear,
        perspective=args.perspective,
        translate=args.translate,
        mosaic=args.mosaic,
        close_mosaic=args.close_mosaic,
        hsv_h=args.hsv_h,
        hsv_s=args.hsv_s,
        hsv_v=args.hsv_v,
        device=args.device,
        workers=args.workers,
        cache=as_cache(args.cache),
        rect=args.rect,
        resume=args.resume,
        project=args.project,
        name=args.name,
        exist_ok=True,
        plots=True,
        verbose=True,
    )
    elapsed = time.time() - t0

    # ---- 收尾 ----
    print(f"\n{'=' * 74}")
    print(f"  训练结束，用时 {elapsed/3600:.2f} 小时，共 {len(history)} 轮"
          f"（patience={args.patience}）")

    def gnum(d, k):
        try:
            return float(d.get(k))
        except (TypeError, ValueError):
            return float("nan")

    valid = [h for h in history
             if gnum(h, "metrics/mAP50-95(B)") == gnum(h, "metrics/mAP50-95(B)")]
    if valid:
        best = max(valid, key=lambda h: gnum(h, "metrics/mAP50-95(B)"))
        last = valid[-1]
        print(f"  最佳 epoch    : {int(best['epoch'])}   "
              f"mAP50={gnum(best, 'metrics/mAP50(B)'):.4f}   "
              f"mAP50-95={gnum(best, 'metrics/mAP50-95(B)'):.4f}")
        print(f"  末轮 epoch    : {int(last['epoch'])}   "
              f"mAP50={gnum(last, 'metrics/mAP50(B)'):.4f}   "
              f"mAP50-95={gnum(last, 'metrics/mAP50-95(B)'):.4f}")
        if int(last["epoch"]) - int(best["epoch"]) > 5:
            print(f"  ⚠ 最佳出现在第 {int(best['epoch'])} 轮、之后连续退化 —— "
                  f"过拟合信号（数据量不足或增强不够）")
    print(f"  最佳权重      : {run_dir / 'weights' / 'best.pt'}")
    print(f"  loss CSV      : {csv_path}")
    print(f"  loss 曲线     : {png_path}")
    print("=" * 74)
    print("""
  下一步（先看指标，别急着用）：
    1. 打开 loss_curve.png —— train/val 的 box·cls loss 若在后期明显分叉，
       就是过拟合，说明数据量不够或增强不足
    2. 直接调 python infer.py 跑几张真实截图看实际效果
    3. 每类 AP：python -c "from ultralytics import YOLO; YOLO('%s').val(data='%s')"
""" % (run_dir / "weights" / "best.pt", args.data))


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# 建议的启动命令
# ---------------------------------------------------------------------------
# 两个域的数据集**分开训练**，各配一份 data yaml（run 名称自动跟随数据集名）：
#   data_chat.yaml    个人微信   datasets/chat_ui     train 46 / val 13
#   data_wxwork.yaml  企业微信   datasets/wxwork_ui   train 17 / val  5
#   data_merged.yaml  合并版（已退役，仅留作对照，不建议使用）
#   ※ --data 没有默认值，必须显式指定，避免误用另一份配置。
#
# A) 先冒烟，2 分钟确认链路通（强烈建议第一次这么做）
#    python train.py --data data_chat.yaml --smoke
#
# B) 个人微信（正式训练）
#    python train.py --data data_chat.yaml --hsv-h 0 --hsv-s 0 --mosaic 0 --scale 0.85,1.0
#
# C) 企业微信（只有 17 张训练图，务必盯紧 loss 曲线的 train/val 分叉）
#    python train.py --data data_wxwork.yaml --hsv-h 0 --hsv-s 0 --mosaic 0 --scale 0.85,1.0
#
# D) GPU 上跑（imgsz 上限受训练图长边中位数约束，脚本会提示）：
#    python train.py --data data_chat.yaml --device 0 --imgsz 1536 --batch 16 --workers 8 \
#        --cache ram --hsv-h 0 --hsv-s 0 --mosaic 0 --scale 0.85,1.0
#
# E) 两个模型训完后，做跨域测试（这才是「分开训」最有价值的产出）：
#    # 个人微信模型在企微 val 上测 → 量化域迁移差距
#    python -c "from ultralytics import YOLO; \
#        YOLO('runs/train/chat_ui/weights/best.pt').val(data='data_wxwork.yaml')"
