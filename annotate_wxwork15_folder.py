#!/usr/bin/env python3
"""Predict YOLO labels into an image folder as sidecars + classes.txt + label_report.txt."""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

DEFAULT_NAMES = [
    "self_avatar",
    "nav_chat_icon",
    "nav_contacts_icon",
    "search_bar",
    "list_item",  # c13：合并了旧 contact_item(4) / conversation_item(6)
    "send_button",
    "incoming_bubble",
    "outgoing_bubble",
    "input_bar",
    "single_chat",
    "group_chat",
    "contact_send_message",
    "nav_groups_icon",
]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True)
    p.add_argument("--source", required=True, help="image directory")
    p.add_argument("--imgsz", type=int, default=1280)
    p.add_argument("--conf", type=float, default=0.25)
    p.add_argument("--device", default="cpu")
    p.add_argument("--iou", type=float, default=0.7)
    args = p.parse_args()

    src = Path(args.source).expanduser().resolve()
    if not src.is_dir():
        print(f"[error] not a directory: {src}", file=sys.stderr)
        return 2

    images = sorted(f for f in src.iterdir() if f.suffix.lower() in IMAGE_SUFFIXES)
    if not images:
        print(f"[error] no images in {src}", file=sys.stderr)
        return 2

    from ultralytics import YOLO

    model = YOLO(args.model)
    names = list(DEFAULT_NAMES)
    # Prefer model.names whenever available (13-class c13, legacy 14-class, or otherwise);
    # DEFAULT_NAMES (c13) is only a fallback for weights without embedded names.
    if isinstance(model.names, dict) and model.names:
        names = [model.names[i] for i in sorted(int(k) for k in model.names.keys())]
    elif isinstance(model.names, (list, tuple)) and model.names:
        names = list(model.names)

    (src / "classes.txt").write_text("\n".join(names) + "\n", encoding="utf-8")

    class_counts: Counter = Counter()
    per_image = []
    nonempty = 0

    results = model.predict(
        source=[str(f) for f in images],
        imgsz=args.imgsz,
        conf=args.conf,
        iou=args.iou,
        device=args.device,
        save=False,
        verbose=False,
    )

    for img, r in zip(images, results):
        lines = []
        boxes = r.boxes
        n = 0
        if boxes is not None and len(boxes):
            # xywhn is already normalized cx,cy,w,h
            xywhn = boxes.xywhn.tolist()
            cls_ids = [int(c) for c in boxes.cls.tolist()]
            for cid, (cx, cy, w, h) in zip(cls_ids, xywhn):
                lines.append(f"{cid} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
                class_counts[cid] += 1
                n += 1
        label_path = img.with_suffix(".txt")
        label_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        if n:
            nonempty += 1
        per_image.append((img.name, n))
        print(f"{img.name}: {n} boxes")

    report_lines = [
        f"model: {args.model}",
        f"source: {src}",
        f"imgsz: {args.imgsz}",
        f"conf: {args.conf}",
        f"device: {args.device}",
        f"images: {len(images)}",
        f"nonempty_labels: {nonempty}",
        f"total_boxes: {sum(class_counts.values())}",
        "",
        "per_class_counts:",
    ]
    for i, name in enumerate(names):
        report_lines.append(f"  {i:2d} {name}: {class_counts.get(i, 0)}")
    missing = [names[i] for i in range(len(names)) if class_counts.get(i, 0) == 0]
    report_lines.append("")
    report_lines.append("missing_classes: " + (", ".join(missing) if missing else "(none)"))
    report_lines.append("")
    report_lines.append("per_image:")
    for name, n in per_image:
        report_lines.append(f"  {name}: {n}")

    report_path = src / "label_report.txt"
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    print("-" * 60)
    print(report_path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
