#!/usr/bin/env python3
"""Remap YOLO labels from the old 14-class schema (c14) to the new 13-class schema (c13).

c14 -> c13: conversation_item(6) and contact_item(4) are merged into list_item(4).

    old14                       new13
    0  self_avatar          ->  0  self_avatar
    1  nav_chat_icon        ->  1  nav_chat_icon
    2  nav_contacts_icon    ->  2  nav_contacts_icon
    3  search_bar           ->  3  search_bar
    4  contact_item         ->  4  list_item
    5  send_button          ->  5  send_button
    6  conversation_item    ->  4  list_item
    7  incoming_bubble      ->  6  incoming_bubble
    8  outgoing_bubble      ->  7  outgoing_bubble
    9  input_bar            ->  8  input_bar
    10 single_chat          ->  9  single_chat
    11 group_chat           ->  10 group_chat
    12 contact_send_message ->  11 contact_send_message
    13 nav_groups_icon      ->  12 nav_groups_icon

Nothing is modified in place. With --apply the whole source tree is mirrored to a NEW
directory (default: <src>_c13): label .txt files are remapped, images and other files are
copied (or hard-linked with --link), classes.txt / data yaml files that carry the old
14-class names are rewritten to the 13-class names, and image-list files (train.txt /
val.txt with absolute paths) are re-pointed at the new directory. A ready-to-train
<out>/data_c13.yaml is written too (--yaml FILE writes another copy; an existing FILE is
backed up to FILE.bak first). Ultralytics *.cache files and stale label_report.txt /
split_report.txt are skipped. Any layout works because the tree is mirrored:
flat (img + sidecar .txt), images/ + labels/, or train|val/{images,labels} splits.

Safety: the source schema must be proven to be c14 -- a classes.txt or *.yaml (with
`names:`) in the source root that lists exactly the old 14 names, or an explicit
--names-from FILE. 15-class (message_input), 11-class and 76-class trees are refused.
Any label id outside 0..13 aborts before anything is written. The output dir must not exist.

Default is dry-run (prints counts, writes nothing). Pure python + pathlib, works on Windows.

Usage:
  python tools/remap_14_to_13.py gen_data/out_c14                       # dry-run
  python tools/remap_14_to_13.py --apply gen_data/out_c14               # -> gen_data/out_c14_c13
  python tools/remap_14_to_13.py --apply gen_data/splits_c14 \\
      --names-from gen_data/data_c14.yaml --out gen_data/splits_c13
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

OLD14 = [
    "self_avatar", "nav_chat_icon", "nav_contacts_icon", "search_bar", "contact_item",
    "send_button", "conversation_item", "incoming_bubble", "outgoing_bubble", "input_bar",
    "single_chat", "group_chat", "contact_send_message", "nav_groups_icon",
]
NEW13 = [
    "self_avatar", "nav_chat_icon", "nav_contacts_icon", "search_bar", "list_item",
    "send_button", "incoming_bubble", "outgoing_bubble", "input_bar",
    "single_chat", "group_chat", "contact_send_message", "nav_groups_icon",
]
# old id -> new id
MAPPING = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 4, 7: 6, 8: 7, 9: 8, 10: 9, 11: 10, 12: 11, 13: 12}
assert all(NEW13[MAPPING[i]] == ("list_item" if n in ("contact_item", "conversation_item") else n)
           for i, n in enumerate(OLD14))

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
SKIP_SUFFIXES = {".cache"}
SKIP_NAMES = {".DS_Store", "Thumbs.db"}
STALE_REPORTS = {"label_report.txt", "split_report.txt"}  # counts would be wrong after remap
YAML_SUFFIXES = {".yaml", ".yml"}


# --------------------------------------------------------------------------- names parsing
def parse_names_file(path: Path) -> list[str] | None:
    """classes.txt (one name per line) or a data yaml with `names:`. No PyYAML needed."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    if path.suffix.lower() in YAML_SUFFIXES:
        return parse_yaml_names(text)
    names = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return names or None


def parse_yaml_names(text: str) -> list[str] | None:
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        m = re.match(r"^names\s*:\s*(.*)$", ln)
        if not m:
            continue
        rest = m.group(1).split("#", 1)[0].strip()
        if rest.startswith("["):  # inline list
            items = [x.strip().strip("'\"") for x in rest.strip("[]").split(",")]
            return [x for x in items if x] or None
        mapping: dict[int, str] = {}
        seq: list[str] = []
        for sub in lines[i + 1:]:
            if not sub.strip() or sub.lstrip().startswith("#"):
                continue
            if not sub[:1].isspace():
                break
            body = sub.split("#", 1)[0].strip()
            mm = re.match(r"^(\d+)\s*:\s*(.+)$", body)
            if mm:
                mapping[int(mm.group(1))] = mm.group(2).strip().strip("'\"")
                continue
            ms = re.match(r"^-\s*(.+)$", body)
            if ms:
                seq.append(ms.group(1).strip().strip("'\""))
        if mapping:
            return [mapping[k] for k in sorted(mapping)]
        return seq or None
    return None


def detect_schema(names: list[str] | None) -> str:
    if names is None:
        return "unknown"
    if names == OLD14:
        return "c14"
    if names == NEW13:
        return "c13"
    return "other(%d: %s)" % (len(names), ",".join(names[:7]) + ("..." if len(names) > 7 else ""))


def find_root_names(src: Path) -> tuple[list[str] | None, Path | None]:
    cands = [src / "classes.txt"] + sorted(p for p in src.iterdir()
                                          if p.is_file() and p.suffix.lower() in YAML_SUFFIXES)
    for c in cands:
        if c.is_file():
            names = parse_names_file(c)
            if names:
                return names, c
    return None, None


# --------------------------------------------------------------------------- labels
def parse_label_text(text: str) -> list[list[str]] | None:
    """Rows of tokens if this looks like a YOLO label file (empty file counts), else None."""
    rows = []
    for ln in text.splitlines():
        parts = ln.split()
        if not parts:
            continue
        if len(parts) < 5:
            return None
        try:
            [float(x) for x in parts]
        except ValueError:
            return None
        rows.append(parts)
    return rows


def remap_label(text: str, path: Path, stats: Counter, errors: list[str]) -> str:
    out = []
    eol = "\r\n" if "\r\n" in text else "\n"
    for lineno, ln in enumerate(text.splitlines(), 1):
        parts = ln.split()
        if not parts:
            continue
        try:
            cid_f = float(parts[0])
            cid = int(cid_f)
        except ValueError:
            errors.append("%s:%d bad class token %r" % (path, lineno, parts[0]))
            continue
        if cid != cid_f or cid not in MAPPING:
            errors.append("%s:%d class id %s outside 0..13 (not a c14 label?)" % (path, lineno, parts[0]))
            continue
        new = MAPPING[cid]
        stats["old_%d" % cid] += 1
        stats["new_%d" % new] += 1
        stats["lines"] += 1
        if new != cid:
            stats["changed_lines"] += 1
        out.append(" ".join([str(new)] + parts[1:]))
    return eol.join(out) + (eol if out else "")


def same_path(val: str, p: Path) -> bool:
    try:
        return Path(val).expanduser().resolve() == p.resolve()
    except (OSError, ValueError):
        return False


def rewrite_yaml(text: str, src: Path, out: Path) -> str:
    """Replace nc / names block, re-point `path:` if it pointed at src."""
    lines = text.splitlines()
    res: list[str] = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if re.match(r"^nc\s*:", ln):
            res.append("nc: %d" % len(NEW13))
        elif re.match(r"^names\s*:", ln):
            res.append("names:")
            res.extend("  %d: %s" % (k, n) for k, n in enumerate(NEW13))
            i += 1
            while i < len(lines) and (not lines[i].strip() or lines[i][:1].isspace()):
                i += 1
            continue
        elif re.match(r"^path\s*:", ln):
            # Windows "C:/..." has a colon too: take everything after the first "path:"
            val = ln[ln.index(":") + 1:].split(" #", 1)[0].strip().strip("'\"")
            res.append("path: %s" % out.as_posix() if val and same_path(val, src) else ln)
        else:
            res.append(ln)
        i += 1
    return "# remapped c14 -> c13 by tools/remap_14_to_13.py\n" + "\n".join(res) + "\n"


def repoint_list(text: str, src: Path, out: Path) -> str | None:
    """train.txt/val.txt style image lists: replace src prefix with out. None if not such a list."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines or not all(Path(ln).suffix.lower() in IMAGE_SUFFIXES for ln in lines):
        return None
    s_posix, s_native = src.as_posix(), str(src)
    new = []
    for t in lines:
        if t.startswith(s_posix):
            t = out.as_posix() + t[len(s_posix):]
        elif t.startswith(s_native):
            t = str(out) + t[len(s_native):]
        new.append(t)
    return "\n".join(new) + "\n"


# --------------------------------------------------------------------------- main work
def plan_tree(src: Path, out: Path) -> tuple[list[tuple], Counter, list[str], list[str]]:
    """Walk src, decide an action for every file. Nothing is written here."""
    actions: list[tuple] = []  # (kind, src_path, dst_path, payload)
    stats: Counter = Counter()
    errors: list[str] = []
    notes: list[str] = []
    for dirpath, dirnames, filenames in os.walk(src):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        d = Path(dirpath)
        for fn in sorted(filenames):
            p = d / fn
            rel = p.relative_to(src)
            dst = out / rel
            suf = p.suffix.lower()
            if fn in SKIP_NAMES or fn.startswith("._") or suf in SKIP_SUFFIXES or ".bak" in fn:
                stats["skipped"] += 1
                continue
            if fn in STALE_REPORTS:
                stats["skipped_stale_reports"] += 1
                continue
            if suf in IMAGE_SUFFIXES:
                actions.append(("image", p, dst, None))
                stats["images"] += 1
                continue
            if fn == "classes.txt":
                sch = detect_schema(parse_names_file(p))
                if sch == "c14":
                    actions.append(("write", p, dst, "\n".join(NEW13) + "\n"))
                    stats["classes_txt_rewritten"] += 1
                else:
                    if sch != "c13":
                        notes.append("classes.txt not c14, copied unchanged: %s [%s]" % (rel, sch))
                    actions.append(("copy", p, dst, None))
                continue
            if suf in YAML_SUFFIXES:
                text = p.read_text(encoding="utf-8", errors="ignore")
                if detect_schema(parse_yaml_names(text)) == "c14":
                    actions.append(("write", p, dst, rewrite_yaml(text, src, out)))
                    stats["yaml_rewritten"] += 1
                else:
                    actions.append(("copy", p, dst, None))
                continue
            if suf == ".txt":
                text = p.read_text(encoding="utf-8", errors="ignore")
                rows = parse_label_text(text)
                if rows is not None:
                    actions.append(("write", p, dst, remap_label(text, p, stats, errors)))
                    stats["label_files"] += 1
                    if not rows:
                        stats["empty_label_files"] += 1
                    continue
                lst = repoint_list(text, src, out)
                if lst is not None:
                    actions.append(("write", p, dst, lst))
                    stats["image_lists_repointed"] += 1
                    continue
            actions.append(("copy", p, dst, None))
            stats["other_files"] += 1
    return actions, stats, errors, notes


def detect_splits(root: Path) -> tuple[str, str]:
    if (root / "train" / "images").is_dir():
        return "train/images", ("val/images" if (root / "val" / "images").is_dir() else "train/images")
    if (root / "images" / "train").is_dir():
        return "images/train", ("images/val" if (root / "images" / "val").is_dir() else "images/train")
    if (root / "train.txt").is_file():
        return "train.txt", ("val.txt" if (root / "val.txt").is_file() else "train.txt")
    return ".", "."


def emit_yaml(out: Path, src: Path) -> str:
    train, val = detect_splits(src)  # out mirrors src, so the layout is the same
    body = [
        "# c13: conversation_item + contact_item merged into list_item (id 4).",
        "# generated by tools/remap_14_to_13.py from %s" % src.as_posix(),
        "path: %s" % out.as_posix(),
        "train: %s" % train,
        "val: %s" % val,
        "nc: %d" % len(NEW13),
        "names:",
    ] + ["  %d: %s" % (i, n) for i, n in enumerate(NEW13)]
    return "\n".join(body) + "\n"


def backup_path(p: Path) -> Path:
    bak = p.with_name(p.name + ".bak")
    n = 1
    while bak.exists():
        bak = p.with_name("%s.bak%d" % (p.name, n))
        n += 1
    return bak


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", nargs="+", help="c14 dataset/label root(s); the tree is mirrored")
    ap.add_argument("--apply", action="store_true", help="actually write (default: dry-run)")
    ap.add_argument("--out", help="output dir (single src only; default <src>_c13). Must not exist.")
    ap.add_argument("--names-from", help="classes.txt or data yaml that declares the SOURCE schema "
                                         "(use when src root has no classes.txt/yaml, e.g. splits_c14)")
    ap.add_argument("--yaml", help="also write the new 13-class data yaml here (single src only)")
    ap.add_argument("--link", action="store_true", help="hard-link images instead of copying (same drive)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if len(args.src) > 1 and (args.out or args.yaml):
        ap.error("--out / --yaml only work with a single src")

    mode = "APPLY" if args.apply else "DRY-RUN"
    declared = None
    if args.names_from:
        declared = parse_names_file(Path(args.names_from).expanduser())
        if detect_schema(declared) != "c14":
            print("[error] --names-from %s is not the old 14-class list: %s"
                  % (args.names_from, detect_schema(declared)))
            return 2

    rc = 0
    for s in args.src:
        src = Path(s).expanduser().resolve()
        out = Path(args.out).expanduser().resolve() if args.out else src.with_name(src.name + "_c13")
        print("== [%s] %s -> %s" % (mode, src, out))
        if not src.is_dir():
            print("   [skip] not a directory")
            rc = 1
            continue
        names, where = find_root_names(src)
        if declared is not None:
            if names is not None and detect_schema(names) != "c14":
                print("   [refuse] %s says %s, contradicts --names-from" % (where, detect_schema(names)))
                rc = 1
                continue
            schema, where_s = "c14", "--names-from %s" % args.names_from
        else:
            schema, where_s = detect_schema(names), (str(where) if where else "no classes.txt/yaml in root")
        print("   source schema: %s (from %s)" % (schema, where_s))
        if schema == "c13":
            print("   [skip] already 13-class")
            continue
        if schema != "c14":
            print("   [refuse] source is not proven c14. Put the c14 classes.txt/yaml in the root "
                  "or pass --names-from gen_data/data_c14.yaml if you are sure.")
            rc = 1
            continue
        if out.exists():
            print("   [refuse] output already exists (never overwritten): %s" % out)
            rc = 1
            continue
        if out == src or src in out.parents:
            print("   [refuse] output is inside source")
            rc = 1
            continue

        actions, stats, errors, notes = plan_tree(src, out)
        for n in notes:
            print("   [note] " + n)
        print("   files: labels=%d (empty=%d) images=%d classes.txt=%d yaml=%d lists=%d other=%d "
              "skipped=%d stale_reports_skipped=%d" % (
                  stats["label_files"], stats["empty_label_files"], stats["images"],
                  stats["classes_txt_rewritten"], stats["yaml_rewritten"], stats["image_lists_repointed"],
                  stats["other_files"], stats["skipped"], stats["skipped_stale_reports"]))
        print("   boxes: %d, ids changed: %d (conversation_item->list_item merged: %d)" % (
            stats["lines"], stats["changed_lines"], stats["old_6"]))
        print("   %-3s %-22s %7s  ->  %-3s %-22s %7s" % ("old", "name", "boxes", "new", "name", "boxes"))
        for i, n in enumerate(OLD14):
            j = MAPPING[i]
            print("   %-3d %-22s %7d  ->  %-3d %-22s %7d" % (
                i, n, stats["old_%d" % i], j, NEW13[j], stats["new_%d" % j]))
        if errors:
            print("   [error] %d bad label lines; nothing will be written. First few:" % len(errors))
            for e in errors[:10]:
                print("      " + e)
            rc = 1
            continue
        if args.verbose:
            for kind, p, _dst, _ in actions:
                print("   %-5s %s" % (kind, p.relative_to(src)))
        yaml_text = emit_yaml(out, src)
        auto_yaml = out / "data_c13.yaml"
        print("   data yaml -> train: %s  val: %s" % detect_splits(src))
        if not args.apply:
            print("   would write: %s" % auto_yaml)
            if args.yaml:
                print("   would write: %s" % Path(args.yaml).expanduser().resolve())
            print("   (dry-run: nothing written; add --apply)")
            continue

        for kind, p, dst, payload in actions:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if kind == "write":
                with open(dst, "w", encoding="utf-8", newline="") as f:
                    f.write(payload)
            elif kind == "image" and args.link:
                try:
                    os.link(p, dst)
                except OSError:
                    shutil.copy2(p, dst)
            else:
                shutil.copy2(p, dst)
        out.mkdir(parents=True, exist_ok=True)
        (out / "remap_report.txt").write_text(
            "remapped c14 -> c13 from %s\nboxes=%d changed=%d\n" % (src, stats["lines"], stats["changed_lines"])
            + "".join("%d %s %d\n" % (j, n, stats["new_%d" % j]) for j, n in enumerate(NEW13)),
            encoding="utf-8")
        if not auto_yaml.exists():
            auto_yaml.write_text(yaml_text, encoding="utf-8")
            print("   wrote: %s" % auto_yaml)
        if args.yaml:
            yp = Path(args.yaml).expanduser().resolve()
            if yp.exists():
                bak = backup_path(yp)
                shutil.copy2(yp, bak)
                print("   existing yaml backed up -> %s" % bak)
            yp.parent.mkdir(parents=True, exist_ok=True)
            yp.write_text(yaml_text, encoding="utf-8")
            print("   wrote: %s" % yp)
        print("   done: %d files under %s" % (len(actions), out))
    return rc


if __name__ == "__main__":
    sys.exit(main())
