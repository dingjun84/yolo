#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验「类别名口径」在全仓只有一套：13 类，id 4 = list_item。

用法:
  python tools/check_class_consistency.py
      # 静态检查（默认，秒级，不需要 torch/ultralytics）

  python tools/check_class_consistency.py --weights weights/yolo26n_detect_wxwork.pt
      # 追加校验权重内嵌的 model.names 是否与口径一致（需要 ultralytics，较慢）

检查项:
  A  根 classes.txt 与 gen_data/classes.txt 逐行一致，且等于权威表
  B  gen_data/data_c13.yaml 的 nc / names 与权威表一致
  C  server.py 的 CLASS_NAMES_CANONICAL 与权威表一致
  D  prepare_dataset.py 的 CLASSES 与权威表一致
  E  annotate_wxwork15_folder.py 的 DEFAULT_NAMES 与权威表一致
  F  gen_data/wecom_ui.py 的 NUM_CLASSES 与 CLS_* 常量拓扑正确（含 CLS_LIST_ITEM == 4）
  G  现役源码/文档里不出现旧类名（冻结的历史资产在白名单内，不计）
  H  已生成的 out_*/classes.txt（若存在）与权威表一致

退出码: 0 = 全部通过; 1 = 有不一致。
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CANONICAL_SRC = ROOT / "classes.txt"

# 旧类名。只允许出现在冻结的历史资产里，现役路径一律不得出现。
OLD_NAMES = ("contact_item", "conversation_item")

# 冻结的历史资产（不再使用，也刻意不改造）—— 扫描时跳过。
FROZEN_FILES = {
    "tools/remap_14_to_13.py",     # 转换工具，输入侧本就是旧名
    "gen_data/synth_c14.log",      # 历史日志
    "data_chat.yaml",
    "data_merged.yaml",
    "data_wxwork.yaml",
    "gen_data/data_c14.yaml",
    "gen_data/data_ft200.yaml",
    "gen_data/data_ft200_search.yaml",
    "gen_data/data_pages20.yaml",
    "gen_data/data_search10.yaml",
    "gen_data/data_train15.yaml",
    "gen_data/data_m.yaml",
}

# 冻结的历史产物目录（15 类时代生成的合成数据集，与上面那批 yaml 配对）
FROZEN_DIRS = {
    "gen_data/out_train15",
    "gen_data/out_ft200",
    "gen_data/out_ft200_search",
    "gen_data/out_ft200_sparse",
    "gen_data/out_pages20",
    "gen_data/out_search10",
    "gen_data/out_check10",
}

# 当前口径的合成产物目录（H 检查它）
CURRENT_OUT = "gen_data/out_c13"

# wecom_ui.py 里 CLS_* 常量与 id 的期望对应关系（id 4 必须是 list_item）
EXPECTED_CONSTS = {
    "CLS_SELF_AVATAR": 0,
    "CLS_NAV_CHAT": 1,
    "CLS_NAV_CONTACTS": 2,
    "CLS_SEARCH_BAR": 3,
    "CLS_LIST_ITEM": 4,
    "CLS_SEND_BUTTON": 5,
    "CLS_INCOMING": 6,
    "CLS_OUTGOING": 7,
    "CLS_INPUT_BAR": 8,
    "CLS_SINGLE_CHAT": 9,
    "CLS_GROUP_CHAT": 10,
    "CLS_CONTACT_SEND_MESSAGE": 11,
    "CLS_NAV_GROUPS": 12,
}

SKIP_DIRS = {".git", ".conda", "__pycache__", ".workbuddy", "node_modules"}
SKIP_TOP = {"runs", "datasets", "weights", "real_screenshots", "chat_dataset", "wxwork_dataset"}


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.notes: list[str] = []

    def ok(self, tag: str, msg: str) -> None:
        print(f"  [OK]   {tag}  {msg}")

    def fail(self, tag: str, msg: str) -> None:
        self.failures.append(f"{tag}: {msg}")
        print(f"  [FAIL] {tag}  {msg}")

    def note(self, msg: str) -> None:
        self.notes.append(msg)
        print(f"  [note] {msg}")


def read_canonical() -> list[str]:
    if not CANONICAL_SRC.exists():
        print(f"[error] 找不到权威类别表 {CANONICAL_SRC}", file=sys.stderr)
        sys.exit(2)
    return [ln.strip() for ln in CANONICAL_SRC.read_text(encoding="utf-8").splitlines() if ln.strip()]


def literal_assigns(path: Path) -> dict[str, object]:
    """取出模块级 `NAME = <literal>` 的字面量赋值（含带注解的）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out: dict[str, object] = {}
    for node in tree.body:
        targets: list[str] = []
        value = None
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
            value = node.value
        if not targets or value is None:
            continue
        try:
            lit = ast.literal_eval(value)
        except ValueError:
            continue
        for t in targets:
            out[t] = lit
    return out


def check_names_list(report: Report, tag: str, label: str, got: list[str], canonical: list[str]) -> None:
    if got == canonical:
        report.ok(tag, f"{label}（{len(got)} 类，id 4 = {got[4]}）")
    else:
        report.fail(tag, f"{label} 与权威表不一致：\n         期望 {canonical}\n         实际 {got}")


def check_classes_txt(report: Report, canonical: list[str]) -> None:
    for rel in ("classes.txt", "gen_data/classes.txt"):
        p = ROOT / rel
        if not p.exists():
            report.fail("A", f"{rel} 不存在")
            continue
        got = [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
        check_names_list(report, "A", rel, got, canonical)


def parse_yaml_names(path: Path) -> tuple[int | None, dict[int, str]]:
    """极简解析（不依赖 PyYAML）：只取 nc 和 names 块。"""
    nc = None
    names: dict[int, str] = {}
    in_names = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        m = re.match(r"^nc:\s*(\d+)\s*$", line)
        if m:
            nc = int(m.group(1))
            in_names = False
            continue
        if re.match(r"^names:\s*$", line):
            in_names = True
            continue
        if in_names:
            m = re.match(r"^\s+(\d+):\s*(\S+)\s*$", line)
            if m:
                names[int(m.group(1))] = m.group(2)
            elif re.match(r"^\S", line):
                in_names = False
    return nc, names


def check_data_c13(report: Report, canonical: list[str]) -> None:
    p = ROOT / "gen_data/data_c13.yaml"
    if not p.exists():
        report.fail("B", "gen_data/data_c13.yaml 不存在")
        return
    nc, names = parse_yaml_names(p)
    got = [names[i] for i in sorted(names)]
    if got != canonical:
        report.fail("B", f"data_c13.yaml 的 names 与权威表不一致：\n         实际 {got}")
    elif nc != len(canonical):
        report.fail("B", f"data_c13.yaml 的 nc={nc}，应为 {len(canonical)}")
    else:
        report.ok("B", f"data_c13.yaml（nc={nc}，names 一致）")


def check_python_table(report: Report, tag: str, rel: str, var: str, canonical: list[str]) -> None:
    p = ROOT / rel
    if not p.exists():
        report.fail(tag, f"{rel} 不存在")
        return
    assigns = literal_assigns(p)
    if var not in assigns:
        report.fail(tag, f"{rel} 里找不到模块级常量 {var}")
        return
    got = list(assigns[var])  # type: ignore[arg-type]
    check_names_list(report, tag, f"{rel}::{var}", [str(x) for x in got], canonical)


def check_server(report: Report, canonical: list[str]) -> None:
    p = ROOT / "server.py"
    if not p.exists():
        report.fail("C", "server.py 不存在")
        return
    assigns = literal_assigns(p)
    table = assigns.get("CLASS_NAMES_CANONICAL")
    if not isinstance(table, dict):
        report.fail("C", "server.py 里找不到字典常量 CLASS_NAMES_CANONICAL")
        return
    got = [str(table[i]) for i in sorted(table)]
    check_names_list(report, "C", "server.py::CLASS_NAMES_CANONICAL", got, canonical)


def check_wecom_ui(report: Report, canonical: list[str]) -> None:
    p = ROOT / "gen_data/wecom_ui.py"
    if not p.exists():
        report.fail("F", "gen_data/wecom_ui.py 不存在")
        return
    assigns = literal_assigns(p)
    nc = assigns.get("NUM_CLASSES")
    if nc != len(canonical):
        report.fail("F", f"NUM_CLASSES={nc!r}，应为 {len(canonical)}")

    cls = {k: v for k, v in assigns.items() if k.startswith("CLS_") and isinstance(v, int)}
    for name, want in EXPECTED_CONSTS.items():
        if name not in cls:
            report.fail("F", f"wecom_ui.py 缺少常量 {name}（应为 {want}）")
        elif cls[name] != want:
            report.fail("F", f"{name}={cls[name]}，应为 {want}")
    ids = sorted(cls.values())
    if ids != list(range(len(canonical))):
        report.fail("F", f"CLS_* 取值不是 0..{len(canonical) - 1} 的一一映射：{ids}")
    elif not report.failures:
        report.ok("F", f"wecom_ui.py（NUM_CLASSES={nc}，{len(cls)} 个 CLS_* 常量，CLS_LIST_ITEM=4）")


def iter_scan_files():
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        rel_parts = p.relative_to(ROOT).parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        if rel_parts[0] in SKIP_TOP:
            continue
        rel = p.relative_to(ROOT).as_posix()
        if p.name == "classes.txt" or p.suffix in (".py", ".md", ".yaml", ".yml"):
            yield p, rel


def check_old_names(report: Report) -> None:
    self_rel = "tools/check_class_consistency.py"
    hits: list[str] = []
    skipped: list[str] = []
    for p, rel in iter_scan_files():
        if rel in FROZEN_FILES:
            skipped.append(rel)
            continue
        if any(rel == d or rel.startswith(d + "/") for d in FROZEN_DIRS):
            if p.name in ("classes.txt", "data_synth.yaml"):
                skipped.append(rel)
            continue
        if rel == self_rel:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if any(n in line for n in OLD_NAMES):
                hits.append(f"{rel}:{i}: {line.strip()[:100]}")
    if hits:
        report.fail("G", "现役源码/文档里仍有旧类名：\n         " + "\n         ".join(hits))
    else:
        report.ok("G", f"现役源码/文档无旧类名（跳过 {len(skipped)} 个冻结资产）")


def check_generated_out(report: Report, canonical: list[str]) -> None:
    p = ROOT / CURRENT_OUT / "classes.txt"
    if not p.exists():
        report.note(f"H: {CURRENT_OUT}/classes.txt 不存在（还没生成当前口径的数据），跳过")
        return
    got = [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    check_names_list(report, "H", f"{CURRENT_OUT}/classes.txt", got, canonical)


def check_weights(report: Report, canonical: list[str], weight: str) -> None:
    try:
        from ultralytics import YOLO
    except Exception as exc:  # pragma: no cover
        report.fail("I", f"无法导入 ultralytics，跳过权重校验：{exc}")
        return
    p = Path(weight)
    if not p.is_absolute():
        p = ROOT / p
    model = YOLO(str(p))
    names = {int(k): str(v) for k, v in (model.names or {}).items()}
    got = [names[i] for i in sorted(names)]
    check_names_list(report, "I", f"权重 {p.name} 内嵌 model.names", got, canonical)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default=None,
                    help="可选：追加校验该权重内嵌的 model.names（需要 ultralytics）")
    args = ap.parse_args()

    canonical = read_canonical()
    print(f"权威类别表 {CANONICAL_SRC.relative_to(ROOT)}：{len(canonical)} 类，"
          f"id 4 = {canonical[4] if len(canonical) > 4 else '?'}\n")

    report = Report()
    check_classes_txt(report, canonical)
    check_data_c13(report, canonical)
    check_server(report, canonical)
    check_python_table(report, "D", "prepare_dataset.py", "CLASSES", canonical)
    check_python_table(report, "E", "annotate_wxwork15_folder.py", "DEFAULT_NAMES", canonical)
    check_wecom_ui(report, canonical)
    check_old_names(report)
    check_generated_out(report, canonical)
    if args.weights:
        check_weights(report, canonical, args.weights)

    print()
    if report.failures:
        print(f"[不一致] {len(report.failures)} 项：")
        for f in report.failures:
            print(f"  - {f}")
        return 1
    print("[通过] 类别名口径全仓一致：13 类，id 4 = list_item")
    return 0


if __name__ == "__main__":
    sys.exit(main())
