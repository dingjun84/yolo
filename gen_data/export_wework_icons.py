#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_wework_icons.py — 从企业微信 Mac 客户端里导出界面图标（矢量优先）

背景：企业微信官方**没有**发布桌面端图标下载。官方只发布 WeUI for Work
（https://weui.io/work/ ，移动端 18 个 glyph）。真正的桌面导航图标打包在客户端
安装包的 Assets.car 里。

本脚本只用 macOS 自带工具，把指定名额的图标抠出来：

  1) assetutil -n <资源名> -o tmp.car <Assets.car>   # 把 car 裁剪成只剩这一个资源
  2) 在裁剪结果里按  %PDF … %%EOF  切片                # 矢量资源在 car 里是明文存放的
                                                     #（已实测：main car 内 3130 个未压缩 PDF）
  3) sips -s format png <x.pdf> --out <x.png>        # 光栅化，1x = 资源原始 pt 尺寸

不需要 Xcode，不需要第三方库（只有 --white 需要 Pillow）。

用法
----
  # 看内置映射表 + 每个资源在你这台机器上是否可用
  python export_wework_icons.py --list

  # 导出整套左侧导航图标（原色 + 选中态的白色版），并保留矢量母版
  python export_wework_icons.py --out assets/icons_wecom --keep-pdf --white selected

  # 按资源名导出，输出名同名
  python export_wework_icons.py --names icon_tab_calendar,icon_todo,icon_expand_more

  # 自定义映射
  python export_wework_icons.py --map my_more=icon_expand_more --map my_cal=main_calendar_20 --out /tmp/ic

参数
----
  --app PATH        企业微信.app 或直接给 Assets.car（默认 /Applications/企业微信.app）
  --out DIR         输出目录（默认 assets/icons_wecom）
  --preset NAME     预设：nav（默认）
  --names A,B,C     直接给资源名，输出名 = 资源名
  --map OUT=ASSET   追加/覆盖映射，可重复
  --appearance X    X = light（默认）| dark；同名资源有浅/深两版时取哪一版
  --white X         X = selected（默认）| all | none；额外输出白色版（<名>_white.png）
  --size N          输出边长 N 像素（默认保持原始尺寸；放大是重采样，会糊，慎用）
  --keep-pdf        把矢量母版另存到 <out>/_pdf/
  --overwrite       允许覆盖已存在的输出文件
  --list            只打印映射表与可用性，不导出

注意
----
  * 图标是微信官方版权素材，仅限自用/内部（例如合成训练数据），不要对外分发。
  * 少数资源只有位图版本（car 里存的是 lzfse 压缩位图，不是明文 PDF），例如
    icon_tab_document_*、icon_tab_voipmt_*。本脚本会跳过并列出它可用的 rendition，
    需要的话换用矢量版本（见 nav 预设里"会议"改用了 main_meeting_20）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ASSETUTIL = "/usr/bin/assetutil"
SIPS = "/usr/bin/sips"

PDF_MAGIC = b"%PDF"
PDF_EOF = b"%%EOF"

# ---------------------------------------------------------------------------
# 预设：左侧导航区。（输出名, 资源名, 说明）
# 输出名对齐 gen_data/wecom_ui.py 里 _draw_left_nav 用到的文件名。
# ---------------------------------------------------------------------------
# 命名规律（本机 5.0.7 实测）：
#   *_normal   未选中，22pt 线稿        *_selected  选中，20pt 实心
#   *_expand_* 宽栏（展开态）16pt       main_*      非 tab 栏图标
# 资源名的"真实图案"看 rendition 名更准，例如 nav_docs ← wedoc_fill_22.pdf。
NAV_PRESET = [
    # 消息
    ("nav_chat",                 "icon_tab_conversation_normal",          "消息 22pt"),
    ("nav_chat_selected",        "icon_tab_conversation_selected",        "消息 选中 20pt"),
    ("nav_chat_expand",          "icon_tab_conversation_expand_normal",   "消息 宽栏 16pt"),
    ("nav_chat_expand_selected", "icon_tab_conversation_expand_selected", "消息 宽栏选中 16pt"),
    # 邮件
    ("nav_mail",                 "icon_tab_exmail_normal",                "邮件 22pt"),
    # icon_tab_exmail_selected 只有位图，退用 side_nav_mailbox_selected_24；
    # 若坚持 16pt 可用 icon_tab_exmail_expand_selected（会明显偏小）
    ("nav_mail_selected",        "icon_mail_pressed",                     "邮件 选中 24pt"),
    # 文档（icon_tab_document_* 只有位图，这里用腾讯文档 wedoc 矢量）
    ("nav_docs",                 "icon_tab_mail_document_normal",         "文档 22pt"),
    ("nav_docs_selected",        "icon_tab_mail_document_selected",       "文档 选中 20pt"),
    # 通讯录
    ("nav_contacts",             "icon_tab_organization_normal",          "通讯录 22pt"),
    ("nav_contacts_selected",    "icon_tab_organization_selected",        "通讯录 选中 20pt"),
    # 日程
    ("nav_calendar",             "icon_tab_calendar",                     "日程 22pt"),
    ("nav_calendar_selected",    "icon_tab_calendar_press",               "日程 选中 20pt"),
    # 待办 / 会议
    ("nav_todo",                 "icon_todo",                             "待办 22pt"),
    ("nav_meeting",              "main_meeting_20",                       "会议 20pt"),
    ("nav_meeting_16",           "main_meeting_16",                       "会议 宽栏 16pt"),
    # 工作台
    ("nav_workbench",            "icon_tab_workplace_normal",             "工作台 22pt"),
    ("nav_workbench_selected",   "icon_tab_workplace_selected",           "工作台 选中 20pt"),
    # 低频项（智能表格 / 会话标签）
    ("nav_smart",                "icon_tab_smart_off",                    "智能表格 22pt"),
    ("nav_smart_selected",       "icon_tab_smart_on",                     "智能表格 选中 20pt"),
    ("nav_convtag",              "icon_tab_convtag_normal",               "会话标签 22pt"),
    ("nav_convtag_selected",     "icon_tab_convtag_selected",             "会话标签 选中 20pt"),
    # 底部"更多"
    ("nav_more",                 "icon_more_22",                          "更多 ⋯ 22pt"),
    # 选中态的白色图标：客户端导航"蓝底胶囊 + 白图标"用这两个名额补齐
    # （其它项的白色版由 --white 从各自的 *_selected 派生，见下）
    ("nav_meeting_selected_white", "main_meeting_16_white",               "会议 选中（原生白色矢量 16pt）"),
    ("nav_todo_selected_white",    "icon_todo",                           "待办 选中（无专用资源，用同字形漂白 22pt）"),
]

PRESETS = {"nav": NAV_PRESET}


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def die(msg: str, code: int = 2):
    print(f"错误：{msg}", file=sys.stderr)
    sys.exit(code)


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def resolve_car(app: str) -> str:
    """把 --app 归一化成 Assets.car 路径。"""
    p = os.path.expanduser(app)
    if p.endswith(".car"):
        if not os.path.isfile(p):
            die(f"找不到 car 文件：{p}")
        return p
    # .app 包，或 .app 外面一层目录
    cands = [
        os.path.join(p, "Contents", "Resources", "Assets.car"),
    ]
    if os.path.isdir(p) and not p.endswith(".app"):
        for name in sorted(os.listdir(p)):
            if name.endswith(".app"):
                cands.append(os.path.join(p, name, "Contents", "Resources", "Assets.car"))
    for c in cands:
        if os.path.isfile(c):
            return c
    die(f"在 {p} 里找不到 Contents/Resources/Assets.car；用 --app 指定 .app 或 .car")


def read_car_info(car: str) -> dict[str, list[dict]]:
    """assetutil --info → {资源名: [rendition, ...]}（只在没给 --names 时用得上）。"""
    r = run([ASSETUTIL, "--info", car])
    if r.returncode != 0:
        die(f"assetutil --info 失败：{r.stderr.strip()}")
    try:
        rows = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        die(f"assetutil --info 输出不是 JSON：{e}")
    by: dict[str, list[dict]] = {}
    for a in rows:
        n = a.get("Name")
        if n:
            by.setdefault(n, []).append(a)
    return by


def raw_pdf_renditions(entries: list[dict]) -> list[str]:
    """按元数据顺序取出"明文 PDF"型 rendition 的名字。

    car 里同一资源的 rendition 有两类：
      * 有 Compression=lzfse 的位图（含 1x/2x 缩放）
      * 没有 Compression、RenditionName 以 .pdf 结尾的矢量原文 ← 我们要的
    """
    return [str(a.get("RenditionName", ""))
            for a in entries
            if not a.get("Compression") and str(a.get("RenditionName", "")).lower().endswith(".pdf")]


def raw_pdf_sizes(entries: list[dict]) -> list[int]:
    """与 raw_pdf_renditions 对齐的长度（SizeOnDisk）列表。"""
    return [int(a.get("SizeOnDisk") or 0)
            for a in entries
            if not a.get("Compression") and str(a.get("RenditionName", "")).lower().endswith(".pdf")]


def thin(car: str, name: str, dst: str) -> int:
    """把 car 裁剪成只保留 name 这个资源；返回剩余资源数（-1 表示失败）。"""
    if os.path.exists(dst):
        os.remove(dst)
    r = run([ASSETUTIL, "-n", name, "-o", dst, car])
    if r.returncode != 0 or not os.path.exists(dst):
        return -1
    # 正常输出形如：carutil: found 13236 assets that needed to be removed
    return os.path.getsize(dst)


def carve_pdfs(blob_path: str) -> list[bytes]:
    """从裁剪出的 car 里按 %PDF…%%EOF 切出矢量原文（保持文件内顺序）。"""
    data = open(blob_path, "rb").read()
    out, i = [], 0
    while True:
        j = data.find(PDF_MAGIC, i)
        if j < 0:
            break
        e = data.find(PDF_EOF, j)
        if e < 0:
            break
        out.append(data[j:e + len(PDF_EOF)])
        i = e + len(PDF_EOF)
    return out


def pick_appearance(rendition_names: list[str], want: str) -> int:
    """同名资源有浅/深两版时，选出想要那一版的序号。"""
    if len(rendition_names) <= 1:
        return 0
    want = want.lower()
    pos = ("dark", "darkmode") if want == "dark" else ("light",)
    neg = ("light",) if want == "dark" else ("dark", "darkmode")
    for i, rn in enumerate(rendition_names):
        low = rn.lower()
        if any(t in low for t in pos) and not any(t in low for t in neg):
            return i
    # 名字里没写：默认顺序是 浅色在前、深色在后（本机 5.0.7 实测）
    return 1 if want == "dark" and len(rendition_names) > 1 else 0


def size_overhead(carved: list[bytes], info_sizes: list[int]) -> int:
    """算出 car 里 "SizeOnDisk - 实际 PDF 字节数" 的固定开销。

    裁剪后的 car 里往往不止目标那一个矢量资源（同族/同页的 PDF 会被一起留下），
    所以不能"取第 1 个 PDF"。可靠的做法是按长度对号：矢量资源的 SizeOnDisk 恒比
    PDF 原文多一个固定开销（本机 5.0.7 实测 = 225 字节），这里用投票法把它推出来，
    避免写死魔数。
    """
    lengths = {len(b) for b in carved}
    best, best_hits = 0, -1
    for s in {x for x in info_sizes if x}:
        for l in lengths:
            d = s - l
            if d < 0:
                continue
            hits = sum(1 for s2 in info_sizes if (s2 - d) in lengths)
            if hits > best_hits:
                best, best_hits = d, hits
    return best


MEDIABOX_RE = re.compile(rb"MediaBox\s*\[([^\]]*)\]")


def pdf_mediabox(pdf: bytes) -> tuple[int, int] | None:
    """读出 PDF 的 MediaBox（= sips 光栅化后的像素尺寸）。"""
    m = MEDIABOX_RE.search(pdf)
    if not m:
        return None
    nums = re.findall(rb"-?\d+(?:\.\d+)?", m.group(1))
    if len(nums) != 4:
        return None
    try:
        x0, y0, x1, y1 = (float(n) for n in nums)
    except ValueError:
        return None
    return (round(x1 - x0), round(y1 - y0))


def expected_dims(entries: list[dict]) -> tuple[int, int] | None:
    """从同一资源的位图 rendition 推断图标应有的 pt 尺寸（取 1x 那一版）。

    矢量资源本体在元数据里 PixelWidth/PixelHeight 是空的，但它的位图兄弟
    （同名的 1x/2x 压缩条目）带着真实尺寸，例如 checkmark_circle_fill_22.pdf
    的位图条目是 22x22 / 44x44 → 期望 22pt。
    """
    dims = []
    for a in entries:
        w, h = a.get("PixelWidth"), a.get("PixelHeight")
        if isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0:
            dims.append((w, h))
    if not dims:
        return None
    square = [d for d in dims if d[0] == d[1]]
    return min(square or dims, key=lambda d: d[0] * d[1])


def choose_by_size(carved: list[bytes], target_size: int, overhead: int,
                   want_dims: tuple[int, int] | None = None) -> tuple[int, str]:
    """挑出目标 PDF 的序号，返回 (序号, 说明)；挑不到返回 (-1, "")。

    只按 SizeOnDisk 对号会在"两个 PDF 字节数完全一样"时撞车
    （实测 icon_todo：16x16 与 22x22 都是 3738 字节），所以撞车时再用
    PDF 自己的 MediaBox 尺寸消歧。
    """
    same_len = [i for i, b in enumerate(carved) if len(b) == target_size - overhead]
    if not same_len:
        if want_dims:
            by_dim = [i for i, b in enumerate(carved) if pdf_mediabox(b) == want_dims]
            if by_dim:
                return by_dim[0], f"长度没对上，改用 MediaBox{want_dims} 选中第 {by_dim[0] + 1} 个"
        return -1, ""
    if len(same_len) == 1 or not want_dims:
        return same_len[0], ""
    exact = [i for i in same_len if pdf_mediabox(carved[i]) == want_dims]
    if exact:
        return (exact[0],
                f"{len(same_len)} 个候选字节数相同，按 MediaBox{want_dims} 选中第 {exact[0] + 1} 个")
    return (same_len[0],
            f"{len(same_len)} 个候选字节数相同、MediaBox 均不符，退回第 {same_len[0] + 1} 个")


def to_png(pdf: bytes, out_png: str, size: int | None) -> bool:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf)
        tmp_pdf = f.name
    try:
        r = run([SIPS, "-s", "format", "png", tmp_pdf, "--out", out_png])
        if r.returncode != 0 or not os.path.exists(out_png):
            return False
        if size:
            run([SIPS, "-z", str(size), str(size), out_png])
        return True
    finally:
        os.remove(tmp_pdf)


def make_white(png_path: str, inplace: bool = False) -> str:
    """把 PNG 里所有不透明像素刷成白色，保留 alpha —— 用于"蓝底胶囊 + 白图标"的选中态。

    返回 "written" / "already" / "no-pillow"：
      * "already"   原图本身就是白的（来源就是白色矢量，如 main_meeting_16_white），
                    不做处理，也就不会冒出 <名>_white_white.png
      * inplace=False（默认）派生 <名>_white.png；inplace=True 直接就地改（用于
        预设里名字已带 _white 的名额，它本身就该是白图）
    """
    try:
        from PIL import Image
    except ImportError:
        return "no-pillow"
    src = Image.open(png_path).convert("RGBA")
    px = src.load()
    w, h = src.size
    opaque = [px[x, y] for y in range(h) for x in range(w) if px[x, y][3] > 200]
    if opaque and min(min(p[:3]) for p in opaque) >= 250:
        return "already"                      # 本来就是白的
    white = (255, 255, 255)
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a:
                px[x, y] = (*white, a)
    src.save(png_path if inplace else png_path[:-4] + "_white.png")
    return "written"


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def build_jobs(args, info: dict[str, list[dict]]) -> tuple[list[tuple[str, str]], list[str]]:
    jobs: list[tuple[str, str]] = []          # (输出名, 资源名)
    notes: list[str] = []

    if args.preset:
        for out_name, asset, _desc in PRESETS[args.preset]:
            if info and asset not in info:
                notes.append(f"{asset} 不在这个 car 里，跳过（{out_name}）")
                continue
            jobs.append((out_name, asset))
    for nm in (args.names or "").split(","):
        nm = nm.strip()
        if nm:
            if info and nm not in info:
                notes.append(f"{nm} 不在这个 car 里，跳过")
                continue
            jobs.append((nm, nm))
    for m in args.map or []:
        if "=" not in m:
            die(f"--map 需要 OUT=ASSET 形式，收到：{m}")
        out_name, asset = m.split("=", 1)
        jobs.append((out_name.strip(), asset.strip()))

    # 去重（后者覆盖前者，方便用 --map 换掉预设里的某一条）
    seen: dict[str, str] = {}
    for out_name, asset in jobs:
        seen[out_name] = asset
    return list(seen.items()), notes


def main() -> int:
    ap = argparse.ArgumentParser(
        description="从企业微信 Mac 客户端 Assets.car 导出界面图标（矢量优先）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--app", default="/Applications/企业微信.app",
                    help="企业微信.app 或 Assets.car（默认 /Applications/企业微信.app）")
    ap.add_argument("--out", default="assets/icons_wecom", help="输出目录")
    ap.add_argument("--preset", default="nav", choices=sorted(PRESETS),
                    help="预设映射（默认 nav；给 --names/--map 时仍会叠加）")
    ap.add_argument("--names", default="", help="逗号分隔的资源名，输出名=资源名")
    ap.add_argument("--map", action="append", metavar="OUT=ASSET",
                    help="自定义映射，可重复")
    ap.add_argument("--appearance", default="light", choices=["light", "dark"],
                    help="同名资源有浅/深两版时取哪一版（默认 light）")
    ap.add_argument("--white", default="selected", choices=["selected", "all", "none"],
                    help="额外输出白色版 <名>_white.png（默认只对含 selected 的项）")
    ap.add_argument("--size", type=int, default=0, help="输出边长像素（默认原始尺寸）")
    ap.add_argument("--keep-pdf", action="store_true", help="矢量母版另存 <out>/_pdf/")
    ap.add_argument("--overwrite", action="store_true", help="允许覆盖已有文件")
    ap.add_argument("--list", action="store_true", help="只打印映射表与可用性，不导出")
    args = ap.parse_args()

    for tool in (ASSETUTIL, SIPS):
        if not os.path.exists(tool):
            die(f"找不到系统工具 {tool}（本脚本依赖 macOS 自带的 assetutil / sips）")

    car = resolve_car(args.app)
    print(f"car  : {car}")
    print(f"      {os.path.getsize(car) / 1e6:.1f} MB")

    print("读取资源目录 …")
    info = read_car_info(car)
    print(f"      共 {len(info)} 个命名资源")

    jobs, notes = build_jobs(args, info)

    # --list：只报告可用性
    if args.list:
        print("\n映射表（输出名 → 资源名 | 矢量/位图 | rendition）：")
        for out_name, asset in jobs:
            rends = raw_pdf_renditions(info.get(asset, []))
            dims = expected_dims(info.get(asset, []))
            if rends:
                kind = f"矢量 x{len(rends)}" + (f"，{dims[0]}pt" if dims else "")
            else:
                kind = "位图（本脚本跳过）"
            print(f"  {out_name:<26} ← {asset:<34} {kind}")
            if rends:
                for rn in rends:
                    print(f"      · {rn}")
        for n in notes:
            print(f"  ! {n}")
        return 0

    os.makedirs(args.out, exist_ok=True)
    if args.keep_pdf:
        os.makedirs(os.path.join(args.out, "_pdf"), exist_ok=True)

    tmpdir = tempfile.mkdtemp(prefix="wework_icons_")
    ok, skipped, tint_failed = [], [], False
    try:
        for idx, (out_name, asset) in enumerate(jobs, 1):
            entries = info.get(asset, [])
            rends = raw_pdf_renditions(entries)
            sizes = raw_pdf_sizes(entries)
            car_tmp = os.path.join(tmpdir, f"{idx}.car")

            if not rends:
                skipped.append((out_name, asset,
                                [str(a.get("RenditionName", "?")) for a in entries]))
                print(f"[{idx}/{len(jobs)}] {out_name:<26} 跳过：只有位图版本")
                continue

            if thin(car, asset, car_tmp) < 0:
                skipped.append((out_name, asset, ["assetutil 裁剪失败"]))
                print(f"[{idx}/{len(jobs)}] {out_name:<26} 跳过：assetutil 裁剪失败")
                continue

            pdfs = carve_pdfs(car_tmp)
            if not pdfs:
                skipped.append((out_name, asset, ["裁剪结果里没有明文 PDF"]))
                print(f"[{idx}/{len(jobs)}] {out_name:<26} 跳过：没有明文 PDF")
                continue

            k = pick_appearance(rends, args.appearance)          # 用元数据里的 light/dark 名字选版本
            target_size = sizes[k]
            want_dims = expected_dims(entries)

            # 裁剪后的 car 里通常还留着同族资源的 PDF，所以按长度对号而不是取第 1 个
            thin_info = read_car_info(car_tmp)
            thin_sizes = [s for rs in thin_info.values() for s in raw_pdf_sizes(rs)]
            overhead = size_overhead(pdfs, thin_sizes)
            j, why = choose_by_size(pdfs, target_size, overhead, want_dims)
            if j < 0:
                j = min(k, len(pdfs) - 1)
                notes.append(f"{asset}：按长度没对上（SizeOnDisk={target_size}），"
                             f"退回取第 {j + 1} 个 PDF，请开图确认")
            elif why:
                notes.append(f"{asset}：{why}")
            pdf = pdfs[j]

            out_png = os.path.join(args.out, out_name + ".png")
            if os.path.exists(out_png) and not args.overwrite:
                print(f"[{idx}/{len(jobs)}] {out_name:<26} 已存在，跳过（--overwrite 可覆盖）")
                continue
            if not to_png(pdf, out_png, args.size or None):
                skipped.append((out_name, asset, ["sips 光栅化失败"]))
                print(f"[{idx}/{len(jobs)}] {out_name:<26} 跳过：sips 失败")
                continue

            if args.keep_pdf:
                with open(os.path.join(args.out, "_pdf", out_name + ".pdf"), "wb") as f:
                    f.write(pdf)

            # 白色处理：名字带 _white 的名额（预设里显式指定）就地刷白；
            # 其余按 --white 派生一份 <名>_white.png
            if out_name.endswith("_white"):
                st = make_white(out_png, inplace=True)
            elif args.white == "all" or (args.white == "selected" and "selected" in out_name):
                st = make_white(out_png)
            else:
                st = "skip"
            extra = " +_white" if st == "written" else ""
            if st == "no-pillow":
                tint_failed = True

            print(f"[{idx}/{len(jobs)}] {out_name:<26} ← {asset}  ({rends[k]}){extra}")
            ok.append(out_name)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print(f"\n完成：{len(ok)} 张 → {os.path.abspath(args.out)}")
    if args.keep_pdf and ok:
        print(f"      矢量母版 → {os.path.abspath(os.path.join(args.out, '_pdf'))}")
    if tint_failed:
        print("      提示：没装 Pillow，白色版没生成（pip install pillow 后重跑 --white）")
    if skipped:
        print("\n跳过（car 里只有位图版本，本脚本只处理明文 PDF）：")
        for out_name, asset, rends in skipped:
            print(f"  {out_name:<26} ← {asset}")
            for rn in rends[:4]:
                print(f"        · {rn}")
        print("  → 找一个矢量替代，例如“会议”用 main_meeting_20 / main_meeting_16。")
    for n in notes:
        print(f"  ! {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
