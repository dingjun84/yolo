# -*- coding: utf-8 -*-
"""Render c13 preview images with label boxes (chat empty / chat typed / contacts / search / customers)."""
import os, random, sys
from PIL import ImageDraw
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wecom_ui import WeComSynthesizer, load_lines, _load_font

base = os.path.dirname(os.path.abspath(__file__))
names = [l.strip() for l in open(os.path.join(base, 'classes.txt')) if l.strip()]
out = os.path.join(base, 'preview_c13')
os.makedirs(out, exist_ok=True)
A = lambda p: os.path.join(base, 'assets', p)
syn = WeComSynthesizer(A('avatars'), A('icons'), load_lines(A('names.txt')), load_lines(A('messages.txt')),
                       load_lines(A('snippets.txt')), rng=random.Random(int(sys.argv[1]) if len(sys.argv) > 1 else 7))
font = _load_font(11)
COL = [(255,0,0),(0,160,0),(0,0,255),(200,120,0),(160,0,160),(0,150,150),(120,120,0),(255,80,160),(0,100,255),(255,140,0),(100,0,200),(0,200,100),(200,0,60),(60,60,60)]
jobs = [('chat_empty', 'chat_wide', False), ('chat_typed', 'chat_narrow', True),
        ('chat_typed_wide', 'chat_wide', True), ('chat_dark_empty', 'chat_dark', False),
        ('contacts_profile', 'contacts_profile', None), ('contacts_search', 'contacts_search', None),
        ('contacts_customers', 'contacts_customers', None)]
for tag, preset, typed in jobs:
    sc = syn.make_scenario(preset, jitter=True)
    if typed is not None:
        sc['input_typed'] = typed
    img, lines, sc = syn.render(scenario=sc)
    img.save(os.path.join(out, tag + '_raw.png'))
    W, H = img.size
    d = ImageDraw.Draw(img)
    for ln in lines:
        c, xc, yc, w, h = ln.split(); c = int(c)
        xc, yc, w, h = float(xc)*W, float(yc)*H, float(w)*W, float(h)*H
        x0, y0, x1, y1 = xc-w/2, yc-h/2, xc+w/2, yc+h/2
        d.rectangle([x0, y0, x1, y1], outline=COL[c % len(COL)], width=2)
        d.text((x0+2, max(0, y0-12)), '%d %s' % (c, names[c]), fill=COL[c % len(COL)], font=font)
    img.save(os.path.join(out, tag + '.png'))
    print(tag, W, H, 'labels=%d' % len(lines), 'typed=%s' % sc.get('input_typed'))
