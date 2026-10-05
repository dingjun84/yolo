#!/usr/bin/env python3
"""Remap YOLO label ids from 15-class (with message_input@5) to 14-class.

Rule: drop lines with class id 5 (message_input); shift ids 6..14 -> 5..13.
Default is dry-run. Pass --apply to write (each file backed up as <.name>.bak_c15 once).

Usage:
  python tools/remap_15_to_14.py DIR [DIR ...]
  python tools/remap_15_to_14.py --apply DIR
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

SKIP_NAMES = {"classes.txt", "label_report.txt"}


def process_file(path: Path, apply: bool) -> tuple[int, int, int]:
    """Returns (lines_in, dropped, shifted)."""
    raw = path.read_text(encoding="utf-8", errors="ignore")
    lines = raw.splitlines(keepends=True)
    out: list[str] = []
    dropped = shifted = 0
    for line in lines:
        parts = line.split()
        if len(parts) >= 5:
            try:
                cid = int(float(parts[0]))
            except ValueError:
                out.append(line)
                continue
            if cid == 5:
                dropped += 1
                continue
            if cid > 5:
                shifted += 1
                end = ""
                if line.endswith("\r\n"):
                    end = "\r\n"
                elif line.endswith("\n"):
                    end = "\n"
                parts[0] = str(cid - 1)
                out.append(" ".join(parts) + end)
                continue
        out.append(line)
    if apply:
        bak = path.with_name(path.name + ".bak_c15")
        if not bak.exists():
            shutil.copy2(path, bak)
        path.write_text("".join(out), encoding="utf-8")
    return len(lines), dropped, shifted


def looks_like_yolo_label(path: Path) -> bool:
    try:
        sample = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    for line in sample.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            cid = int(float(parts[0]))
            vals = [float(x) for x in parts[1:5]]
        except ValueError:
            continue
        if all(0.0 <= v <= 1.5 for v in vals) and 0 <= cid <= 20:
            return True
    return False



def nearest_is_14_class(path: Path, root: Path) -> bool:
    """True if a classes.txt between path and root (inclusive) is already 14-class.

    Does not walk above `root`, so a repo-level classes.txt won't mask nested
    15-class / 11-class datasets.
    """
    root = root.resolve()
    cur = path.parent.resolve()
    root_parents = set(root.parents)
    while True:
        ct = cur / "classes.txt"
        if ct.is_file():
            names = [ln.strip() for ln in ct.read_text(encoding="utf-8", errors="ignore").splitlines() if ln.strip()]
            if len(names) >= 6 and names[5] == "send_button" and "message_input" not in names:
                return True
            if "message_input" in names:
                return False
            return False
        if cur == root or cur in root_parents:
            break
        if cur.parent == cur:
            break
        cur = cur.parent
    return False

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dirs", nargs="+", help="label roots to walk")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = ap.parse_args()

    total_files = total_drop = total_shift = touched = 0
    for d in args.dirs:
        root = Path(d).expanduser().resolve()
        if not root.is_dir():
            print(f"[skip] not a dir: {root}")
            continue
        for path in sorted(root.rglob("*.txt")):
            if path.name in SKIP_NAMES or path.name.endswith(".bak_c15"):
                continue
            if not looks_like_yolo_label(path):
                continue
            # Skip if nearest classes.txt is already 14-class (id5=send_button).
            # 15-class trees usually ship their own classes.txt with message_input@5.
            if nearest_is_14_class(path, root):
                continue
            n, dropped, shifted = process_file(path, apply=args.apply)
            total_files += 1
            total_drop += dropped
            total_shift += shifted
            if dropped or shifted:
                touched += 1
                mode = "APPLY" if args.apply else "DRY"
                print(f"[{mode}] {path}: lines={n} drop_id5={dropped} shift={shifted}")

    print(
        f"\nSummary ({'APPLY' if args.apply else 'DRY-RUN'}): "
        f"label_files={total_files} touched={touched} "
        f"dropped_message_input_lines={total_drop} shifted_lines={total_shift}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
