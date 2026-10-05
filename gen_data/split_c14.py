# -*- coding: utf-8 -*-
"""out_c14 -> splits_c14 (90/10 per preset), then validate labels + class histogram."""
import os, random, shutil, csv, sys
from collections import Counter, defaultdict
base = os.path.dirname(os.path.abspath(__file__))
src = os.path.join(base, 'out_c14'); dst = os.path.join(base, 'splits_c14')
names = [l.strip() for l in open(os.path.join(base, 'classes.txt')) if l.strip()]
assert len(names) == 14
if os.path.exists(dst):
    sys.exit('splits_c14 already exists')
groups = defaultdict(list)
for fn in sorted(os.listdir(src)):
    if fn.endswith('.jpg'):
        stem = fn[:-4]
        groups[stem.rsplit('_', 1)[0]].append(stem)
rng = random.Random(0)
split_of = {}
for g, stems in sorted(groups.items()):
    s = stems[:]; rng.shuffle(s)
    nv = max(1, round(len(s) * 0.10))
    for i, st in enumerate(s):
        split_of[st] = 'val' if i < nv else 'train'
for sp in ('train', 'val'):
    for sub in ('images', 'labels'):
        os.makedirs(os.path.join(dst, sp, sub))
typed = {}
with open(os.path.join(src, 'manifest.csv')) as f:
    for r in csv.DictReader(f):
        typed[r['stem']] = r['input_typed']
hist = {'train': Counter(), 'val': Counter()}
nimg = Counter(); bad = []; pages = defaultdict(Counter); chat_typed = defaultdict(Counter)
for st, sp in sorted(split_of.items()):
    shutil.copy2(os.path.join(src, st + '.jpg'), os.path.join(dst, sp, 'images', st + '.jpg'))
    shutil.copy2(os.path.join(src, st + '.txt'), os.path.join(dst, sp, 'labels', st + '.txt'))
    nimg[sp] += 1
    g = st.rsplit('_', 1)[0]; pages[sp][g] += 1
    if g.startswith('chat'):
        chat_typed[sp][typed.get(st)] += 1
    for ln in open(os.path.join(src, st + '.txt')):
        p = ln.split()
        if not p: continue
        c = int(p[0]); vals = [float(v) for v in p[1:]]
        if not (0 <= c < 14) or len(vals) != 4 or any(v < 0 or v > 1 for v in vals):
            bad.append((st, ln.strip()))
        hist[sp][c] += 1
out = []
out.append('images: train=%d val=%d' % (nimg['train'], nimg['val']))
for sp in ('train', 'val'):
    out.append('%s pages: %s' % (sp, dict(sorted(pages[sp].items()))))
    out.append('%s chat input_typed: %s' % (sp, dict(chat_typed[sp])))
out.append('%-3s %-22s %7s %6s' % ('id', 'name', 'train', 'val'))
for i, n in enumerate(names):
    out.append('%-3d %-22s %7d %6d' % (i, n, hist['train'][i], hist['val'][i]))
out.append('max class id: train=%s val=%s' % (max(hist['train']), max(hist['val'])))
out.append('missing train: %s  missing val: %s' % ([i for i in range(14) if not hist['train'][i]], [i for i in range(14) if not hist['val'][i]]))
out.append('bad label lines (id>=14 / bad coords): %d %s' % (len(bad), bad[:5]))
txt = '\n'.join(out); print(txt)
open(os.path.join(dst, 'split_report.txt'), 'w', encoding='utf-8').write(txt + '\n')
