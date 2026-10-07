#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""企业微信桌面 UI 合成数据集生成器（离线，无网络）。

输出布局对齐 yolo-label-tool：同一目录下 stem.jpg + stem.txt（外加 classes.txt）。

示例:
  python synthesize.py --count 50 --out out_c13 \\
      --avatars assets/avatars --icons assets/icons \\
      --names assets/names.txt --messages assets/messages.txt --seed 0
"""
from __future__ import print_function
import argparse
import os
import random
import sys

try:
    import yaml
except ImportError:
    yaml = None

from wecom_ui import WeComSynthesizer, load_lines


def parse_args():
    p = argparse.ArgumentParser(description='Synthetic WeCom (企业微信) UI dataset generator')
    p.add_argument('--config', type=str, default=None, help='optional YAML config')
    p.add_argument('--count', type=int, default=50)
    p.add_argument('--out', type=str, default='out_c13')
    p.add_argument('--avatars', type=str, default='assets/avatars')
    p.add_argument('--icons', type=str, default='assets/icons')
    p.add_argument('--names', type=str, default='assets/names.txt')
    p.add_argument('--messages', type=str, default='assets/messages.txt')
    p.add_argument('--snippets', type=str, default='assets/snippets.txt')
    p.add_argument('--seed', type=int, default=0)
    p.add_argument('--format', type=str, default='jpg', choices=['jpg', 'png', 'jpeg'])
    p.add_argument('--quality', type=int, default=92)
    p.add_argument('--prefix', type=str, default='wxsyn')
    p.add_argument('--min-visible-h', type=int, default=4)
    p.add_argument('--min-area-ratio', type=float, default=5e-5)
    p.add_argument('--preset', type=str, default=None,
                   help='Comma-separated high-fidelity presets to cycle: '
                        'chat_narrow,chat_wide,chat_wide_groups,chat_dark,'
                        'contacts_profile,contacts_profile_dark,contacts_customers,'
                        'contacts_search,forward_dialog '
                        '(aliases: forward_dialog_recent, forward_dialog_search). '
                        'Example: --preset chat_narrow,contacts_profile --count 4')
    p.add_argument('--preset-random', action='store_true',
                   help='Pick a RANDOM preset per image (uniform) instead of cycling. '
                        'Without --preset, defaults to ALL presets = every page type '
                        'equally likely. Combines with --preset to restrict the pool.')
    p.add_argument('--list-presets', action='store_true',
                   help='Print available presets and exit')
    return p.parse_args()


def apply_config(args):
    if not args.config:
        return args
    if yaml is None:
        print('PyYAML not installed; ignoring --config', file=sys.stderr)
        return args
    with open(args.config, 'r') as f:
        cfg = yaml.safe_load(f) or {}
    # CLI defaults are already set; only fill from config if user left defaults?
    # Simpler: config overrides defaults, then we re-parse... Just apply keys present.
    mapping = {
        'count': 'count', 'out': 'out', 'avatars': 'avatars', 'icons': 'icons',
        'names': 'names', 'messages': 'messages', 'snippets': 'snippets',
        'seed': 'seed', 'image_format': 'format', 'jpg_quality': 'quality',
        'min_visible_h': 'min_visible_h', 'min_area_ratio': 'min_area_ratio',
    }
    for ck, ak in mapping.items():
        if ck in cfg:
            # argparse uses dest with underscore for dashed
            dest = ak.replace('-', '_')
            if dest == 'format':
                setattr(args, 'format', cfg[ck])
            elif dest == 'min_visible_h':
                setattr(args, 'min_visible_h', cfg[ck])
            elif dest == 'min_area_ratio':
                setattr(args, 'min_area_ratio', cfg[ck])
            else:
                setattr(args, dest if hasattr(args, dest) else ak, cfg[ck])
    return args


def main():
    args = parse_args()
    args = apply_config(args)

    base = os.path.dirname(os.path.abspath(__file__))

    def resolve(path):
        if os.path.isabs(path):
            return path
        # prefer cwd, else script dir
        if os.path.exists(path):
            return os.path.abspath(path)
        alt = os.path.join(base, path)
        return alt

    out_root = resolve(args.out)
    # 与 yolo-label-tool 一致：stem.jpg + stem.txt 同目录
    os.makedirs(out_root, exist_ok=True)

    avatars = resolve(args.avatars)
    icons = resolve(args.icons)
    names = load_lines(resolve(args.names))
    messages = load_lines(resolve(args.messages))
    snippets = load_lines(resolve(args.snippets))

    if not names:
        print('warning: empty names list', file=sys.stderr)
    if not os.path.isdir(avatars):
        print('warning: avatars dir missing: %s' % avatars, file=sys.stderr)
    if not os.path.isdir(icons):
        print('warning: icons dir missing: %s' % icons, file=sys.stderr)

    if args.list_presets:
        print('Available presets:')
        for name in WeComSynthesizer.PRESETS:
            print('  ' + name)
        print('Aliases:')
        for a, t in sorted(WeComSynthesizer.PRESET_ALIASES.items()):
            print('  %s -> %s' % (a, t))
        return

    rng = random.Random(args.seed)
    syn = WeComSynthesizer(
        avatars_dir=avatars,
        icons_dir=icons,
        names=names,
        messages=messages,
        snippets=snippets,
        min_visible_h=args.min_visible_h,
        min_area_ratio=args.min_area_ratio,
        rng=rng,
    )

    presets = None
    if args.preset:
        presets = [p.strip() for p in args.preset.split(',') if p.strip()]
        if not presets:
            print('error: empty --preset', file=sys.stderr)
            sys.exit(2)
        for p in presets:
            key = p.lower().replace('-', '_')
            key = WeComSynthesizer.PRESET_ALIASES.get(key, key)
            if key not in WeComSynthesizer.PRESETS:
                print('error: unknown preset %r' % p, file=sys.stderr)
                print('choose from: %s' % ', '.join(WeComSynthesizer.PRESETS), file=sys.stderr)
                sys.exit(2)

    ext = 'jpg' if args.format in ('jpg', 'jpeg') else 'png'
    # --preset-random 且未指定 --preset 时：默认池 = 全部 preset（所有页面等概率）
    if args.preset_random and not presets:
        presets = list(WeComSynthesizer.PRESETS)
    print('Generating %d images -> %s' % (args.count, out_root))
    if presets:
        mode = 'random (uniform)' if args.preset_random else 'cycle'
        print('  presets (%s): %s' % (mode, ', '.join(presets)))

    manifest = []
    for i in range(args.count):
        if presets:
            preset = rng.choice(presets) if args.preset_random else presets[i % len(presets)]
        else:
            preset = None
        img, lines, sc = syn.render(preset=preset)
        if preset:
            # readable name for hifi batch: chat_narrow_00000
            stem = '%s_%05d' % (preset.replace('-', '_'), i)
        else:
            stem = '%s_%05d' % (args.prefix, i)
        img_path = os.path.join(out_root, stem + '.' + ext)
        lbl_path = os.path.join(out_root, stem + '.txt')
        if ext == 'jpg':
            img.convert('RGB').save(img_path, quality=args.quality, optimize=True)
        else:
            img.save(img_path)
        with open(lbl_path, 'w') as f:
            f.write('\n'.join(lines) + ('\n' if lines else ''))
        manifest.append((stem, preset or '-', sc['page'], sc.get('input_typed')))
        if (i + 1) % 10 == 0 or i == 0 or i == args.count - 1 or presets:
            print('  [%d/%d] %s  %dx%d  labels=%d  page=%s nav=%s preset=%s' % (
                i + 1, args.count, stem, sc['w'], sc['h'], len(lines),
                sc['page'], 'wide' if sc['nav_wide'] else 'narrow',
                sc.get('preset') or preset or '-'))

    # 每图场景清单（chat 页记录输入区是否有文字）
    with open(os.path.join(out_root, 'manifest.csv'), 'w') as f:
        f.write('stem,preset,page,input_typed\n')
        for row in manifest:
            f.write('%s,%s,%s,%s\n' % row)

    # per-class label report (YOLO 框数量)
    from collections import Counter
    cls_counts = Counter()
    n_images = 0
    n_empty = 0
    for fn in sorted(os.listdir(out_root)):
        if not fn.endswith('.txt') or fn == 'classes.txt':
            continue
        # skip non-label sidecars if any
        stem, _ = os.path.splitext(fn)
        has_img = any(os.path.exists(os.path.join(out_root, stem + e))
                      for e in ('.jpg', '.jpeg', '.png'))
        if not has_img:
            continue
        n_images += 1
        path = os.path.join(out_root, fn)
        with open(path, 'r') as f:
            lines_in = [ln.strip() for ln in f if ln.strip()]
        if not lines_in:
            n_empty += 1
        for ln in lines_in:
            parts = ln.split()
            if not parts:
                continue
            try:
                cid = int(parts[0])
            except ValueError:
                continue
            cls_counts[cid] += 1

    # resolve names for report (may fill later from classes.txt)
    report_names = []
    classes_src_early = os.path.join(base, 'classes.txt')
    if os.path.exists(classes_src_early):
        with open(classes_src_early, 'r') as f:
            report_names = [ln.strip() for ln in f if ln.strip()]

    total_boxes = sum(cls_counts.values())
    report_lines = []
    report_lines.append('Synthetic WeCom label report')
    report_lines.append('out: %s' % out_root)
    report_lines.append('images: %d  (empty labels: %d)' % (n_images, n_empty))
    report_lines.append('total boxes: %d' % total_boxes)
    report_lines.append('')
    report_lines.append('%-4s  %-28s  %8s  %7s' % ('id', 'name', 'count', 'share'))
    report_lines.append('-' * 52)
    n_cls = max(len(report_names), (max(cls_counts.keys()) + 1) if cls_counts else 0)
    for cid in range(n_cls):
        name = report_names[cid] if cid < len(report_names) else ('class_%d' % cid)
        c = cls_counts.get(cid, 0)
        share = (100.0 * c / total_boxes) if total_boxes else 0.0
        report_lines.append('%-4d  %-28s  %8d  %6.1f%%' % (cid, name, c, share))
        # also flag missing classes
    missing = [cid for cid in range(n_cls) if cls_counts.get(cid, 0) == 0]
    report_lines.append('')
    if missing:
        report_lines.append('missing (0 boxes): %s' % ', '.join(
            '%d:%s' % (cid, report_names[cid] if cid < len(report_names) else cid)
            for cid in missing))
    else:
        report_lines.append('missing (0 boxes): none')

    report_txt = '\n'.join(report_lines) + '\n'
    report_path = os.path.join(out_root, 'label_report.txt')
    with open(report_path, 'w') as f:
        f.write(report_txt)
    # console summary
    print('')
    print(report_txt.rstrip())
    print('Wrote %s' % report_path)

    # write a tiny data yaml pointing at this out for convenience
    yaml_path = os.path.join(out_root, 'data_synth.yaml')
    classes_src = os.path.join(base, 'classes.txt')
    names_list = []
    if os.path.exists(classes_src):
        with open(classes_src, 'r') as f:
            names_list = [ln.strip() for ln in f if ln.strip()]
    classes_dst = os.path.join(out_root, 'classes.txt')
    if names_list:
        with open(classes_dst, 'w') as f:
            f.write('\n'.join(names_list) + '\n')

    with open(yaml_path, 'w') as f:
        f.write('# auto-generated; synthetic WeCom UI (flat: image + sidecar .txt)\n')
        f.write('path: %s\n' % out_root)
        f.write('train: .\n')
        f.write('val: .\n')
        f.write('nc: %d\n' % len(names_list))
        f.write('names:\n')
        for i, n in enumerate(names_list):
            f.write('  %d: %s\n' % (i, n))
    print('Done. Wrote %s (images+labels side-by-side)' % yaml_path)


if __name__ == '__main__':
    main()
