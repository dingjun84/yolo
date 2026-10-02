#!/usr/bin/env python3
"""YOLO26 推理测试脚本

把图片路径作为参数传进来即可，支持单张、多张、整个目录、以及 http(s) URL。

用法:
    python infer.py bus.jpg
    python infer.py img1.jpg img2.png --conf 0.4
    python infer.py ./samples/
    python infer.py https://ultralytics.com/images/bus.jpg
    python infer.py bus.jpg --model yolo26s.pt --imgsz 416
    python infer.py ./samples/ --json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff", ".heic", ".avif"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
MEDIA_SUFFIXES = IMAGE_SUFFIXES | VIDEO_SUFFIXES


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="YOLO26 推理测试（默认 CPU）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n"
        "  python infer.py bus.jpg\n"
        "  python infer.py ./samples/ --conf 0.4\n"
        "  python infer.py bus.jpg --model yolo26s.pt --imgsz 416\n"
        "  python infer.py ./samples/ --json",
    )
    p.add_argument("source", nargs="+", help="图片/视频路径，或目录（递归），支持 http(s) URL")
    p.add_argument("--model", default=str(ROOT / "yolo26n.pt"),
                   help="权重路径或模型名，默认项目内 yolo26n.pt")
    p.add_argument("--imgsz", type=int, default=640, help="推理分辨率，默认 640")
    p.add_argument("--conf", type=float, default=0.25, help="置信度阈值，默认 0.25")
    p.add_argument("--iou", type=float, default=0.7, help="NMS IoU 阈值，默认 0.7")
    p.add_argument("--device", default="cpu", help="推理设备，默认 cpu")
    p.add_argument("--max-det", type=int, default=300, help="单图最大检测数，默认 300")
    p.add_argument("--name", default="predict", help="输出子目录名，默认 runs/<name>")
    p.add_argument("--no-save", action="store_true", help="不保存标注后的结果图")
    p.add_argument("--show", action="store_true", help="弹窗显示结果（每张图会阻塞）")
    p.add_argument("--json", action="store_true", help="额外输出 JSON 报告到输出目录")
    return p


def expand_sources(raw: list[str]) -> list[str]:
    """把目录展开成文件列表，并校验本地路径是否存在。"""
    out: list[str] = []
    for s in raw:
        if s.startswith(("http://", "https://")):
            out.append(s)
            continue
        p = Path(s).expanduser()
        if not p.exists():
            raise FileNotFoundError(f"路径不存在: {p}")
        if p.is_dir():
            files = sorted(f for f in p.rglob("*") if f.suffix.lower() in MEDIA_SUFFIXES)
            if not files:
                raise FileNotFoundError(
                    f"目录里没找到可推理的媒体文件: {p}\n"
                    f"  支持的扩展名: {', '.join(sorted(MEDIA_SUFFIXES))}"
                )
            out.extend(str(f) for f in files)
        else:
            out.append(str(p))
    return out


def fmt_classes(names, cls_ids, confs, limit: int = 6) -> list[str]:
    """按类别聚合，返回 '类别 ×数量 (最高置信度)' 形式的行。"""
    grouped: dict[str, list[float]] = {}
    for cid, cf in zip(cls_ids, confs):
        grouped.setdefault(names.get(cid, str(cid)), []).append(cf)
    rows = sorted(grouped.items(), key=lambda kv: (-len(kv[1]), -max(kv[1])))
    lines = [f"{name} ×{len(cs)} (最高 {max(cs):.2f})" for name, cs in rows[:limit]]
    if len(rows) > limit:
        lines.append(f"... 另有 {len(rows) - limit} 个类别")
    return lines


def main() -> int:
    args = build_parser().parse_args()

    # ---- 1. 校验输入 ----
    try:
        sources = expand_sources(args.source)
    except FileNotFoundError as e:
        print(f"[错误] {e}", file=sys.stderr)
        return 2

    model_path = args.model
    if not Path(model_path).exists():
        # 不是本地文件就当模型名交给 ultralytics 自动下载
        print(f"[提示] 本地无 {model_path}，将尝试按模型名自动下载")

    # ---- 2. 延迟导入，保证 --help 秒开 ----
    try:
        import torch
        import ultralytics
        from ultralytics import YOLO
    except ImportError as e:
        print(f"[错误] 依赖未装齐: {e}", file=sys.stderr)
        print("       请确认已激活环境: conda activate "
              f"{ROOT}/.conda/envs/yolo26", file=sys.stderr)
        return 3

    print(f"ultralytics {ultralytics.__version__} | torch {torch.__version__} | device {args.device}")
    print(f"模型 {model_path}")
    print(f"共 {len(sources)} 个输入 | imgsz={args.imgsz} conf={args.conf} iou={args.iou}")
    print("-" * 72)

    # ---- 3. 推理 ----
    # 临时压低 ultralytics 自己的 INFO 日志（含 "Results saved to ..."），
    # 避免它插在下面格式化输出中间造成顺序错乱；进度条不受影响。
    import logging

    from ultralytics.utils import LOGGER as UL_LOGGER

    prev_level = UL_LOGGER.level
    UL_LOGGER.setLevel(logging.WARNING)
    try:
        model = YOLO(model_path)
        results = model.predict(
            source=sources,
            imgsz=args.imgsz,
            conf=args.conf,
            iou=args.iou,
            device=args.device,
            max_det=args.max_det,
            save=not args.no_save,
            project=str(ROOT / "runs"),
            name=args.name,
            show=args.show,
            verbose=False,
        )
    finally:
        UL_LOGGER.setLevel(prev_level)

    # ---- 4. 汇总 ----
    total_cls: Counter = Counter()
    total_boxes = 0
    speed_sum = {"preprocess": 0.0, "inference": 0.0, "postprocess": 0.0}
    report_items = []

    for i, r in enumerate(results, 1):
        names = r.names if isinstance(r.names, dict) else dict(enumerate(r.names))
        boxes = r.boxes
        cls_ids = [int(c) for c in boxes.cls.tolist()] if boxes is not None and len(boxes) else []
        confs = [float(c) for c in boxes.conf.tolist()] if boxes is not None and len(boxes) else []

        total_boxes += len(cls_ids)
        total_cls.update(names.get(c, str(c)) for c in cls_ids)
        for k in speed_sum:
            speed_sum[k] += float(r.speed.get(k, 0.0))

        label = Path(str(r.path)).name
        print(f"[{i}/{len(results)}] {label}")
        if not cls_ids:
            print("      未检测到目标（可尝试降低 --conf）")
        else:
            for line in fmt_classes(names, cls_ids, confs):
                print(f"      {line}")
        print(f"      耗时 推理 {r.speed.get('inference', 0):.1f}ms "
              f"(预处理 {r.speed.get('preprocess', 0):.1f} / 后处理 {r.speed.get('postprocess', 0):.1f})")

        report_items.append({
            "path": str(r.path),
            "num_boxes": len(cls_ids),
            "detections": [
                {"class": names.get(c, str(c)), "conf": round(cf, 4)}
                for c, cf in zip(cls_ids, confs)
            ],
            "speed_ms": {k: round(float(v), 2) for k, v in r.speed.items()},
        })

    n = max(len(results), 1)
    print("-" * 72)
    print(f"合计 {total_boxes} 个目标，覆盖 {len(total_cls)} 个类别")
    if total_cls:
        top = "、".join(f"{k}×{v}" for k, v in total_cls.most_common(10))
        print(f"类别分布: {top}")
    print(f"平均单张: 推理 {speed_sum['inference'] / n:.1f}ms "
          f"(预处理 {speed_sum['preprocess'] / n:.1f} / 后处理 {speed_sum['postprocess'] / n:.1f})")

    # ---- 5. 输出位置 ----
    # 注意 --no-save 时 ultralytics 的 save_dir 是 None，不能直接 Path(None)
    save_dir = getattr(results[0], "save_dir", None)
    if save_dir:
        save_dir = Path(str(save_dir))
        print(f"结果目录: {save_dir}")
    else:
        save_dir = ROOT / "runs" / args.name
        print("未保存结果图（--no-save）")

    if args.json:
        report = {
            "model": str(model_path),
            "ultralytics": ultralytics.__version__,
            "torch": torch.__version__,
            "device": args.device,
            "args": {"imgsz": args.imgsz, "conf": args.conf, "iou": args.iou, "max_det": args.max_det},
            "summary": {
                "num_inputs": len(results),
                "total_boxes": total_boxes,
                "class_counts": dict(total_cls),
                "avg_speed_ms": {k: round(v / n, 2) for k, v in speed_sum.items()},
            },
            "items": report_items,
        }
        report_path = save_dir / "report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON 报告: {report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
