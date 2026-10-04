# -*- coding: utf-8 -*-
"""企业微信桌面 UI 合成：布局、绘制、YOLO 标签框。

纯 Pillow，无网络。类别 ID 必须与父目录 classes.txt 一致：
  0 self_avatar  1 nav_chat_icon  2 nav_contacts_icon  3 search_bar
  4 contact_item  5 message_input  6 send_button  7 conversation_item
  8 incoming_bubble  9 outgoing_bubble  10 input_bar
  11 single_chat（单聊）  12 group_chat（群聊）
  13 contact_send_message（联系人详情「发消息」）
"""
from __future__ import print_function, division
import os
import random
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ---------------------------------------------------------------------------
# 类别
# ---------------------------------------------------------------------------
CLS_SELF_AVATAR = 0
CLS_NAV_CHAT = 1
CLS_NAV_CONTACTS = 2
CLS_SEARCH_BAR = 3
CLS_CONTACT_ITEM = 4
CLS_MESSAGE_INPUT = 5
CLS_SEND_BUTTON = 6
CLS_CONVERSATION_ITEM = 7
CLS_INCOMING = 8
CLS_OUTGOING = 9
CLS_INPUT_BAR = 10
CLS_SINGLE_CHAT = 11  # 单聊
CLS_GROUP_CHAT = 12  # 群聊
CLS_CONTACT_SEND_MESSAGE = 13  # 联系人详情「发消息」
CLS_NAV_GROUPS = 14  # 导航「分组」图标

# ---------------------------------------------------------------------------
# 配色（对齐官方「应用深色模式色值表」+ 桌面截图校准）
# 浅色为主；深色列用于 contacts_profile dark。
# https://developer.work.weixin.qq.com/document/path/94600
# ---------------------------------------------------------------------------
C_NAV_BG = (218, 232, 247)            # 截图侧栏 ~#DAE8F7
C_WIN_BG = (245, 246, 247)            # gray_blue_97_bg #F5F6F7
C_LIST_BG = (240, 243, 247)           # 会话列表底 ~#F0F3F7
C_CHAT_BG = (245, 247, 250)           # 聊天区
C_TITLE_BG = (255, 255, 255)
C_SEP = (230, 232, 235)               # 分割线（≈ black_a7）
C_SELECTED_NAV = (200, 222, 247)      # 导航选中浅蓝底 ~#C8DEF7（非实心蓝）
C_SELECTED_NAV_FG = (38, 126, 240)    # blue_btn #267EF0（选中图标/文字）
C_NAV_ICON_GRAY = (98, 114, 138)       # 未选中导航图标 ~#62728A（非纯黑）
C_NAV_ICON_GRAY_DARK = (160, 168, 178) # 深色主题未选中图标
C_SELECTED_LIST = (38, 126, 240)      # blue_btn #267EF0 会话行选中实心
C_SELECTED_LIST_TEXT = (255, 255, 255)
C_TEXT = (30, 30, 30)
C_TEXT_SEC = (153, 153, 153)          # gray_60 #999999
C_TEXT_PLACEHOLDER = (170, 175, 185)
C_SEARCH_BG = (235, 237, 240)         # gray_blue_94_bg #EBEDF0
C_INCOMING = (255, 255, 255)          # white_bubble_bg
C_INCOMING_ALT = (235, 235, 235)      # 偶发灰气泡
C_OUTGOING = (201, 231, 255)          # blue_bubble_bg #C9E7FF
C_BADGE = (255, 70, 80)               # red_notification #FF4650
C_BADGE_WEUI = (244, 53, 48)          # WeUI badge #F43530（备用）
C_SEND_BG = (235, 237, 240)
C_SEND_TEXT = (153, 153, 153)
C_SEND_BG_ACTIVE = (38, 126, 240)     # 可点发送：blue_btn
C_SEND_TEXT_ACTIVE = (255, 255, 255)
C_INPUT_AREA = (255, 255, 255)
C_CARD_BG = (255, 255, 255)
C_CARD_BORDER = (220, 222, 225)
C_PROFILE_SEND = (38, 126, 240)       # blue_btn #267EF0
C_PROFILE_SEND_DARK = (51, 140, 255)  # blue_btn 深色 #338CFF
C_PROFILE_SEND_TEXT = (255, 255, 255)
C_DARK_BG = (0, 0, 0)
C_DARK_PANEL = (34, 35, 36)           # ~#222324
C_DARK_TEXT = (230, 232, 236)
C_DARK_TEXT_SEC = (150, 155, 165)
C_DARK_BADGE = (255, 89, 98)          # #FF5962
C_DARK_NAV_BG = (0, 0, 0)
C_DARK_SELECTED_NAV = (40, 48, 60)
C_DARK_LIST_BG = (28, 29, 30)         # 会话/通讯录列表
C_DARK_CHAT_BG = (25, 26, 27)         # 聊天区
C_DARK_TITLE_BG = (34, 35, 36)        # 标题栏 / 输入区
C_DARK_SEARCH_BG = (45, 46, 48)
C_DARK_SEP = (55, 58, 64)
C_DARK_INPUT = (34, 35, 36)
C_WECHAT_GREEN = (7, 193, 96)         # @微信
C_CORP_ORANGE = (232, 136, 58)        # 外部联系人 @公司（搜索结果行）


def _load_font(size):
    candidates = [
        '/System/Library/Fonts/PingFang.ttc',
        '/System/Library/Fonts/STHeiti Light.ttc',
        '/System/Library/Fonts/Hiragino Sans GB.ttc',
        '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
        '/Library/Fonts/Arial Unicode.ttf',
        '/System/Library/Fonts/Helvetica.ttc',
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _text_size(draw, text, font):
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        return font.getsize(text)


def _truncate(draw, text, font, max_w, ellipsis=u'\u2026'):
    if _text_size(draw, text, font)[0] <= max_w:
        return text
    for i in range(len(text), 0, -1):
        t = text[:i] + ellipsis
        if _text_size(draw, t, font)[0] <= max_w:
            return t
    return ellipsis


def _clip_box(box, viewport):
    """box/viewport: (x0,y0,x1,y1) -> clipped box or None."""
    x0, y0, x1, y1 = box
    vx0, vy0, vx1, vy1 = viewport
    cx0 = max(x0, vx0)
    cy0 = max(y0, vy0)
    cx1 = min(x1, vx1)
    cy1 = min(y1, vy1)
    if cx1 <= cx0 or cy1 <= cy0:
        return None
    return (cx0, cy0, cx1, cy1)


def _box_to_yolo(box, img_w, img_h, min_h=4, min_area_ratio=5e-5):
    """绝对像素框 -> YOLO 归一化行；过小则丢弃。"""
    x0, y0, x1, y1 = box
    x0 = max(0, min(img_w, x0))
    y0 = max(0, min(img_h, y0))
    x1 = max(0, min(img_w, x1))
    y1 = max(0, min(img_h, y1))
    w = x1 - x0
    h = y1 - y0
    if w < 2 or h < min_h:
        return None
    if (w * h) / float(img_w * img_h) < min_area_ratio:
        return None
    xc = (x0 + x1) / 2.0 / img_w
    yc = (y0 + y1) / 2.0 / img_h
    nw = w / float(img_w)
    nh = h / float(img_h)
    return (xc, yc, nw, nh)


def _paste_rgba(base, overlay, xy):
    if overlay.mode != 'RGBA':
        overlay = overlay.convert('RGBA')
    base.paste(overlay, xy, overlay)


def _draw_badge(draw, cx, cy, count, font, fill=None):
    """红角标，中心落在 (cx, cy)。标签仍归入所属 icon/avatar，不单独成类。

    count 约定：
      None / False  -> 不画
      0 / 'dot'     -> 纯红点（无数字）
      1–9 / 10–99   -> 白字数字胶囊
      >99           -> 三点省略红圈
    """
    if count is None or count is False:
        return None
    color = fill or C_BADGE
    # plain red dot
    if count == 0 or count == 'dot':
        r = 5
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
        return (cx - r, cy - r, cx + r, cy + r)
    try:
        count = int(count)
    except Exception:
        return None
    if count < 0:
        return None
    if count > 99:
        r = 8
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
        for i, dx in enumerate((-4, 0, 4)):
            draw.ellipse([cx + dx - 1.5, cy - 1.5, cx + dx + 1.5, cy + 1.5], fill=(255, 255, 255))
        return (cx - r, cy - r, cx + r, cy + r)
    text = str(int(count))
    tw, th = _text_size(draw, text, font)
    pad_x = 5 if count >= 10 else 4
    bw = max(tw + pad_x * 2, th + 4)
    bh = th + 4
    # single digit: force circle
    if count < 10:
        side = max(bw, bh, 14)
        bw = bh = side
    x0 = cx - bw / 2.0
    y0 = cy - bh / 2.0
    draw.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=bh / 2.0, fill=color)
    draw.text((x0 + (bw - tw) / 2.0, y0 + (bh - th) / 2.0 - 1), text, fill=(255, 255, 255), font=font)
    return (x0, y0, x0 + bw, y0 + bh)


def _recolor_keep_alpha(im, rgb):
    """把不透明像素刷成 rgb，保留 alpha（用于把白色选中图标染成 #267EF0）。"""
    if im.mode != 'RGBA':
        im = im.convert('RGBA')
    px = im.load()
    w, h = im.size
    r, g, b = rgb
    for y in range(h):
        for x in range(w):
            _, _, _, a = px[x, y]
            if a > 0:
                px[x, y] = (r, g, b, a)
    return im


def _load_nav_icon(icons_dir, normal, selected_blue, selected_white, size, selected, dark=False):
    """未选中：模板黑图标染成灰（深色主题更浅）；选中：蓝实心 / 白图标染 blue_btn。"""
    if not selected:
        im = _load_icon(icons_dir, normal, size)
        gray = C_NAV_ICON_GRAY_DARK if dark else C_NAV_ICON_GRAY
        return _recolor_keep_alpha(im, gray)
    blue_path = os.path.join(icons_dir, selected_blue)
    if os.path.exists(blue_path):
        return _load_icon(icons_dir, selected_blue, size)
    white_path = os.path.join(icons_dir, selected_white)
    if os.path.exists(white_path):
        im = _load_icon(icons_dir, selected_white, size)
        return _recolor_keep_alpha(im, C_SELECTED_NAV_FG)
    im = _load_icon(icons_dir, normal, size)
    return _recolor_keep_alpha(im, C_SELECTED_NAV_FG)


def _load_icon(icons_dir, name, size):
    path = os.path.join(icons_dir, name)
    if not os.path.exists(path):
        im = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        return im
    im = Image.open(path).convert('RGBA')
    return im.resize((size, size), Image.LANCZOS)


def _load_avatars(avatars_dir):
    files = []
    if os.path.isdir(avatars_dir):
        for fn in sorted(os.listdir(avatars_dir)):
            if fn.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                files.append(os.path.join(avatars_dir, fn))
    return files


def _avatar_img(paths, size, rng):
    if paths:
        im = Image.open(rng.choice(paths)).convert('RGBA')
        im = im.resize((size, size), Image.LANCZOS)
        # 轻微圆角遮罩
        mask = Image.new('L', (size, size), 0)
        md = ImageDraw.Draw(mask)
        r = max(2, size // 8)
        md.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=255)
        out = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        out.paste(im, (0, 0))
        out.putalpha(mask)
        return out
    im = Image.new('RGBA', (size, size), (120, 140, 180, 255))
    return im


def _group_avatar_img(paths, size, rng):
    """群聊头像：2x2 拼贴。"""
    canvas = Image.new('RGBA', (size, size), (220, 224, 230, 255))
    cell = max(1, (size - 2) // 2)
    gap = 1
    for idx, (ox, oy) in enumerate(((gap, gap), (gap + cell + gap, gap),
                                    (gap, gap + cell + gap), (gap + cell + gap, gap + cell + gap))):
        tile = _avatar_img(paths, cell, rng)
        canvas.paste(tile, (ox, oy), tile)
    mask = Image.new('L', (size, size), 0)
    md = ImageDraw.Draw(mask)
    r = max(2, size // 8)
    md.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=255)
    canvas.putalpha(mask)
    return canvas



class WeComSynthesizer(object):
    def __init__(self, avatars_dir, icons_dir, names, messages, snippets,
                 min_visible_h=4, min_area_ratio=5e-5, rng=None):
        self.avatars_dir = avatars_dir
        self.icons_dir = icons_dir
        self.names = names or [u'\u7528\u6237']
        self.messages = messages or [u'\u4f60\u597d']
        self.snippets = snippets or [u'\u4f60\u597d']
        self.min_visible_h = min_visible_h
        self.min_area_ratio = min_area_ratio
        self.rng = rng or random.Random(0)
        self.avatar_paths = _load_avatars(avatars_dir)
        self.font_sm = _load_font(11)
        self.font_md = _load_font(13)
        self.font_nm = _load_font(14)
        self.font_title = _load_font(15)
        self.font_badge = _load_font(10)
        self.font_nav = _load_font(11)

    # 高保真典型页模板名（CLI --preset / sample_scenario 可强制）
    PRESETS = (
        'chat_narrow',
        'chat_wide',
        'chat_wide_groups',
        'chat_dark',
        'contacts_profile',
        'contacts_profile_dark',
        'contacts_customers',
        'contacts_search',
    )

    def _sample_search_hits(self):
        """通讯录搜索：短查询（1 或 2 字）+ 2..6 条互不相同、都含该查询的人名。

        命中位置混有前缀（田志清）、后缀（小田 / 阿田，不用姓+查询硬拼）、中间（张志伟）。
        不会整组都是「查询 + 同一个字」。部分条目带 @公司，部分不带。
        返回 (query, hits)，hit = {'name', 'corp'}，corp 为 None 或公司名（不含 @）。
        """
        rng = self.rng
        surn = (u'\u8d75\u94b1\u5b59\u674e\u5468\u5434\u90d1\u738b\u51af\u9648\u891a\u536b'
                u'\u848b\u6c88\u97e9\u6768\u6731\u79e6\u5c24\u8bb8\u4f55\u5415\u65bd\u5f20'
                u'\u5b54\u66f9\u4e25\u534e\u91d1\u9b4f\u9676\u59dc\u621a\u8c22\u90b9\u55bb'
                u'\u67cf\u6c34\u7aa6\u7ae0\u4e91\u82cf\u6f58\u845b\u8303\u5f6d\u90ce\u9c81'
                u'\u97e6\u660c\u9a6c\u82d7\u51e4\u82b1\u65b9\u4fde\u4efb\u8881\u67f3\u5510'
                u'\u7f57\u859b\u4f0d\u4f59\u7c73\u8d1d\u59da\u5b5f\u987e\u5c39\u6c5f\u949f'
                u'\u6c6a\u7530')
        giv = (u'\u5fd7\u6e05\u521a\u4f1f\u5a1c\u82b3\u6d0b\u9759\u5f3a\u78ca\u654f\u5a77'
               u'\u6d69\u4e3d\u660e\u96ea\u4eae\u6653\u519b\u98de\u96e8\u6668\u9633\u5efa'
               u'\u56fd\u534e\u5e73\u5b89\u4e50\u6587\u535a\u601d\u8fdc\u5b50\u8f69\u6d69'
               u'\u7136\u4e00\u8bfa\u8bd7\u6db5\u6770\u658c\u8d85\u9e4f\u8f89\u73b2\u71d5'
               u'\u971e\u9f99')

        def pick(alphabet, k):
            return u''.join(rng.choice(alphabet) for _ in range(k))

        qlen = 1 if rng.random() < 0.65 else 2
        if qlen == 1:
            q = rng.choice(surn + giv)
        elif rng.random() < 0.75:
            q = rng.choice(surn) + rng.choice(giv)
        else:
            q = rng.choice(giv) + rng.choice(giv)

        n = rng.randint(2, 6)

        def classify(nm):
            if nm.startswith(q) and not nm.endswith(q):
                return 'prefix'
            if nm.endswith(q) and not nm.startswith(q):
                return 'suffix'
            if (q in nm) and (not nm.startswith(q)) and (not nm.endswith(q)):
                return 'middle'
            return 'other'

        def make(pos):
            if pos == 'suffix':
                # 查询在末尾：前面只用常见称呼（小张、阿张、老张、大张），不用姓氏硬拼。
                nicks = [u'\u5c0f', u'\u963f', u'\u8001', u'\u5927']
                rng.shuffle(nicks)
                for pre in nicks:
                    cand = pre + q
                    if cand != q and classify(cand) == 'suffix':
                        return cand
                return None
            for _ in range(40):
                if pos == 'prefix':
                    # 查询在开头，后面接名用字（张子轩 / 志清），不接姓氏
                    k = 2 if rng.random() < 0.6 else 1
                    nm = q + pick(giv, k)
                else:
                    # 查询在中间：姓 + 查询 + 名（张志伟）。姓不与查询重叠。
                    left = rng.choice(surn)
                    if q.startswith(left):
                        continue
                    nm = left + q + rng.choice(giv)
                if nm and nm != q and classify(nm) == pos:
                    return nm
            return None

        if n >= 3:
            positions = ['prefix', 'suffix', 'middle']
            while len(positions) < n:
                positions.append(rng.choice(['prefix', 'suffix', 'middle']))
        else:
            positions = list(rng.choice([
                ('prefix', 'suffix'),
                ('prefix', 'middle'),
                ('suffix', 'middle'),
            ]))
        rng.shuffle(positions)

        names = []
        seen = set()
        for pos in positions:
            nm = None
            for _ in range(16):
                cand = make(pos)
                if cand and cand not in seen:
                    nm = cand
                    break
            if nm is None:
                if pos == 'suffix':
                    nm = (u'\u5c0f' + q) if classify(u'\u5c0f' + q) == 'suffix' else (u'\u963f' + q)
                elif pos == 'prefix':
                    nm = q + rng.choice(giv) + rng.choice(giv)
                else:
                    left = rng.choice(surn)
                    if q.startswith(left):
                        left = u'\u674e' if not q.startswith(u'\u674e') else u'\u738b'
                    nm = left + q + rng.choice(giv)
                guard = 0
                while (nm in seen or classify(nm) != pos) and guard < 6:
                    if pos == 'prefix':
                        nm = q + rng.choice(giv) + rng.choice(giv)
                    elif pos == 'middle':
                        left = rng.choice(surn)
                        if not q.startswith(left):
                            nm = left + q + rng.choice(giv)
                    guard += 1
            seen.add(nm)
            names.append(nm)

        # 两个前缀命中时，常常共享中间字、只差末字（田志清 / 田志刚）
        pref_i = [i for i, pos in enumerate(positions) if pos == 'prefix']
        if len(pref_i) >= 2 and rng.random() < 0.75:
            stem_ch = rng.choice(u'\u5fd7\u6587\u5b50\u6d69\u6653\u96e8')
            # 二字查询已经以字结尾时，stem 接在查询后
            a = q + stem_ch + rng.choice(giv)
            b = q + stem_ch + rng.choice(giv)
            guard = 0
            while b == a and guard < 8:
                b = q + stem_ch + rng.choice(giv)
                guard += 1
            if a != b and classify(a) == 'prefix' and classify(b) == 'prefix':
                names[pref_i[0]] = a
                names[pref_i[1]] = b

        # 去重，并保证仍含查询、位置种类没被挤没（n>=3 时三种都在）
        fixed = []
        seen = set()
        for pos, nm in zip(positions, names):
            if nm in seen or q not in nm or classify(nm) != pos:
                nm = make(pos)
                tries = 0
                while (not nm or nm in seen or q not in nm or classify(nm) != pos) and tries < 12:
                    nm = make(pos)
                    tries += 1
                if not nm or classify(nm) != pos:
                    if pos == 'suffix':
                        nm = u'\u963f' + q if classify(u'\u963f' + q) == 'suffix' else u'\u5c0f' + q
                    elif pos == 'prefix':
                        nm = q + rng.choice(giv) + rng.choice(giv)
                    else:
                        left = u'\u674e' if not q.startswith(u'\u674e') else u'\u738b'
                        nm = left + q + rng.choice(giv)
            seen.add(nm)
            fixed.append(nm)
        names = fixed

        corp_names = [u'\u5fae\u4fe1', u'\u817e\u8baf', u'\u963f\u91cc\u5df4\u5df4',
                      u'\u5b57\u8282\u8df3\u52a8', u'\u534e\u4e3a', u'\u7f8e\u56e2',
                      u'\u597d\u51f6\u706b\u79d1\u6280', u'\u767e\u5ea6']
        if n == 2:
            flags = [True, False]
        else:
            flags = [True, False]
            while len(flags) < n:
                flags.append(rng.random() < 0.45)
        rng.shuffle(flags)
        hits = []
        for nm, want in zip(names, flags):
            corp = rng.choice(corp_names) if want else None
            hits.append({'name': nm, 'corp': corp})
        return q, hits

    def make_scenario(self, preset, jitter=True):
        """构造高保真典型页场景。preset 见 PRESETS。"""
        rng = self.rng
        name = (preset or '').strip().lower().replace('-', '_')
        if name == 'contacts_profile_light':
            name = 'contacts_profile'
        dark = False
        show_groups = None  # None=宽栏默认画分组；False=强制不画；True=强制画
        search_query = None
        search_hits = None
        show_profile = True
        profile_name = None
        profile_corp = None
        selected_idx = None
        if name == 'contacts_profile_dark':
            name = 'contacts_profile'
            dark = True
        if name == 'chat_dark':
            # 窄/宽随机的深色聊天
            name = 'chat_narrow' if (rng.random() < 0.45 if jitter else False) else 'chat_wide'
            dark = True
        if name == 'chat_wide_groups':
            name = 'chat_wide'
            show_groups = True

        if name == 'contacts_customers':
            # 宽导航含「分组/单聊/群聊」+ 客户目录（只有几行，下面留白）。
            # 搜索框在目录栏顶部，只框灰色条。
            w, h = 1064, 808
            if jitter:
                w = rng.randint(1000, 1360)
                h = rng.randint(720, 920)
            nav_wide = True
            nav_w = rng.randint(150, 176) if jitter else 164
            list_w = rng.randint(200, 320) if jitter else 250
            page = 'contacts'
            n_conv = rng.choice([3, 4, 5, 6]) if jitter else 4
            msg_mode = 'empty'
            chat_badge = rng.choice([None]*10 + [1, 2, 3, 9])
            contacts_badge = rng.choice([None]*12 + [0, 1])
            show_groups = True
            list_style = 'categories'
            selected_idx = 1  # 我的客户，右侧才是联系人行
        elif name == 'chat_narrow':
            w, h = 1100, 700
            if jitter:
                w = rng.randint(980, 1200)
                h = rng.randint(640, 780)
            nav_wide = False
            nav_w = rng.randint(56, 64) if jitter else 60
            list_w = int(w * (rng.uniform(0.18, 0.36) if jitter else 0.25))
            page = 'chat'
            if jitter and rng.random() < 0.30:
                n_conv = rng.choice([1, 2, 3, 4])
            else:
                n_conv = rng.choice([8, 10, 12, 14]) if jitter else 12
            msg_mode = rng.choice(['mixed', 'dense', 'incoming']) if jitter else 'mixed'
            chat_badge = rng.choice([None]*12 + [1, 2, 3, 5, 9, 99, 'dot'])
            contacts_badge = rng.choice([None]*14 + [0, 1])
            if not dark:
                dark = False
            show_groups = False
        elif name == 'chat_wide':
            w, h = 1200, 800
            if jitter:
                w = rng.randint(1100, 1400)
                h = rng.randint(720, 900)
            nav_wide = True
            nav_w = rng.randint(150, 175) if jitter else 160
            list_w = int(w * (rng.uniform(0.16, 0.32) if jitter else 0.23))
            page = 'chat'
            if jitter and rng.random() < 0.30:
                n_conv = rng.choice([1, 2, 3, 4])
            else:
                n_conv = rng.choice([8, 10, 12, 15]) if jitter else 12
            msg_mode = rng.choice(['mixed', 'dense', 'outgoing']) if jitter else 'mixed'
            chat_badge = rng.choice([None]*12 + [1, 2, 3, 5, 9, 99, 'dot'])
            contacts_badge = rng.choice([None]*14 + [0, 1])
            if show_groups is None:
                show_groups = True  # 宽栏默认含「分组」
            if not dark:
                dark = False
        elif name == 'contacts_profile':
            w, h = 1100, 720
            if jitter:
                w = rng.randint(1000, 1400)
                h = rng.randint(640, 860)
            nav_wide = rng.random() < 0.55 if jitter else True
            if nav_wide:
                nav_w = rng.randint(150, 175) if jitter else 160
                if show_groups is None:
                    show_groups = True
            else:
                nav_w = rng.randint(56, 64) if jitter else 60
                show_groups = False
            list_w = int(w * (rng.uniform(0.20, 0.28) if jitter else 0.24))
            page = 'contacts'
            n_conv = rng.choice([6, 8, 10, 12]) if jitter else 8
            msg_mode = 'empty'
            chat_badge = rng.choice([None]*12 + [1, 2, 3, 5, 9, 99, 'dot'])
            contacts_badge = rng.choice([None]*14 + [0, 1])
            # dark already set if contacts_profile_dark
        elif name == 'contacts_search':
            # 通讯录搜索结果：搜索框是 1～2 字查询，下列 2～6 条部分同名的人。
            # 行仍走联系人列表画法，每行 contact_item。右侧资料页不盖住列表。
            w, h = 1100, 740
            if jitter:
                w = rng.randint(1000, 1400)
                h = rng.randint(700, 920)
            nav_wide = (rng.random() < 0.6) if jitter else True
            if nav_wide:
                nav_w = rng.randint(150, 175) if jitter else 160
                if show_groups is None:
                    show_groups = True
            else:
                nav_w = rng.randint(56, 64) if jitter else 60
                show_groups = False
            list_w = int(w * (rng.uniform(0.24, 0.34) if jitter else 0.28))
            page = 'contacts'
            search_query, search_hits = self._sample_search_hits()
            n_conv = len(search_hits)
            msg_mode = 'empty'
            chat_badge = rng.choice([None] * 12 + [1, 2, 3, 5])
            contacts_badge = rng.choice([None] * 14 + [0, 1])
            list_style = 'people'
            if jitter and rng.random() < 0.22:
                dark = True
            if rng.random() < 0.78:
                selected_idx = rng.randrange(n_conv)
                show_profile = True
                profile_name = search_hits[selected_idx]['name']
                profile_corp = search_hits[selected_idx].get('corp')
            else:
                selected_idx = -1
                show_profile = False
        else:
            raise ValueError('unknown preset %r; choose from %s' % (preset, ', '.join(self.PRESETS)))

        list_scroll = False
        msg_scroll = page == 'chat' and msg_mode in ('mixed', 'dense') and (rng.random() < 0.35)
        # force some unread badges on conversation rows for chat presets
        unread_rate = 0.45 if page == 'chat' else 0.0
        if selected_idx is None:
            selected_idx = 0 if n_conv > 0 else -1
        return {
            'w': w, 'h': h,
            'nav_wide': nav_wide,
            'nav_w': nav_w,
            'list_w': list_w,
            'page': page,
            'n_conv': n_conv,
            'msg_mode': msg_mode,
            'list_scroll': list_scroll,
            'msg_scroll': msg_scroll,
            'chat_badge': chat_badge,
            'contacts_badge': contacts_badge,
            'selected_idx': selected_idx,
            'dark': dark,
            'preset': preset,
            'unread_rate': unread_rate,
            'extra_nav_dots': bool(page == 'chat' and rng.random() < 0.45),
            'show_groups': bool(show_groups) if show_groups is not None else False,
            'show_nav_groups': bool(not nav_wide),
            'list_style': locals().get('list_style', 'people'),
            'search_query': search_query,
            'search_hits': search_hits,
            'show_profile': show_profile,
            'profile_name': profile_name,
            'profile_corp': profile_corp,
        }

    def sample_scenario(self, preset=None):
        """随机采样多样性场景；preset 非空则走高保真模板。
        无 preset 时约 40% 的随机样本也会偏向典型页，保证训练集常碰到高保真布局。
        """
        if preset:
            return self.make_scenario(preset, jitter=True)

        rng = self.rng
        # 提高典型页命中率
        if rng.random() < 0.18:
            return self.make_scenario('contacts_customers', jitter=True)
        if rng.random() < 0.40:
            return self.make_scenario(rng.choice(self.PRESETS), jitter=True)

        nav_wide = rng.random() < 0.45
        page = 'contacts' if rng.random() < 0.28 else 'chat'
        w = rng.randint(900, 1400)
        h = rng.randint(580, 1000)
        # 偶发极端比例
        if rng.random() < 0.15:
            w = rng.randint(800, 1000)
            h = rng.randint(900, 1100)
        if rng.random() < 0.15:
            w = rng.randint(1200, 1500)
            h = rng.randint(560, 700)

        n_conv = rng.choice([0, 1, 2, 3, 5, 8, 12, 15, 20])
        list_style = 'people'
        if page == 'contacts':
            if rng.random() < 0.45:
                list_style = 'categories'
                n_conv = rng.choice([3, 4, 5, 6])
                page = 'chat'
                msg_mode = 'empty'
            else:
                n_conv = rng.choice([2, 3, 5, 8, 12, 18])

        if list_style != 'categories':
            msg_mode = rng.choice(['empty', 'incoming', 'outgoing', 'mixed', 'sparse', 'dense'])
        list_scroll = rng.random() < 0.45 and n_conv >= 6
        msg_scroll = rng.random() < 0.4 and msg_mode in ('mixed', 'dense', 'incoming', 'outgoing')

        # None=无角标；0/'dot'=红点；正数=数字
        badge = rng.choice([None]*12 + [0, 1, 2, 3, 5, 9, 99])
        contacts_badge = rng.choice([None]*14 + [0, 1])

        list_w = int(w * rng.uniform(0.20, 0.32))
        if nav_wide:
            nav_w = int(w * rng.uniform(0.12, 0.16))
            nav_w = max(140, min(190, nav_w))
        else:
            nav_w = int(w * rng.uniform(0.045, 0.065))
            nav_w = max(52, min(70, nav_w))

        dark = rng.random() < 0.35
        return {
            'w': w, 'h': h,
            'nav_wide': nav_wide,
            'nav_w': nav_w,
            'list_w': list_w,
            'page': page,
            'n_conv': n_conv,
            'msg_mode': msg_mode,
            'list_scroll': list_scroll,
            'msg_scroll': msg_scroll,
            'chat_badge': badge,
            'contacts_badge': contacts_badge,
            'selected_idx': 0 if n_conv > 0 else -1,
            'dark': dark,
            'unread_rate': 0.30 if page == 'chat' else 0.0,
            'extra_nav_dots': rng.random() < 0.25,
            'show_groups': bool(nav_wide and rng.random() < 0.75),
            'show_nav_groups': bool((not nav_wide) and rng.random() < 0.85),
            'list_style': list_style,
        }

    def render(self, scenario=None, preset=None):
        sc = scenario or self.sample_scenario(preset=preset)
        W, H = sc['w'], sc['h']
        win_bg = C_DARK_BG if sc.get('dark') else C_WIN_BG
        img = Image.new('RGB', (W, H), win_bg)
        draw = ImageDraw.Draw(img)
        labels = []  # (cls, x0,y0,x1,y1) absolute

        nav_w = sc['nav_w']
        list_w = sc['list_w']
        chat_x0 = nav_w + list_w
        if chat_x0 >= W - 200:
            list_w = max(180, W - nav_w - 280)
            chat_x0 = nav_w + list_w
            sc['list_w'] = list_w

        # --- left nav ---
        self._draw_nav(img, draw, labels, sc)

        # --- middle list ---
        self._draw_middle(img, draw, labels, sc)

        # --- right pane ---
        if sc.get('list_style') == 'categories':
            self._draw_customer_pane(img, draw, labels, sc)
        elif sc['page'] == 'contacts':
            if sc.get('show_profile', True):
                self._draw_contact_profile(img, draw, labels, sc)
            else:
                # 未选中时右侧留白，不把资料页画到中间的结果列表上
                pane_bg = C_DARK_BG if sc.get('dark') else (248, 248, 250)
                draw.rectangle([chat_x0, 0, W, H], fill=pane_bg)
        else:
            self._draw_chat(img, draw, labels, sc)

        # 窗口细边框
        border_c = (70, 72, 78) if sc.get('dark') else (200, 205, 210)
        draw.rectangle([0, 0, W - 1, H - 1], outline=border_c)

        yolo_lines = []
        for cls, x0, y0, x1, y1 in labels:
            y = _box_to_yolo((x0, y0, x1, y1), W, H,
                             min_h=self.min_visible_h,
                             min_area_ratio=self.min_area_ratio)
            if y is not None:
                yolo_lines.append('%d %.6f %.6f %.6f %.6f' % (cls, y[0], y[1], y[2], y[3]))

        return img, yolo_lines, sc

    # ------------------------------------------------------------------ nav
    def _draw_nav(self, img, draw, labels, sc):
        W, H = sc['w'], sc['h']
        nav_w = sc['nav_w']
        wide = sc['nav_wide']
        dark = sc.get('dark', False)
        nav_bg = C_DARK_NAV_BG if dark else C_NAV_BG
        text_c = C_DARK_TEXT if dark else C_TEXT
        text_sec = C_DARK_TEXT_SEC if dark else C_TEXT_SEC
        sel_nav = C_DARK_SELECTED_NAV if dark else C_SELECTED_NAV
        badge_fill = C_DARK_BADGE if dark else C_BADGE
        draw.rectangle([0, 0, nav_w, H], fill=nav_bg)

        # self avatar
        pad = 10 if wide else 8
        av_size = 36 if wide else 32
        ax = pad
        ay = 16
        av = _avatar_img(self.avatar_paths, av_size, self.rng)
        _paste_rgba(img, av, (ax, ay))
        labels.append((CLS_SELF_AVATAR, ax, ay, ax + av_size, ay + av_size))

        if wide:
            name = _truncate(draw, self.rng.choice(self.names), self.font_md, nav_w - ax - av_size - 16)
            draw.text((ax + av_size + 8, ay + 8), name, fill=text_c, font=self.font_md)

        # nav items: (key, 文案, 类别 id, 角标, 常态图标, 选中图标)
        # 选中态：浅蓝底 + 蓝实心 *_selected.png（截图校准；白图标仅作缺省染色源）。
        # key 与 sc['page'] 对应：谁等于 page 谁高亮（浅蓝底 + 蓝图标）。
        # (key, 文案, 类别, 角标, 常态, 蓝实心选中, 白选中)
        # 真实企微截图：选中 = 浅蓝底(#C8DEF7) + 蓝色图标(#267EF0)，不是「实心蓝底+白图标」。
        items = [
            ('chat',     u'\u6d88\u606f', CLS_NAV_CHAT, sc.get('chat_badge'),
             'nav_chat.png', 'nav_chat_selected.png', 'nav_chat_selected_white.png'),
            ('mail',     u'\u90ae\u4ef6', None, None,
             'nav_mail.png', 'nav_mail_selected.png', 'nav_mail_selected_white.png'),
            ('docs',     u'\u6587\u6863', None, None,
             'nav_docs.png', 'nav_docs_selected.png', 'nav_docs_selected_white.png'),
            ('contacts', u'\u901a\u8baf\u5f55', CLS_NAV_CONTACTS, sc.get('contacts_badge'),
             'nav_contacts.png', 'nav_contacts_selected.png', 'nav_contacts_selected_white.png'),
            ('cal',      u'\u65e5\u7a0b', None, None,
             'nav_calendar.png', 'nav_calendar_selected.png', 'nav_calendar_selected_white.png'),
            ('todo',     u'\u5f85\u529e', None, None,
             'nav_todo.png', 'nav_todo_selected.png', 'nav_todo_selected_white.png'),
            ('meet',     u'\u4f1a\u8bae', None, None,
             'nav_meeting.png', 'nav_meeting_selected.png', 'nav_meeting_selected_white.png'),
            ('wb',       u'\u5de5\u4f5c\u53f0', None, None,
             'nav_workbench.png', 'nav_workbench_selected.png', 'nav_workbench_selected_white.png'),
        ]
        # 导航红点稀疏随机：整栏通常 0～2 个有角标，避免每个 icon 都挂红点
        # chat/contacts 的 badge 来自 scenario；其它项默认无，再按概率补极少数
        badgeable = [1, 2, 4, 5, 6, 7]  # mail/docs/cal/todo/meet/wb
        n_extra = 0
        if sc.get('extra_nav_dots'):
            n_extra = self.rng.choice([0, 0, 0, 1, 1, 2])  # 多数时候 0～1
        else:
            n_extra = self.rng.choice([0, 0, 0, 0, 1])  # 更稀
        if n_extra:
            picks = list(badgeable)
            self.rng.shuffle(picks)
            for j in picks[:n_extra]:
                it = list(items[j])
                if it[3] is not None:
                    continue
                it[3] = self.rng.choice([0, 0, 0, 1, 2, 3])  # 多为纯红点
                items[j] = tuple(it)

        y = ay + av_size + 18
        # 窄栏图标略大、宽栏略小（与企微侧栏观感一致）
        icon_sz = 20 if wide else 26

        for key, text, cls_id, badge, icon_normal, icon_sel_blue, icon_sel_white in items:
            selected = (sc['page'] == key)
            if wide:
                row_h = 40
                if selected:
                    draw.rounded_rectangle([6, y, nav_w - 6, y + row_h], radius=6, fill=sel_nav)
                ix = 14
                iy = y + (row_h - icon_sz) // 2
                icon = _load_nav_icon(self.icons_dir, icon_normal, icon_sel_blue,
                                     icon_sel_white, icon_sz, selected, dark=dark)
                _paste_rgba(img, icon, (ix, iy))
                tw, th = _text_size(draw, text, self.font_nav)
                tx = ix + icon_sz + 10
                ty = y + (row_h - th) // 2
                tfill = C_SELECTED_NAV_FG if selected else text_c
                draw.text((tx, ty), text, fill=tfill, font=self.font_nav)
                if badge is not None:
                    # 宽栏：数字角标靠行尾；纯红点贴图标右上角（与截图一致）
                    if badge == 0 or badge == 'dot':
                        bx = ix + icon_sz - 1
                        by = iy + 1
                    else:
                        bx = nav_w - 18
                        by = y + row_h // 2
                    _draw_badge(draw, bx, by, badge, self.font_badge, fill=badge_fill)
                # 导航类只标图标（宽窄布局一致，不含文字）
                if cls_id is not None:
                    pad = 2
                    labels.append((cls_id, ix - pad, iy - pad,
                                   ix + icon_sz + pad, iy + icon_sz + pad))
                y += row_h + 2
            else:
                # narrow: icon above text；角标贴图标右上角（略重叠）
                cell_h = 56
                cell_w = nav_w - 4
                cx0 = 2
                if selected:
                    draw.rounded_rectangle([cx0, y, cx0 + cell_w, y + cell_h - 4],
                                          radius=6, fill=sel_nav)
                ix = (nav_w - icon_sz) // 2
                iy = y + 4
                icon = _load_nav_icon(self.icons_dir, icon_normal, icon_sel_blue,
                                     icon_sel_white, icon_sz, selected, dark=dark)
                _paste_rgba(img, icon, (ix, iy))
                tw, th = _text_size(draw, text, self.font_sm)
                tx = (nav_w - tw) // 2
                ty = iy + icon_sz + 2
                tfill = C_SELECTED_NAV_FG if selected else text_sec
                draw.text((tx, ty), text, fill=tfill, font=self.font_sm)
                if badge is not None:
                    # 中心落在图标右上角，红点/数字略压住图标边缘
                    _draw_badge(draw, ix + icon_sz - 1, iy + 1, badge, self.font_badge,
                                fill=badge_fill)
                # 导航类只标图标（不含下方文字）
                if cls_id is not None:
                    pad = 2
                    labels.append((cls_id, ix - pad, iy - pad,
                                   ix + icon_sz + pad, iy + icon_sz + pad))
                y += cell_h

        more_y = H - 48
        # 窄栏底部次级入口：微盘 / 高级功能 / 分组（分组 = CLS_NAV_GROUPS）
        if (not wide) and sc.get('show_nav_groups', True):
            # 主项过长时仍尽量挤出「分组」
            bot_items = [
                ('wedrive', '微盘', None,
                 'nav_wedrive.png', 'nav_wedrive_selected.png', 'nav_wedrive_selected_white.png'),
                ('advanced', '高级功能', None,
                 'nav_advanced.png', 'nav_advanced_selected.png', 'nav_advanced_selected_white.png'),
                ('groups', '分组', CLS_NAV_GROUPS,
                 'nav_convtag.png', 'nav_convtag_selected.png', 'nav_convtag_selected_white.png'),
            ]
            # 空间不够时只保留「分组」
            need = 56 * len(bot_items)
            if y + need >= more_y:
                bot_items = [bot_items[-1]]
            if y + 50 < more_y:
                y += 6
                bot_icon_sz = 22
                for key, text, cls_id, icon_normal, icon_sel_blue, icon_sel_white in bot_items:
                    if y + 50 >= more_y:
                        break
                    cell_h = 52
                    cell_w = nav_w - 4
                    cx0 = 2
                    selected = False
                    ix = (nav_w - bot_icon_sz) // 2
                    iy = y + 4
                    icon = _load_nav_icon(self.icons_dir, icon_normal, icon_sel_blue,
                                         icon_sel_white, bot_icon_sz, selected, dark=dark)
                    if icon is not None:
                        _paste_rgba(img, icon, (ix, iy))
                    tw, th = _text_size(draw, text, self.font_sm)
                    tx = (nav_w - tw) // 2
                    ty = iy + bot_icon_sz + 2
                    draw.text((tx, ty), text, fill=text_sec, font=self.font_sm)
                    if cls_id is not None:
                        pad = 2
                        labels.append((cls_id, ix - pad, iy - pad,
                                       ix + bot_icon_sz + pad, iy + bot_icon_sz + pad))
                    y += cell_h

        # 宽栏「分组」标题：标签图标 + 文案，标为 nav_groups_icon
        if wide and sc.get('show_groups', False) and y + 110 < more_y:
            y += 10
            hdr = '分组'
            hdr_icon_sz = 14
            hdr_icon = _load_icon(self.icons_dir, 'nav_convtag.png', hdr_icon_sz)
            if hdr_icon is not None:
                gray = C_NAV_ICON_GRAY_DARK if dark else C_NAV_ICON_GRAY
                hdr_icon = _recolor_keep_alpha(hdr_icon, gray)
            hx, hy = 14, y
            if hdr_icon is not None:
                _paste_rgba(img, hdr_icon, (hx, hy))
                draw.text((hx + hdr_icon_sz + 6, hy + 1), hdr, fill=text_sec, font=self.font_sm)
                labels.append((CLS_NAV_GROUPS, hx - 2, hy - 2,
                               hx + hdr_icon_sz + 2, hy + hdr_icon_sz + 2))
            else:
                draw.text((14, y), hdr, fill=text_sec, font=self.font_sm)
            y += 22
            # 图标来自 export_wework_icons.py --preset grp → assets/icons/grp_*.png
            # (label, icon_file, selected_icon_or_None, maybe_unread_badge)
            group_rows = [
                ('未读', 'grp_unread.png', None, True),
                ('@我', 'grp_atme.png', None, False),
                ('单聊', 'grp_single.png', 'grp_single_selected.png', False),
                ('群聊', 'grp_group.png', None, False),
                ('内部聊天', 'grp_internal.png', None, False),
                ('外部聊天', 'grp_external.png', None, False),
                ('标记', 'grp_star.png', None, False),
            ]
            # 随机高亮其中一项（常见为单聊/群聊）
            sel_idx = self.rng.choice([2, 2, 3, None, None])
            icon_sz = 16
            for gi, (gtext, icon_fn, icon_sel, maybe_badge) in enumerate(group_rows):
                if y + 30 >= more_y:
                    break
                row_h = 30
                selected = (sel_idx is not None and gi == sel_idx)
                if selected:
                    try:
                        draw.rounded_rectangle([6, y, nav_w - 6, y + row_h], radius=6,
                                               fill=C_SELECTED_NAV)
                    except AttributeError:
                        draw.rectangle([6, y, nav_w - 6, y + row_h], fill=C_SELECTED_NAV)
                ix, iy = 14, y + (row_h - icon_sz) // 2
                use = icon_sel if (selected and icon_sel) else icon_fn
                icon = _load_icon(self.icons_dir, use, icon_sz)
                if icon is not None:
                    _paste_rgba(img, icon, (ix, iy))
                else:
                    try:
                        draw.rounded_rectangle([ix, iy, ix + icon_sz, iy + icon_sz], radius=2,
                                               outline=text_sec)
                    except AttributeError:
                        draw.rectangle([ix, iy, ix + icon_sz, iy + icon_sz], outline=text_sec)
                tw, th = _text_size(draw, gtext, self.font_nav)
                tfill = C_SELECTED_NAV_FG if selected else text_c
                draw.text((ix + icon_sz + 8, y + (row_h - th) // 2), gtext, fill=tfill, font=self.font_nav)
                # 单聊 / 群聊：只标左侧图标（与主导航策略一致）
                if gtext == '单聊':
                    labels.append((CLS_SINGLE_CHAT, ix - 2, iy - 2,
                                   ix + icon_sz + 2, iy + icon_sz + 2))
                elif gtext == '群聊':
                    labels.append((CLS_GROUP_CHAT, ix - 2, iy - 2,
                                   ix + icon_sz + 2, iy + icon_sz + 2))
                # 分组行角标也稀疏：未读行 ~35%，其它行极少
                do_badge = (maybe_badge and self.rng.random() < 0.35) or (
                    (not maybe_badge) and self.rng.random() < 0.06)
                if do_badge:
                    bc = self.rng.choice([0, 0, 1, 2, 3, 5, 8])
                    _draw_badge(draw, nav_w - 18, y + row_h // 2, bc, self.font_badge,
                                fill=badge_fill)
                y += row_h

            # 参考截图：7 项之后隔一段，单独一项「我的企业」（实心块图标，比上面偏浅）
            if y + 34 < more_y:
                y += 12
                row_h = 30
                ix, iy = 14, y + (row_h - icon_sz) // 2
                corp_icon = _load_icon(self.icons_dir, 'grp_corp.png', icon_sz)
                if corp_icon is not None:
                    _paste_rgba(img, corp_icon, (ix, iy))
                tw, th = _text_size(draw, u'\u6211\u7684\u4f01\u4e1a', self.font_nav)
                draw.text((ix + icon_sz + 8, y + (row_h - th) // 2), u'\u6211\u7684\u4f01\u4e1a',
                          fill=text_c, font=self.font_nav)
                y += row_h

        # bottom more
        more = _load_icon(self.icons_dir, 'nav_more.png', 20)
        _paste_rgba(img, more, ((nav_w - 20) // 2, H - 40))

    # -------------------------------------------------------------- middle

    _CORPS = (u"\u5fae\u4fe1", u"\u817e\u8baf", u"\u963f\u91cc\u5df4\u5df4",
              u"\u5b57\u8282\u8df3\u52a8", u"\u534e\u4e3a", u"\u7f8e\u56e2",
              u"\u597d\u51f6\u706b\u79d1\u6280", u"\u767e\u5ea6")

    def _draw_centered_name(self, rd, name_x, list_w, row_h, name, corp, selected, name_fill):
        """One line: name and @company, vertically centered with the avatar.

        Returns the x of the text's right edge.
        """
        font = self.font_nm
        tag = (u"@" + corp) if corp else u""
        if tag:
            avail = max(40, list_w - name_x - 16)
            if _text_size(rd, tag, font)[0] > int(avail * 0.62):
                tag = _truncate(rd, tag, font, int(avail * 0.62))
        tag_w = (_text_size(rd, tag, font)[0] + 6) if tag else 0
        max_name_w = max(24, list_w - name_x - 16 - tag_w)
        name_t = _truncate(rd, name, font, max_name_w)
        try:
            bbox = rd.textbbox((0, 0), name_t, font=font)
            th = bbox[3] - bbox[1]
            text_y = (row_h - th) // 2 - bbox[1]
        except Exception:
            _, th = _text_size(rd, name_t, font)
            text_y = (row_h - th) // 2
        rd.text((name_x, text_y), name_t, fill=name_fill, font=font)
        nw = _text_size(rd, name_t, font)[0]
        if not tag:
            return name_x + nw
        if selected:
            tag_fill = (210, 255, 224) if corp == u"\u5fae\u4fe1" else (255, 236, 214)
        elif corp == u"\u5fae\u4fe1":
            tag_fill = C_WECHAT_GREEN
        else:
            tag_fill = C_CORP_ORANGE
        rd.text((name_x + nw + 4, text_y), tag, fill=tag_fill, font=font)
        return name_x + nw + 4 + _text_size(rd, tag, font)[0]

    def _draw_customer_pane(self, img, draw, labels, sc):
        """Right side of the customer page. Folder headers are not labeled.
        Each person is a contact_item: one centered line, box hugs the row.
        """
        W, H = sc["w"], sc["h"]
        x0 = sc["nav_w"] + sc["list_w"]
        dark = sc.get("dark", False)
        bg = C_DARK_BG if dark else (255, 255, 255)
        text_c = C_DARK_TEXT if dark else C_TEXT
        sec_c = C_DARK_TEXT_SEC if dark else C_TEXT_SEC
        draw.rectangle([x0, 0, W, H], fill=bg)
        draw.text((x0 + 20, 16), u"\u6211\u7684\u5ba2\u6237", fill=text_c, font=self.font_title)
        # tag row, not a contact
        ty = 50
        draw.rounded_rectangle([x0 + 20, ty, x0 + 36, ty + 16], radius=3, fill=(46, 184, 92))
        draw.text((x0 + 44, ty), u"\u6807\u7b7e", fill=text_c, font=self.font_md)
        draw.text((W - 28, ty), u">", fill=sec_c, font=self.font_sm)
        y = ty + 34

        wx = u"\u5fae\u4fe1"
        comp = self.rng.choice([c for c in self._CORPS if c != wx])
        groups = [
            (u"\u5fae\u4fe1\u8054\u7cfb\u4eba", wx, self.rng.randint(1, 3)),
            (comp, comp, self.rng.randint(1, 3)),
        ]
        row_h = self.rng.randint(46, 54)
        total = 0
        max_w = W - x0 - 24
        for gname, corp, n in groups:
            if y + 22 + row_h > H - 24:
                break
            draw.polygon([(x0 + 18, y + 4), (x0 + 24, y + 8), (x0 + 18, y + 12)], fill=sec_c)
            draw.rounded_rectangle([x0 + 28, y, x0 + 44, y + 14], radius=2, fill=(88, 150, 230))
            draw.text((x0 + 50, y - 1), gname, fill=sec_c, font=self.font_sm)
            y += 24
            for _ in range(n):
                if y + row_h > H - 20:
                    break
                name = self.rng.choice(self.names)
                right = self._paint_customer_row(
                    img, x0 + 12, y, max_w, row_h, name, corp, text_c)
                labels.append((CLS_CONTACT_ITEM, x0 + 12, y, x0 + 12 + right, y + row_h))
                y += row_h + 4
                total += 1
        if total:
            cap = u"\u5171%d\u4f4d\u5ba2\u6237" % total
            tw, th = _text_size(draw, cap, self.font_sm)
            draw.text((x0 + (W - x0 - tw) // 2, y + 4), cap, fill=sec_c, font=self.font_sm)

    def _paint_customer_row(self, img, x, y, max_w, row_h, name, corp, name_fill):
        av_sz = max(28, row_h - 16)
        row = Image.new("RGBA", (max_w, row_h), (0, 0, 0, 0))
        rd = ImageDraw.Draw(row)
        av = _avatar_img(self.avatar_paths, av_sz, self.rng)
        av_x = 8
        _paste_rgba(row, av, (av_x, (row_h - av_sz) // 2))
        name_x = av_x + av_sz + 8
        text_right = self._draw_centered_name(
            rd, name_x, max_w, row_h, name, corp, False, name_fill)
        right = min(max_w, int(text_right) + 14)
        crop = row.crop((0, 0, right, row_h))
        img.paste(crop, (int(x), int(y)), crop)
        return right

    def _draw_middle(self, img, draw, labels, sc):
        W, H = sc['w'], sc['h']
        nav_w = sc['nav_w']
        list_w = sc['list_w']
        x0 = nav_w
        dark = sc.get('dark', False)
        list_bg = C_DARK_LIST_BG if dark else C_LIST_BG
        sep_c = C_DARK_SEP if dark else C_SEP
        search_bg = C_DARK_SEARCH_BG if dark else C_SEARCH_BG
        placeholder = C_DARK_TEXT_SEC if dark else C_TEXT_PLACEHOLDER
        name_c = C_DARK_TEXT if dark else C_TEXT
        snip_c = C_DARK_TEXT_SEC if dark else C_TEXT_SEC
        draw.rectangle([x0, 0, x0 + list_w, H], fill=list_bg)
        # right separator
        draw.line([(x0 + list_w - 1, 0), (x0 + list_w - 1, H)], fill=sep_c)

        # search bar row（截图约 32–34px 高、圆角胶囊）
        # 框只包灰色胶囊，不含右侧「+」。宽度随栏宽变，再随机收窄一截。
        search_h = self.rng.choice([30, 32, 34])
        pad = self.rng.choice([10, 12, 14])
        plus_sz = 26
        sy = self.rng.choice([10, 12, 14])
        sx = x0 + pad
        sw = list_w - pad * 2 - plus_sz - 8
        if self.rng.random() < 0.45:
            sw = int(sw * self.rng.uniform(0.78, 0.94))
        sw = max(110, min(sw, list_w - pad - plus_sz - 16))
        sh = search_h
        draw.rounded_rectangle([sx, sy, sx + sw, sy + sh], radius=6, fill=search_bg)
        # search icon + placeholder；搜索结果场景改成短查询，框仍是整条胶囊
        sicon = _load_icon(self.icons_dir, 'search.png', 16)
        _paste_rgba(img, sicon, (sx + 8, sy + (sh - 16) // 2))
        query = sc.get('search_query')
        if query:
            draw.text((sx + 28, sy + (sh - 13) // 2), query, fill=name_c, font=self.font_md)
            draw.text((sx + sw - 16, sy + (sh - 13) // 2), u'\u00d7', fill=placeholder, font=self.font_md)
        else:
            draw.text((sx + 28, sy + (sh - 13) // 2), u'\u641c\u7d22', fill=placeholder, font=self.font_md)
        labels.append((CLS_SEARCH_BAR, sx, sy, sx + sw, sy + sh))

        # plus button (not a labeled class)
        px = sx + sw + 8
        py = sy + (sh - plus_sz) // 2
        plus = _load_icon(self.icons_dir, 'plus.png', plus_sz)
        _paste_rgba(img, plus, (px, py))

        # list viewport
        list_top = sy + sh + 8
        list_bot = H
        # 搜索结果：细字「联系人」标题，本身不是 contact_item
        search_hits = sc.get('search_hits')
        if search_hits:
            draw.text((x0 + 14, list_top + 2), u'联系人', fill=snip_c, font=self.font_sm)
            list_top = list_top + 22
        viewport = (x0, list_top, x0 + list_w, list_bot)

        if sc.get('list_style') == 'categories':
            self._draw_category_list(img, draw, x0, list_w, list_top, H, name_c, snip_c, sc)
            return

        n = sc['n_conv']
        is_contacts = sc['page'] == 'contacts'
        # 联系人/搜索结果是一行字，行高按张在 46-54，不再全数据集钉死 64。
        # 同一张图里行高一致。会话行仍是两行字，保持 64。
        row_h = self.rng.randint(46, 54) if is_contacts else 64
        # scroll offset: partially clip top/bottom
        if sc['list_scroll'] and n > 0:
            # negative offset -> first item partially above viewport
            offset = self.rng.randint(-int(row_h * 0.7), int(row_h * 0.4))
        else:
            offset = 0

        y = list_top + offset
        item_cls = CLS_CONTACT_ITEM if is_contacts else CLS_CONVERSATION_ITEM

        for i in range(n):
            row_box = (x0, y, x0 + list_w, y + row_h)
            visible = _clip_box(row_box, viewport)
            selected = (i == sc['selected_idx'])

            if visible:
                # draw only visible portion background
                vx0, vy0, vx1, vy1 = visible
                if selected and not search_hits:
                    draw.rectangle([vx0, vy0, vx1, vy1], fill=C_SELECTED_LIST)
                # content drawn in full row coords but clipped visually by not drawing outside? 
                # We draw into full image; content outside viewport still paints into title/search —
                # so clip drawing by using a temp or only draw if mostly visible.
                # Simpler: draw into a row crop then paste clipped.
                row_im = Image.new('RGBA', (list_w, row_h), (0, 0, 0, 0))
                rd = ImageDraw.Draw(row_im)
                if selected:
                    if search_hits:
                        rd.rounded_rectangle([6, 2, list_w - 6, row_h - 2], radius=6,
                                             fill=C_SELECTED_LIST + (255,))
                    else:
                        rd.rectangle([0, 0, list_w, row_h], fill=C_SELECTED_LIST + (255,))

                av_sz = max(28, row_h - 16) if is_contacts else 40
                is_group = (not is_contacts) and (self.rng.random() < 0.35)
                if is_group:
                    av = _group_avatar_img(self.avatar_paths, av_sz, self.rng)
                else:
                    av = _avatar_img(self.avatar_paths, av_sz, self.rng)
                av_x = 12
                av_y = (row_h - av_sz) // 2
                _paste_rgba(row_im, av, (av_x, av_y))

                hit = None
                if search_hits is not None and i < len(search_hits):
                    hit = search_hits[i]
                name = hit['name'] if hit else self.rng.choice(self.names)
                corp = hit.get('corp') if hit else None
                name_font = self.font_nm
                name_fill = C_SELECTED_LIST_TEXT if selected else name_c
                snip_fill = (220, 230, 245) if selected else snip_c
                time_fill = snip_fill

                name_x = 12 + av_sz + 10
                if is_contacts:
                    if hit is None and self.rng.random() < 0.7:
                        corp = (u"\u5fae\u4fe1" if self.rng.random() < 0.5
                                else self.rng.choice(self._CORPS))
                    self._draw_centered_name(
                        rd, name_x, list_w, row_h, name, corp, selected, name_fill)
                else:
                    name_t = _truncate(rd, name, self.font_nm, list_w - name_x - 56)
                    rd.text((name_x, 12), name_t, fill=name_fill, font=self.font_nm)
                    snip = self.rng.choice(self.snippets)
                    snip_t = _truncate(rd, snip, self.font_sm, list_w - name_x - 16)
                    rd.text((name_x, 36), snip_t, fill=snip_fill, font=self.font_sm)
                    times = [u"\u521a\u521a", u"1\u5206\u949f\u524d", u"16:10",
                             u"\u6628\u5929", u"\u5468\u4e00", "09:30"]
                    t = self.rng.choice(times)
                    tw, th = _text_size(rd, t, self.font_sm)
                    rd.text((list_w - tw - 12, 12), t, fill=time_fill, font=self.font_sm)
                    unread_rate = sc.get("unread_rate", 0.25)
                    if self.rng.random() < unread_rate:
                        bc = self.rng.choice([0, 1, 1, 2, 3, 5, 8, 12, 42, 99, 120])
                        _draw_badge(rd, av_x + av_sz - 1, av_y + 1, bc, self.font_badge)

                # separator：头像下也画；左右与中间栏边框留空隙（不贴边）
                if not selected and not search_hits:
                    sep_inset = 12
                    rd.line([(sep_inset, row_h - 1), (list_w - sep_inset, row_h - 1)],
                            fill=sep_c + (255,))

                # paste only the visible part of the row
                src_y0 = max(0, int(vy0 - y))
                src_y1 = src_y0 + int(vy1 - vy0)
                crop = row_im.crop((0, src_y0, list_w, src_y1))
                img.paste(crop, (int(vx0), int(vy0)), crop)

                if search_hits:
                    lab = (vx0 + 6, vy0 + 2, vx1 - 6, vy1 - 2)
                    if lab[2] > lab[0] and lab[3] > lab[1]:
                        labels.append((item_cls, lab[0], lab[1], lab[2], lab[3]))
                else:
                    labels.append((item_cls, vx0, vy0, vx1, vy1))

            y += row_h
            if y > list_bot + row_h:
                break

    # -------------------------------------------------------- contact profile
    def _draw_category_list(self, img, draw, x0, list_w, list_top, H, name_c, snip_c, sc):
        """客户/分组目录：只有几行，下面留白。这些行不是 contact_item，不打标签。"""
        company = self.rng.choice(self.names)
        cats = [
            '新的客户', '我的客户', '智能机器人', company, '添加成员',
        ]
        n = max(1, min(int(sc.get('n_conv') or 4), len(cats)))
        row_h = 42
        y = list_top
        sel = sc.get('selected_idx', 0)
        if sel < 0 or sel >= n:
            sel = 0
        for i in range(n):
            if y + row_h > H - 4:
                break
            if i == sel:
                draw.rectangle([x0, y, x0 + list_w - 1, y + row_h], fill=C_SELECTED_LIST)
            ix = x0 + 14
            iy = y + (row_h - 18) // 2
            fill = (255, 255, 255) if i == sel else (70, 160, 95)
            draw.rounded_rectangle([ix, iy, ix + 18, iy + 18], radius=3, fill=fill)
            text_fill = C_SELECTED_LIST_TEXT if i == sel else name_c
            draw.text((ix + 26, y + 11), cats[i], fill=text_fill, font=self.font_md)
            draw.text((x0 + list_w - 22, y + 12), '>', fill=snip_c, font=self.font_sm)
            y += row_h

    def _draw_contact_profile(self, img, draw, labels, sc):
        """通讯录/客户详情右侧：类 13「发消息」。
        按钮等宽居中簇：大侧边距 + 等宽 3 钮（窄栏 2 钮），不贴窗边。
        按钮紧跟资料字段，中间空白高度随机，不钉在窗口底部。
        """
        W, H = sc['w'], sc['h']
        x0 = sc['nav_w'] + sc['list_w']
        pane_w = W - x0
        dark = sc.get('dark', False)
        bg = C_DARK_BG if dark else (248, 248, 250)
        text_c = C_DARK_TEXT if dark else C_TEXT
        sec_c = C_DARK_TEXT_SEC if dark else C_TEXT_SEC
        sep_c = C_DARK_SEP if dark else C_SEP
        draw.rectangle([x0, 0, W, H], fill=bg)

        head_h = int(H * 0.22)
        head_bg = C_DARK_PANEL if dark else (255, 255, 255)
        draw.rectangle([x0, 0, W, head_h], fill=head_bg)

        forced_name = sc.get('profile_name')
        name = forced_name or self.rng.choice(self.names)
        av_sz = int(self.rng.uniform(56, 72))
        av = _avatar_img(self.avatar_paths, av_sz, self.rng)
        ax = W - av_sz - 24
        ay = 20
        _paste_rgba(img, av, (ax, ay))

        draw.text((x0 + 24, 28), name, fill=text_c, font=self.font_title)
        if forced_name:
            corp = sc.get('profile_corp')
            if corp:
                cfill = C_WECHAT_GREEN if corp == u'\u5fae\u4fe1' else C_CORP_ORANGE
                draw.text((x0 + 24, 56), u'@' + corp, fill=cfill, font=self.font_sm)
        else:
            draw.text((x0 + 24, 56), u'@\u5fae\u4fe1', fill=C_WECHAT_GREEN, font=self.font_sm)

        y = head_h + 16
        # 信息行：贴近真实企微「备注和标签 / 实名 / 企业名片 / 更多信息」
        if self.rng.random() < 0.65:
            info_rows = [
                (u'\u5907\u6ce8\u548c\u6807\u7b7e', self.rng.choice([u'\u8bbe\u7f6e\u5907\u6ce8\u548c\u63cf\u8ff0', u''])),
                (u'\u5b9e\u540d', self.rng.choice([u'\u5df2\u5b9e\u540d', u'\u672a\u5b9e\u540d', ''])),
                (u'\u4f01\u4e1a\u540d\u7247', self.rng.choice([u'\u817e\u8baf - \u4f01\u4e1a\u5fae\u4fe1', u'\u5916\u90e8\u8054\u7cfb\u4eba', ''])),
                (u'\u66f4\u591a\u4fe1\u606f', ''),
            ]
            use_chevron = True
        else:
            info_rows = [
                (u'\u5907\u6ce8', u'\u8bbe\u7f6e\u5907\u6ce8\u548c\u63cf\u8ff0'),
                (u'\u6807\u7b7e', u'\u8bbe\u7f6e\u6807\u7b7e'),
                (u'\u4f01\u4e1a', self.rng.choice([u'\u817e\u8baf - \u4f01\u4e1a\u5fae\u4fe1', u'\u5916\u90e8\u8054\u7cfb\u4eba', u'\u6df1\u5733\u597d\u51f6\u706b\u79d1\u6280\u6709\u9650\u516c\u53f8', ''])),
                (u'\u6765\u6e90', self.rng.choice([u'\u901a\u8fc7\u5fae\u4fe1\u597d\u53cb\u6dfb\u52a0', u'\u4ece\u7fa4\u804a\u6dfb\u52a0', u'\u4ece\u624b\u673a\u53f7\u7801\u6dfb\u52a0'])),
            ]
            use_chevron = False
            if self.rng.random() < 0.5:
                info_rows.insert(2, (u'\u6dfb\u52a0\u65f6\u95f4', u'2026\u5e749\u670829\u65e5 16:04'))

        for label, val in info_rows:
            draw.text((x0 + 24, y), label, fill=sec_c, font=self.font_sm)
            if val:
                # value toward the right for chevron style; left-aligned for legacy
                if use_chevron:
                    vw, _ = _text_size(draw, val, self.font_nm)
                    draw.text((W - 40 - vw, y), val, fill=text_c, font=self.font_nm)
                else:
                    draw.text((x0 + 100, y), val, fill=text_c, font=self.font_nm)
            if use_chevron:
                chev = u'>'
                cw, ch = _text_size(draw, chev, self.font_nm)
                draw.text((W - 24 - cw, y), chev, fill=sec_c, font=self.font_nm)
            y += 36
            draw.line([(x0 + 24, y - 10), (W - 24, y - 10)], fill=sep_c)

        # --- action buttons: equal-width centered cluster ---
        side_pad = int(self.rng.uniform(0.18, 0.28) * pane_w)
        gap = int(self.rng.uniform(8, 14))
        btn_h = int(self.rng.uniform(36, 44))
        # y 在最后一条分隔线下方约 10px。空白 24–112px，每次不同，
        # 但不要大到把按钮赶到窗口底；放不下就上收，保证整颗按钮在画面内。
        gap = int(self.rng.uniform(24, 112))
        btn_y = y + gap
        limit = H - btn_h - 12
        if btn_y > limit:
            btn_y = limit
        if btn_y < y + 8:
            btn_y = y + 8
        if btn_y + btn_h > H - 4:
            btn_y = H - btn_h - 4
        # Prefer 3 equal when pane wide enough; else 2
        if pane_w >= 380:
            n = 3
            labels_txt = [u'\u53d1\u6d88\u606f', u'\u5199\u90ae\u4ef6', u'\u8bed\u97f3\u901a\u8bdd']
        else:
            n = 2
            labels_txt = [u'\u53d1\u6d88\u606f', u'\u8bed\u97f3\u901a\u8bdd']
        cluster_w = pane_w - 2 * side_pad
        bw = max(64, (cluster_w - (n - 1) * gap) // n)
        # re-center using actual used width (floor division leftover)
        used = n * bw + (n - 1) * gap
        cx = x0 + side_pad + max(0, (cluster_w - used) // 2)

        if dark:
            send_fill = C_PROFILE_SEND_DARK if self.rng.random() < 0.9 else (27, 181, 45)
        else:
            send_fill = C_PROFILE_SEND if self.rng.random() < 0.85 else (21, 182, 40)

        for i, text in enumerate(labels_txt):
            is_send = (i == 0)
            sx0, sy0 = cx, btn_y
            sx1, sy1 = cx + bw, btn_y + btn_h
            if is_send:
                try:
                    draw.rounded_rectangle([sx0, sy0, sx1, sy1], radius=6, fill=send_fill)
                except AttributeError:
                    draw.rectangle([sx0, sy0, sx1, sy1], fill=send_fill)
                tw, th = _text_size(draw, text, self.font_nm)
                draw.text((sx0 + (bw - tw) / 2.0, sy0 + (btn_h - th) / 2.0 - 1),
                          text, fill=C_PROFILE_SEND_TEXT, font=self.font_nm)
                labels.append((CLS_CONTACT_SEND_MESSAGE, sx0, sy0, sx1, sy1))
            else:
                voice_bg = (55, 58, 64) if dark else (245, 246, 247)
                voice_fg = C_DARK_TEXT if dark else C_TEXT
                try:
                    if dark:
                        draw.rounded_rectangle([sx0, sy0, sx1, sy1], radius=6, fill=voice_bg)
                    else:
                        draw.rounded_rectangle([sx0, sy0, sx1, sy1], radius=6,
                                               fill=voice_bg, outline=C_SEP)
                except AttributeError:
                    draw.rectangle([sx0, sy0, sx1, sy1], fill=voice_bg, outline=C_SEP)
                tw, th = _text_size(draw, text, self.font_nm)
                draw.text((sx0 + (bw - tw) / 2.0, sy0 + (btn_h - th) / 2.0 - 1),
                          text, fill=voice_fg, font=self.font_nm)
            cx = sx1 + gap

    # ---------------------------------------------------------------- chat
    def _draw_chat(self, img, draw, labels, sc):
        W, H = sc['w'], sc['h']
        x0 = sc['nav_w'] + sc['list_w']
        chat_w = W - x0
        dark = sc.get('dark', False)
        chat_bg = C_DARK_CHAT_BG if dark else C_CHAT_BG
        title_bg = C_DARK_TITLE_BG if dark else C_TITLE_BG
        sep_c = C_DARK_SEP if dark else C_SEP
        text_c = C_DARK_TEXT if dark else C_TEXT
        text_sec = C_DARK_TEXT_SEC if dark else C_TEXT_SEC
        input_bg = C_DARK_INPUT if dark else C_INPUT_AREA
        placeholder = C_DARK_TEXT_SEC if dark else C_TEXT_PLACEHOLDER
        draw.rectangle([x0, 0, W, H], fill=chat_bg)

        # title header
        title_h = 48
        draw.rectangle([x0, 0, W, title_h], fill=title_bg)
        draw.line([(x0, title_h), (W, title_h)], fill=sep_c)
        title = self.rng.choice(self.names)
        # ~50% 附加绿色「@微信」
        show_wx = self.rng.random() < 0.50
        wx_tag = ' @微信'
        title_draw = _truncate(draw, title, self.font_title, chat_w - (120 if show_wx else 80))
        tw, th = _text_size(draw, title_draw, self.font_title)
        ty = (title_h - th) // 2
        draw.text((x0 + 16, ty), title_draw, fill=text_c, font=self.font_title)
        if show_wx:
            draw.text((x0 + 16 + tw + 4, ty), wx_tag, fill=C_WECHAT_GREEN, font=self.font_title)

        # bottom input region
        input_bar_h = 36
        msg_input_h = int(H * self.rng.uniform(0.10, 0.16))
        msg_input_h = max(70, min(140, msg_input_h))
        send_h = 28
        send_w = 64
        bottom_pad = 10

        input_area_top = H - msg_input_h - input_bar_h
        ib_y0 = input_area_top
        ib_y1 = ib_y0 + input_bar_h
        draw.rectangle([x0, ib_y0, W, H], fill=input_bg)
        draw.line([(x0, ib_y0), (W, ib_y0)], fill=sep_c)

        ibar_names = ['ibar_emoji.png', 'ibar_scissors.png', 'ibar_image.png',
                      'ibar_folder.png', 'ibar_cloud.png', 'ibar_phone.png', 'ibar_more.png']
        ix = x0 + 12
        iy = ib_y0 + (input_bar_h - 22) // 2
        for nm in ibar_names:
            ic = _load_icon(self.icons_dir, nm, 22)
            _paste_rgba(img, ic, (ix, iy))
            ix += 30
        qm = '快速会议'
        qtw, qth = _text_size(draw, qm, self.font_sm)
        draw.text((W - qtw - 40, ib_y0 + (input_bar_h - qth) // 2), qm, fill=text_sec, font=self.font_sm)

        labels.append((CLS_INPUT_BAR, x0 + 8, ib_y0 + 4, x0 + 8 + 30 * len(ibar_names), ib_y1 - 4))

        mi_y0 = ib_y1
        labels.append((CLS_MESSAGE_INPUT, x0 + 8, mi_y0 + 4, W - 8, H - 8))

        sb_x1 = W - 16
        sb_x0 = sb_x1 - send_w
        sb_y1 = H - bottom_pad
        sb_y0 = sb_y1 - send_h
        send_active = sc.get('send_active', self.rng.random() < 0.25)
        s_bg = C_SEND_BG_ACTIVE if send_active else (C_DARK_SEARCH_BG if dark else C_SEND_BG)
        s_fg = C_SEND_TEXT_ACTIVE if send_active else text_sec
        draw.rounded_rectangle([sb_x0, sb_y0, sb_x1, sb_y1], radius=4, fill=s_bg)
        st = '发送(S)'
        stw, sth = _text_size(draw, st, self.font_sm)
        draw.text((sb_x0 + (send_w - stw) / 2, sb_y0 + (send_h - sth) / 2 - 1),
                  st, fill=s_fg, font=self.font_sm)
        labels.append((CLS_SEND_BUTTON, sb_x0, sb_y0, sb_x1, sb_y1))

        msg_top = title_h
        msg_bot = ib_y0
        viewport = (x0, msg_top, W, msg_bot)

        mode = sc['msg_mode']
        if mode == 'empty' or sc['page'] == 'contacts':
            # 空态占位（双圈），不打标签，避免被学成 outgoing_bubble
            cx = x0 + chat_w // 2
            cy = (msg_top + msg_bot) // 2 - 16
            try:
                draw.ellipse([cx - 36, cy - 22, cx - 6, cy + 8], outline=placeholder, width=2)
                draw.ellipse([cx - 10, cy - 8, cx + 28, cy + 28], outline=placeholder, width=2)
            except TypeError:
                draw.ellipse([cx - 36, cy - 22, cx - 6, cy + 8], outline=placeholder)
                draw.ellipse([cx - 10, cy - 8, cx + 28, cy + 28], outline=placeholder)
            tip = '暂无消息' if sc['page'] == 'chat' else '选择联系人开始聊天'
            ttw, tth = _text_size(draw, tip, self.font_md)
            draw.text((x0 + (chat_w - ttw) // 2, cy + 40), tip,
                      fill=placeholder, font=self.font_md)
            return

        msgs = self._build_messages(mode)
        bubble_gap = 10
        # 气泡旁小头像（视觉 only，不新增类、不改气泡标签框）
        avatar_side = int(self.rng.uniform(28, 32))
        av_gap = 8
        max_bubble_w = int(chat_w * self.rng.uniform(0.48, 0.62))

        sizes = []
        for m in msgs:
            sizes.append(self._measure_bubble(draw, m, max_bubble_w))

        total_h = 0
        for m, s in zip(msgs, sizes):
            if m['kind'] in ('text', 'card', 'image'):
                total_h += max(s[1], avatar_side)
            else:
                total_h += s[1]
        total_h += bubble_gap * (len(sizes) + 1)
        view_h = msg_bot - msg_top
        if sc['msg_scroll'] and total_h > view_h:
            max_off = total_h - view_h + 40
            y = msg_top + bubble_gap - self.rng.randint(20, max(40, max_off))
        else:
            if mode in ('sparse', 'incoming', 'outgoing') and total_h < view_h - 40:
                y = msg_top + 20
            else:
                y = msg_bot - total_h - 10
                if y <= msg_top + 10:
                    y = msg_top + 10

        for m, (bw, bh) in zip(msgs, sizes):
            if m['kind'] == 'time':
                tw, th = _text_size(draw, m['text'], self.font_sm)
                tx = x0 + (chat_w - tw) // 2
                ty = y
                if ty + th > msg_top and ty < msg_bot:
                    draw.text((tx, ty), m['text'], fill=text_sec, font=self.font_sm)
                y += th + bubble_gap
                continue

            if m['kind'] in ('card', 'image'):
                row_h = max(bh, avatar_side)
                if m['dir'] == 'in':
                    av_x = x0 + 12
                    bx0 = av_x + avatar_side + av_gap
                else:
                    av_x = W - 12 - avatar_side
                    bx0 = av_x - av_gap - bw
                by0 = y
                av_box = (av_x, by0, av_x + avatar_side, by0 + avatar_side)
                av_vis = _clip_box(av_box, viewport)
                if av_vis:
                    av = _avatar_img(self.avatar_paths, avatar_side, self.rng)
                    vx0, vy0, vx1, vy1 = [int(v) for v in av_vis]
                    crop = av.crop((vx0 - av_x, vy0 - by0,
                                    vx0 - av_x + (vx1 - vx0), vy0 - by0 + (vy1 - vy0)))
                    img.paste(crop, (vx0, vy0), crop if crop.mode == 'RGBA' else None)
                box = (bx0, by0, bx0 + bw, by0 + bh)
                vis = _clip_box(box, viewport)
                if vis:
                    if m['kind'] == 'image':
                        self._draw_image_msg(img, draw, box, m, vis, dark=dark)
                    else:
                        self._draw_card(img, draw, box, m, vis, dark=dark)
                    cls = CLS_INCOMING if m['dir'] == 'in' else CLS_OUTGOING
                    labels.append((cls, vis[0], vis[1], vis[2], vis[3]))
                y += row_h + bubble_gap
                continue

            # text bubble
            row_h = max(bh, avatar_side)
            if m['dir'] == 'in':
                av_x = x0 + 12
                bx0 = av_x + avatar_side + av_gap
                fill = C_INCOMING_ALT if self.rng.random() < 0.35 else C_INCOMING
                if dark:
                    fill = (55, 58, 64) if fill == C_INCOMING else (45, 48, 52)
                cls = CLS_INCOMING
            else:
                av_x = W - 12 - avatar_side
                bx0 = av_x - av_gap - bw
                fill = C_OUTGOING
                cls = CLS_OUTGOING
            by0 = y
            av_box = (av_x, by0, av_x + avatar_side, by0 + avatar_side)
            av_vis = _clip_box(av_box, viewport)
            if av_vis:
                av = _avatar_img(self.avatar_paths, avatar_side, self.rng)
                vx0, vy0, vx1, vy1 = [int(v) for v in av_vis]
                crop = av.crop((vx0 - av_x, vy0 - by0,
                                vx0 - av_x + (vx1 - vx0), vy0 - by0 + (vy1 - vy0)))
                img.paste(crop, (vx0, vy0), crop if crop.mode == 'RGBA' else None)
            box = (bx0, by0, bx0 + bw, by0 + bh)
            vis = _clip_box(box, viewport)
            if vis:
                self._draw_bubble(img, draw, box, m['text'], fill, vis, dark=dark)
                labels.append((cls, vis[0], vis[1], vis[2], vis[3]))
            y += row_h + bubble_gap
            if y > msg_bot + 80:
                break

    def _build_messages(self, mode):
        rng = self.rng
        msgs = []
        if mode == 'incoming':
            n = rng.randint(2, 8)
            dirs = ['in'] * n
        elif mode == 'outgoing':
            n = rng.randint(2, 8)
            dirs = ['out'] * n
        elif mode == 'sparse':
            n = rng.randint(1, 3)
            dirs = [rng.choice(['in', 'out']) for _ in range(n)]
        elif mode == 'dense':
            n = rng.randint(10, 18)
            dirs = [rng.choice(['in', 'out']) for _ in range(n)]
        else:  # mixed
            n = rng.randint(4, 12)
            dirs = [rng.choice(['in', 'out']) for _ in range(n)]

        # optional leading time
        if rng.random() < 0.6:
            msgs.append({'kind': 'time', 'text': rng.choice([
                u'\u661f\u671f\u4e8c 16:02', u'\u6628\u5929 09:30', u'\u521a\u521a',
                u'2024\u5e7403\u670812\u65e5 14:20',
            ])})

        for d in dirs:
            r = rng.random()
            if r < 0.14:
                # 图片消息：明显撑宽/撑高
                aspect = rng.choice(['tall', 'wide', 'square', 'wide', 'tall'])
                if aspect == 'tall':
                    iw = rng.randint(120, 180)
                    ih = rng.randint(180, 280)
                elif aspect == 'wide':
                    iw = rng.randint(180, 280)
                    ih = rng.randint(100, 160)
                else:
                    s = rng.randint(140, 220)
                    iw = ih = s
                msgs.append({
                    'kind': 'image',
                    'dir': d,
                    'iw': iw,
                    'ih': ih,
                })
            elif r < 0.26:
                # 链接/文件等卡片，尺寸略有变化
                style = rng.choice(['link', 'link', 'file'])
                msgs.append({
                    'kind': 'card',
                    'dir': d,
                    'style': style,
                    'text': rng.choice([
                        '产品介绍', '季度报告', '会议邀请', '设计稿预览',
                        '需求文档.docx', '截图说明', '活动海报',
                    ]),
                    'cw': rng.randint(180, 260),
                    'ch': rng.randint(72, 120) if style == 'link' else rng.randint(56, 72),
                })
            else:
                # 文本长短更随机：短 / 中 / 长 / 多句
                base = rng.choice(self.messages)
                length_roll = rng.random()
                if length_roll < 0.25:
                    text = base[:max(2, len(base)//3)] if len(base) > 4 else base
                    # 极短：嗯/好的/收到 等
                    text = rng.choice(['嗯', '好的', '收到', 'OK', '1', '哈哈', base])
                elif length_roll < 0.55:
                    text = base
                elif length_roll < 0.8:
                    text = base + '，' + rng.choice(self.messages)
                else:
                    text = base + '。' + rng.choice(self.messages) + '，' + rng.choice(self.snippets or self.messages)
                msgs.append({'kind': 'text', 'dir': d, 'text': text})
        return msgs

    def _measure_bubble(self, draw, m, max_w):
        if m['kind'] == 'time':
            tw, th = _text_size(draw, m['text'], self.font_sm)
            return (tw, th)
        if m['kind'] == 'image':
            # 图片可接近栏宽，高度独立
            iw = int(m.get('iw', 160))
            ih = int(m.get('ih', 160))
            iw = min(max_w, max(80, iw))
            return (iw, ih)
        if m['kind'] == 'card':
            cw = int(m.get('cw', 220))
            ch = int(m.get('ch', 90))
            return (min(max_w, cw), ch)
        # wrap text
        font = self.font_md
        text = m['text']
        pad_x, pad_y = 12, 10
        lines = self._wrap(draw, text, font, max_w - pad_x * 2)
        line_h = _text_size(draw, u'\u4e2d', font)[1] + 3
        th = pad_y * 2 + line_h * len(lines)
        tw = 0
        for ln in lines:
            tw = max(tw, _text_size(draw, ln, font)[0])
        bw = min(max_w, tw + pad_x * 2)
        bw = max(bw, 40)
        return (int(bw), int(th))

    def _wrap(self, draw, text, font, max_w):
        if not text:
            return [u'']
        lines = []
        cur = u''
        for ch in text:
            trial = cur + ch
            if _text_size(draw, trial, font)[0] <= max_w:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = ch
        if cur:
            lines.append(cur)
        return lines or [u'']

    def _draw_bubble(self, img, draw, box, text, fill, vis, dark=False):
        x0, y0, x1, y1 = [int(v) for v in box]
        # draw full bubble then we rely on later content? Better: draw clipped via crop
        bw = x1 - x0
        bh = y1 - y0
        bubble = Image.new('RGBA', (bw, bh), (0, 0, 0, 0))
        bd = ImageDraw.Draw(bubble)
        bd.rounded_rectangle([0, 0, bw - 1, bh - 1], radius=6, fill=fill + (255,))
        font = self.font_md
        pad_x, pad_y = 12, 10
        lines = self._wrap(bd, text, font, bw - pad_x * 2)
        line_h = _text_size(bd, u'\u4e2d', font)[1] + 3
        ty = pad_y
        tfill = (C_DARK_TEXT if dark else C_TEXT) + (255,)
        if fill == C_OUTGOING:
            tfill = C_TEXT + (255,)
        for ln in lines:
            bd.text((pad_x, ty), ln, fill=tfill, font=font)
            ty += line_h
        # paste visible crop
        vx0, vy0, vx1, vy1 = [int(v) for v in vis]
        src_x0 = vx0 - x0
        src_y0 = vy0 - y0
        crop = bubble.crop((src_x0, src_y0, src_x0 + (vx1 - vx0), src_y0 + (vy1 - vy0)))
        img.paste(crop, (vx0, vy0), crop)

    def _draw_card(self, img, draw, box, m, vis, dark=False):
        x0, y0, x1, y1 = [int(v) for v in box]
        bw, bh = x1 - x0, y1 - y0
        card = Image.new('RGBA', (bw, bh), (0, 0, 0, 0))
        cd = ImageDraw.Draw(card)
        bg = (C_DARK_PANEL if dark else C_CARD_BG) + (255,)
        outline = (C_DARK_SEP if dark else C_CARD_BORDER) + (255,)
        cd.rounded_rectangle([0, 0, bw - 1, bh - 1], radius=6,
                             fill=bg, outline=outline)
        style = m.get('style', 'link')
        title = m.get('text', '链接')
        tfill = (C_DARK_TEXT if dark else C_TEXT) + (255,)
        sfill = (C_DARK_TEXT_SEC if dark else C_TEXT_SEC) + (255,)
        if style == 'file':
            # 文件行：小色块 + 文件名
            cd.rounded_rectangle([10, (bh - 28) // 2, 38, (bh - 28) // 2 + 28],
                                 radius=4, fill=(90, 160, 255, 255))
            cd.text((46, (bh - 14) // 2), _truncate(cd, title, self.font_sm, bw - 56),
                    fill=tfill, font=self.font_sm)
        else:
            thumb_h = max(28, min(bh - 36, int(bh * 0.45)))
            img_fill = (70, 74, 80, 255) if dark else (
                self.rng.randint(160, 210),
                self.rng.randint(170, 220),
                self.rng.randint(180, 230),
                255,
            )
            cd.rounded_rectangle([8, 8, bw - 8, 8 + thumb_h], radius=4, fill=img_fill)
            cd.text((10, 12 + thumb_h), _truncate(cd, title, self.font_sm, bw - 20),
                    fill=tfill, font=self.font_sm)
            sub_y = 12 + thumb_h + 16
            if sub_y + 12 < bh:
                cd.text((10, sub_y), self.rng.choice(['网页', '腾讯文档', '链接']),
                        fill=sfill, font=self.font_sm)
        vx0, vy0, vx1, vy1 = [int(v) for v in vis]
        src_x0 = vx0 - x0
        src_y0 = vy0 - y0
        crop = card.crop((src_x0, src_y0, src_x0 + (vx1 - vx0), src_y0 + (vy1 - vy0)))
        img.paste(crop, (vx0, vy0), crop)

    def _draw_image_msg(self, img, draw, box, m, vis, dark=False):
        """纯图片气泡：随机色块/贴头像图，尺寸由 measure 决定。"""
        x0, y0, x1, y1 = [int(v) for v in box]
        bw, bh = x1 - x0, y1 - y0
        card = Image.new('RGBA', (bw, bh), (0, 0, 0, 0))
        cd = ImageDraw.Draw(card)
        cd.rounded_rectangle([0, 0, bw - 1, bh - 1], radius=8, fill=(0, 0, 0, 0))
        # 优先用真实头像库当「图」，否则色块
        inner = Image.new('RGBA', (bw, bh), (0, 0, 0, 0))
        if self.avatar_paths and self.rng.random() < 0.75:
            src = Image.open(self.rng.choice(self.avatar_paths)).convert('RGBA')
            # cover fill
            sw, sh = src.size
            scale = max(bw / float(sw), bh / float(sh))
            nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
            src = src.resize((nw, nh), Image.LANCZOS)
            cx = (nw - bw) // 2
            cy = (nh - bh) // 2
            src = src.crop((cx, cy, cx + bw, cy + bh))
            inner.paste(src, (0, 0))
        else:
            idraw = ImageDraw.Draw(inner)
            fill = (
                self.rng.randint(40, 200),
                self.rng.randint(40, 200),
                self.rng.randint(40, 200),
                255,
            )
            idraw.rectangle([0, 0, bw, bh], fill=fill)
        # rounded mask
        mask = Image.new('L', (bw, bh), 0)
        md = ImageDraw.Draw(mask)
        md.rounded_rectangle([0, 0, bw - 1, bh - 1], radius=8, fill=255)
        card.paste(inner, (0, 0), mask)
        vx0, vy0, vx1, vy1 = [int(v) for v in vis]
        src_x0 = vx0 - x0
        src_y0 = vy0 - y0
        crop = card.crop((src_x0, src_y0, src_x0 + (vx1 - vx0), src_y0 + (vy1 - vy0)))
        img.paste(crop, (vx0, vy0), crop)


def load_lines(path):
    if not path or not os.path.exists(path):
        return []
    lines = []
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                lines.append(line)
    return lines
