#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit nav label cy variance for classes 1 (chat) and 2 (contacts).

Usage:
  python tools/audit_nav_cy.py gen_data/out_navvar_1000
  python tools/audit_nav_cy.py gen_data/preview_navvar  # if labels sit next to jpg
"""
from __future__ import print_function
import os, sys, math
from collections import defaultdict

def stddev(xs):
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / float(len(xs))
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))

def main():
    root = sys.argv[1] if len(sys.argv) > 1 else 'gen_data/out_navvar_1000'
    # support flat out (stem.jpg + stem.txt) or YOLO split (images/ + labels/)
    pairs = []
    if os.path.isdir(os.path.join(root, 'images')) and os.path.isdir(os.path.join(root, 'labels')):
        for fn in sorted(os.listdir(os.path.join(root, 'images'))):
            if not fn.lower().endswith(('.jpg', '.png', '.jpeg')):
                continue
            stem = os.path.splitext(fn)[0]
            lp = os.path.join(root, 'labels', stem + '.txt')
            if os.path.isfile(lp):
                pairs.append((os.path.join(root, 'images', fn), lp))
    else:
        for fn in sorted(os.listdir(root)):
            if not fn.lower().endswith(('.jpg', '.png', '.jpeg')):
                continue
            stem = os.path.splitext(fn)[0]
            lp = os.path.join(root, stem + '.txt')
            if os.path.isfile(lp):
                pairs.append((os.path.join(root, fn), lp))
            # also try labels/ sibling
            lp2 = os.path.join(root, 'labels', stem + '.txt')
            if os.path.isfile(lp2):
                pairs.append((os.path.join(root, fn), lp2))

    cy = defaultdict(list)
    for ip, lp in pairs:
        # need image height for pixel cy; use YOLO yc (normalized) if no PIL,
        # but report both norm and assume we can get size via JPEG header lightly
        try:
            from PIL import Image
            H = Image.open(ip).size[1]
        except Exception:
            H = 1
            # fall back to normalized yc * 1 → report as normalized
        for ln in open(lp):
            p = ln.split()
            if len(p) < 5:
                continue
            c = int(p[0])
            if c not in (1, 2, 12):
                continue
            yc = float(p[2])
            cy[c].append(yc * H if H > 1 else yc)

    print('images_with_labels=%d' % len(pairs))
    for c, name in ((1, 'nav_chat_icon'), (2, 'nav_contacts_icon'), (12, 'nav_groups_icon')):
        xs = cy[c]
        if not xs:
            print('cls %d %s: n=0' % (c, name))
            continue
        print('cls %d %s: n=%d mean=%.2f stddev=%.2f min=%.2f max=%.2f' % (
            c, name, len(xs), sum(xs)/len(xs), stddev(xs), min(xs), max(xs)))
        print('  cy_sample=', [round(v, 1) for v in xs[:30]])

if __name__ == '__main__':
    main()
