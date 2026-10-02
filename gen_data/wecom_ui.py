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


def _load_nav_icon(icons_dir, normal, selected_blue, selected_white, size, selected):
    """选中态：优先蓝实心 *_selected.png；否则把 *_selected_white 染成 blue_btn；再退常态。"""
    if not selected:
        return _load_icon(icons_dir, normal, size)
    blue_path = os.path.join(icons_dir, selected_blue)
    if os.path.exists(blue_path):
        return _load_icon(icons_dir, selected_blue, size)
    white_path = os.path.join(icons_dir, selected_white)
    if os.path.exists(white_path):
        im = _load_icon(icons_dir, selected_white, size)
        return _recolor_keep_alpha(im, C_SELECTED_NAV_FG)
    return _load_icon(icons_dir, normal, size)


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
        'contacts_profile',
        'contacts_profile_dark',
    )

    def make_scenario(self, preset, jitter=True):
        """构造高保真典型页场景。preset 见 PRESETS。"""
        rng = self.rng
        name = (preset or '').strip().lower().replace('-', '_')
        if name == 'contacts_profile_light':
            name = 'contacts_profile'
        dark = False
        if name == 'contacts_profile_dark':
            name = 'contacts_profile'
            dark = True

        if name == 'chat_narrow':
            w, h = 1100, 700
            if jitter:
                w = rng.randint(980, 1200)
                h = rng.randint(640, 780)
            nav_wide = False
            nav_w = rng.randint(56, 64) if jitter else 60
            list_w = int(w * (rng.uniform(0.22, 0.28) if jitter else 0.25))
            page = 'chat'
            n_conv = rng.choice([8, 10, 12, 14]) if jitter else 12
            msg_mode = rng.choice(['mixed', 'dense', 'incoming']) if jitter else 'mixed'
            chat_badge = rng.choice([1, 2, 3, 5, 9, 12, 42, 99, 120, 'dot'])
            contacts_badge = rng.choice([None, None, 0, 1])
            dark = False
        elif name == 'chat_wide':
            w, h = 1200, 800
            if jitter:
                w = rng.randint(1100, 1400)
                h = rng.randint(720, 900)
            nav_wide = True
            nav_w = rng.randint(150, 175) if jitter else 160
            list_w = int(w * (rng.uniform(0.20, 0.26) if jitter else 0.23))
            page = 'chat'
            n_conv = rng.choice([8, 10, 12, 15]) if jitter else 12
            msg_mode = rng.choice(['mixed', 'dense', 'outgoing']) if jitter else 'mixed'
            chat_badge = rng.choice([1, 2, 3, 7, 12, 42, 99, 120])
            contacts_badge = rng.choice([None, 0, 1])
            dark = False
        elif name == 'contacts_profile':
            w, h = 1100, 720
            if jitter:
                w = rng.randint(1000, 1400)
                h = rng.randint(640, 860)
            nav_wide = rng.random() < 0.55 if jitter else True
            if nav_wide:
                nav_w = rng.randint(150, 175) if jitter else 160
            else:
                nav_w = rng.randint(56, 64) if jitter else 60
            list_w = int(w * (rng.uniform(0.20, 0.28) if jitter else 0.24))
            page = 'contacts'
            n_conv = rng.choice([6, 8, 10, 12]) if jitter else 8
            msg_mode = 'empty'
            chat_badge = rng.choice([2, 3, 5, 7, 12, 42])
            contacts_badge = rng.choice([None, None, 0, 1])
            # dark already set if contacts_profile_dark
        else:
            raise ValueError('unknown preset %r; choose from %s' % (preset, ', '.join(self.PRESETS)))

        list_scroll = False
        msg_scroll = page == 'chat' and msg_mode in ('mixed', 'dense') and (rng.random() < 0.35)
        # force some unread badges on conversation rows for chat presets
        unread_rate = 0.45 if page == 'chat' else 0.0
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
            'selected_idx': 0 if n_conv > 0 else -1,
            'dark': dark,
            'preset': preset,
            'unread_rate': unread_rate,
            'extra_nav_dots': True if page == 'chat' else False,
        }

    def sample_scenario(self, preset=None):
        """随机采样多样性场景；preset 非空则走高保真模板。
        无 preset 时约 40% 的随机样本也会偏向典型页，保证训练集常碰到高保真布局。
        """
        if preset:
            return self.make_scenario(preset, jitter=True)

        rng = self.rng
        # 提高典型页命中率
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
        if page == 'contacts':
            n_conv = rng.choice([3, 5, 8, 12, 18])

        msg_mode = rng.choice(['empty', 'incoming', 'outgoing', 'mixed', 'sparse', 'dense'])
        list_scroll = rng.random() < 0.45 and n_conv >= 6
        msg_scroll = rng.random() < 0.4 and msg_mode in ('mixed', 'dense', 'incoming', 'outgoing')

        # None=无角标；0/'dot'=红点；正数=数字
        badge = rng.choice([None, None, 0, 1, 2, 3, 5, 9, 12, 42, 88, 99, 120, 200])
        contacts_badge = rng.choice([None, None, None, 0, 1, 2, 4])

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
            'extra_nav_dots': rng.random() < 0.35,
        }

    def render(self, scenario=None, preset=None):
        sc = scenario or self.sample_scenario(preset=preset)
        W, H = sc['w'], sc['h']
        img = Image.new('RGB', (W, H), C_WIN_BG)
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

        # --- right chat ---
        if sc['page'] == 'contacts':
            self._draw_contact_profile(img, draw, labels, sc)
        else:
            self._draw_chat(img, draw, labels, sc)

        # 窗口细边框
        draw.rectangle([0, 0, W - 1, H - 1], outline=(200, 205, 210))

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
        draw.rectangle([0, 0, nav_w, H], fill=C_NAV_BG)

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
            draw.text((ax + av_size + 8, ay + 8), name, fill=C_TEXT, font=self.font_md)

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
        # 偶发给非 chat/contacts 项挂红点（视觉多样性；无类别框）
        if sc.get('extra_nav_dots'):
            for j in (1, 2, 4, 5, 6):  # mail/docs/cal/todo/meet
                if self.rng.random() < 0.22:
                    # mutate tuple -> list then back
                    it = list(items[j])
                    it[3] = 0  # plain red dot
                    items[j] = tuple(it)

        y = ay + av_size + 18
        icon_sz = 22 if wide else 24
        badge_fill = C_BADGE

        for key, text, cls_id, badge, icon_normal, icon_sel_blue, icon_sel_white in items:
            selected = (sc['page'] == key)
            if wide:
                row_h = 40
                if selected:
                    draw.rounded_rectangle([6, y, nav_w - 6, y + row_h], radius=6, fill=C_SELECTED_NAV)
                ix = 14
                iy = y + (row_h - icon_sz) // 2
                icon = _load_nav_icon(self.icons_dir, icon_normal, icon_sel_blue,
                                     icon_sel_white, icon_sz, selected)
                _paste_rgba(img, icon, (ix, iy))
                tw, th = _text_size(draw, text, self.font_nav)
                tx = ix + icon_sz + 10
                ty = y + (row_h - th) // 2
                tfill = C_SELECTED_NAV_FG if selected else C_TEXT
                draw.text((tx, ty), text, fill=tfill, font=self.font_nav)
                box = (6, y, nav_w - 6, y + row_h)
                if badge is not None:
                    # 宽栏：数字角标靠行尾；纯红点贴图标右上角（与截图一致）
                    if badge == 0 or badge == 'dot':
                        bx = ix + icon_sz - 1
                        by = iy + 1
                    else:
                        bx = nav_w - 18
                        by = y + row_h // 2
                    _draw_badge(draw, bx, by, badge, self.font_badge, fill=badge_fill)
                if cls_id is not None:
                    labels.append((cls_id, box[0], box[1], box[2], box[3]))
                y += row_h + 2
            else:
                # narrow: icon above text；角标贴图标右上角（略重叠）
                cell_h = 52
                cell_w = nav_w - 4
                cx0 = 2
                if selected:
                    draw.rounded_rectangle([cx0, y, cx0 + cell_w, y + cell_h - 4],
                                          radius=6, fill=C_SELECTED_NAV)
                ix = (nav_w - icon_sz) // 2
                iy = y + 4
                icon = _load_nav_icon(self.icons_dir, icon_normal, icon_sel_blue,
                                     icon_sel_white, icon_sz, selected)
                _paste_rgba(img, icon, (ix, iy))
                tw, th = _text_size(draw, text, self.font_sm)
                tx = (nav_w - tw) // 2
                ty = iy + icon_sz + 2
                tfill = C_SELECTED_NAV_FG if selected else C_TEXT_SEC
                draw.text((tx, ty), text, fill=tfill, font=self.font_sm)
                # label box around icon+text block (badge 计入同一框)
                box = (cx0, y, cx0 + cell_w, y + cell_h - 4)
                if badge is not None:
                    # 中心落在图标右上角，红点/数字略压住图标边缘
                    _draw_badge(draw, ix + icon_sz - 1, iy + 1, badge, self.font_badge,
                                fill=badge_fill)
                if cls_id is not None:
                    labels.append((cls_id, box[0], box[1], box[2], box[3]))
                y += cell_h

        # bottom more
        more = _load_icon(self.icons_dir, 'nav_more.png', 20)
        _paste_rgba(img, more, ((nav_w - 20) // 2, H - 40))

    # -------------------------------------------------------------- middle
    def _draw_middle(self, img, draw, labels, sc):
        W, H = sc['w'], sc['h']
        nav_w = sc['nav_w']
        list_w = sc['list_w']
        x0 = nav_w
        draw.rectangle([x0, 0, x0 + list_w, H], fill=C_LIST_BG)
        # right separator
        draw.line([(x0 + list_w - 1, 0), (x0 + list_w - 1, H)], fill=C_SEP)

        # search bar row（截图约 32–34px 高、圆角胶囊）
        search_h = 32
        pad = 12
        plus_sz = 26
        sy = 12
        sx = x0 + pad
        sw = list_w - pad * 2 - plus_sz - 8
        sh = search_h
        draw.rounded_rectangle([sx, sy, sx + sw, sy + sh], radius=6, fill=C_SEARCH_BG)
        # search icon + placeholder
        sicon = _load_icon(self.icons_dir, 'search.png', 16)
        _paste_rgba(img, sicon, (sx + 8, sy + (sh - 16) // 2))
        draw.text((sx + 28, sy + (sh - 13) // 2), u'\u641c\u7d22', fill=C_TEXT_PLACEHOLDER, font=self.font_md)
        labels.append((CLS_SEARCH_BAR, sx, sy, sx + sw, sy + sh))

        # plus button (not a labeled class)
        px = sx + sw + 8
        py = sy + (sh - plus_sz) // 2
        plus = _load_icon(self.icons_dir, 'plus.png', plus_sz)
        _paste_rgba(img, plus, (px, py))

        # list viewport
        list_top = sy + sh + 8
        list_bot = H
        viewport = (x0, list_top, x0 + list_w, list_bot)

        n = sc['n_conv']
        row_h = 62
        # scroll offset: partially clip top/bottom
        if sc['list_scroll'] and n > 0:
            # negative offset -> first item partially above viewport
            offset = self.rng.randint(-int(row_h * 0.7), int(row_h * 0.4))
        else:
            offset = 0

        y = list_top + offset
        is_contacts = sc['page'] == 'contacts'
        item_cls = CLS_CONTACT_ITEM if is_contacts else CLS_CONVERSATION_ITEM

        for i in range(n):
            row_box = (x0, y, x0 + list_w, y + row_h)
            visible = _clip_box(row_box, viewport)
            selected = (i == sc['selected_idx'])

            if visible:
                # draw only visible portion background
                vx0, vy0, vx1, vy1 = visible
                if selected:
                    draw.rectangle([vx0, vy0, vx1, vy1], fill=C_SELECTED_LIST)
                # content drawn in full row coords but clipped visually by not drawing outside? 
                # We draw into full image; content outside viewport still paints into title/search —
                # so clip drawing by using a temp or only draw if mostly visible.
                # Simpler: draw into a row crop then paste clipped.
                row_im = Image.new('RGBA', (list_w, row_h), (0, 0, 0, 0))
                rd = ImageDraw.Draw(row_im)
                if selected:
                    rd.rectangle([0, 0, list_w, row_h], fill=C_SELECTED_LIST + (255,))

                av_sz = 40
                is_group = (not is_contacts) and (self.rng.random() < 0.35)
                if is_group:
                    av = _group_avatar_img(self.avatar_paths, av_sz, self.rng)
                else:
                    av = _avatar_img(self.avatar_paths, av_sz, self.rng)
                av_x = 12
                av_y = (row_h - av_sz) // 2
                _paste_rgba(row_im, av, (av_x, av_y))

                name = self.rng.choice(self.names)
                name_font = self.font_nm
                name_fill = C_SELECTED_LIST_TEXT if selected else C_TEXT
                snip_fill = (220, 230, 245) if selected else C_TEXT_SEC
                time_fill = snip_fill

                name_x = 12 + av_sz + 10
                max_name_w = list_w - name_x - 56
                name_t = _truncate(rd, name, name_font, max_name_w)
                rd.text((name_x, 12), name_t, fill=name_fill, font=name_font)

                if not is_contacts:
                    snip = self.rng.choice(self.snippets)
                    snip_t = _truncate(rd, snip, self.font_sm, list_w - name_x - 16)
                    rd.text((name_x, 36), snip_t, fill=snip_fill, font=self.font_sm)
                    # time
                    times = [u'\u521a\u521a', u'1\u5206\u949f\u524d', u'16:10', u'\u6628\u5929', u'\u5468\u4e00', '09:30']
                    t = self.rng.choice(times)
                    tw, th = _text_size(rd, t, self.font_sm)
                    rd.text((list_w - tw - 12, 12), t, fill=time_fill, font=self.font_sm)
                    # unread badge：贴在头像右上角（略重叠），仅视觉，不另标类
                    unread_rate = sc.get('unread_rate', 0.25)
                    if self.rng.random() < unread_rate:
                        bc = self.rng.choice([0, 1, 1, 2, 3, 5, 8, 12, 42, 99, 120])
                        # 中心 ≈ 头像右上角
                        _draw_badge(rd, av_x + av_sz - 1, av_y + 1, bc, self.font_badge)
                else:
                    # contact: just name (maybe company subtitle)
                    sub = self.rng.choice([u'\u4ea7\u54c1\u90e8', u'\u6280\u672f\u4e2d\u5fc3', u'\u5e02\u573a\u90e8', u''])
                    if sub:
                        rd.text((name_x, 36), sub, fill=snip_fill, font=self.font_sm)

                # separator
                if not selected:
                    rd.line([(12 + av_sz + 10, row_h - 1), (list_w, row_h - 1)], fill=C_SEP + (255,))

                # paste only the visible part of the row
                src_y0 = max(0, int(vy0 - y))
                src_y1 = src_y0 + int(vy1 - vy0)
                crop = row_im.crop((0, src_y0, list_w, src_y1))
                img.paste(crop, (int(vx0), int(vy0)), crop)

                labels.append((item_cls, vx0, vy0, vx1, vy1))
                # 单聊/群聊：头像区域（仅会话列表；可见部分裁剪）
                if not is_contacts:
                    type_cls = CLS_GROUP_CHAT if is_group else CLS_SINGLE_CHAT
                    ax0 = x0 + av_x
                    ay0 = y + av_y
                    av_box = (ax0, ay0, ax0 + av_sz, ay0 + av_sz)
                    av_vis = _clip_box(av_box, viewport)
                    if av_vis:
                        labels.append((type_cls, av_vis[0], av_vis[1], av_vis[2], av_vis[3]))

            y += row_h
            if y > list_bot + row_h:
                break

    # -------------------------------------------------------- contact profile
    def _draw_contact_profile(self, img, draw, labels, sc):
        """通讯录/客户详情右侧：类 13「发消息」。
        窄窗：发消息 + 语音通话；宽窗：发消息 + 写邮件 + 语音通话，发消息随栏宽拉长。
        """
        W, H = sc['w'], sc['h']
        x0 = sc['nav_w'] + sc['list_w']
        pane_w = W - x0
        dark = sc.get('dark', False)
        bg = C_DARK_BG if dark else (248, 248, 250)
        text_c = C_DARK_TEXT if dark else C_TEXT
        sec_c = C_DARK_TEXT_SEC if dark else C_TEXT_SEC
        draw.rectangle([x0, 0, W, H], fill=bg)

        head_h = int(H * 0.22)
        head_bg = C_DARK_PANEL if dark else (255, 255, 255)
        draw.rectangle([x0, 0, W, head_h], fill=head_bg)

        name = self.rng.choice(self.names)
        av_sz = int(self.rng.uniform(56, 72))
        av = _avatar_img(self.avatar_paths, av_sz, self.rng)
        ax = W - av_sz - 24
        ay = 20
        _paste_rgba(img, av, (ax, ay))

        draw.text((x0 + 24, 28), name, fill=text_c, font=self.font_title)
        draw.text((x0 + 24, 56), '@微信', fill=(7, 193, 96), font=self.font_sm)

        y = head_h + 16
        rows = [
            ('备注', '设置备注和描述'),
            ('标签', '设置标签'),
            ('企业', self.rng.choice(['腾讯 - 企业微信', '外部联系人', '深圳好凶火科技有限公司', ''])),
            ('来源', self.rng.choice(['通过微信好友添加', '从群聊添加', '从手机号码添加'])),
        ]
        if self.rng.random() < 0.5:
            rows.insert(2, ('添加时间', '2026年9月29日 16:04'))
        for label, val in rows:
            draw.text((x0 + 24, y), label, fill=sec_c, font=self.font_sm)
            if val:
                draw.text((x0 + 100, y), val, fill=text_c, font=self.font_nm)
            y += 32
            draw.line([(x0 + 24, y - 8), (W - 24, y - 8)],
                      fill=C_SEP if not dark else (60, 64, 70))

        # --- action buttons: width follows pane ---
        margin = 24
        gap = 10
        btn_h = int(self.rng.uniform(36, 44))
        btn_y = H - btn_h - int(self.rng.uniform(16, 28))
        avail = pane_w - 2 * margin
        # 宽栏 ≈3 钮；窄栏 2 钮。也用随机再拆一档，避免和窗口强绑定
        three = pane_w >= 420 or (pane_w >= 340 and self.rng.random() < 0.55)
        if three:
            # 发消息略宽，写邮件/语音通话均分剩余
            send_w = int(avail * self.rng.uniform(0.38, 0.48))
            rest = avail - send_w - 2 * gap
            other_w = max(70, rest // 2)
            # 纠正取整误差
            send_w = avail - 2 * other_w - 2 * gap
            labels_btn = [
                ('发消息', True, send_w),
                ('写邮件', False, other_w),
                ('语音通话', False, other_w),
            ]
        else:
            send_w = int(avail * self.rng.uniform(0.52, 0.62))
            voice_w = avail - send_w - gap
            labels_btn = [
                ('发消息', True, send_w),
                ('语音通话', False, voice_w),
            ]

        if dark:
            send_fill = C_PROFILE_SEND_DARK if self.rng.random() < 0.9 else (27, 181, 45)  # green_wechat dark
        else:
            send_fill = C_PROFILE_SEND if self.rng.random() < 0.85 else (21, 182, 40)  # green_wechat
        cx = x0 + margin
        for text, is_send, bw in labels_btn:
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
        draw.rectangle([x0, 0, W, H], fill=C_CHAT_BG)

        # title header
        title_h = 48
        draw.rectangle([x0, 0, W, title_h], fill=C_TITLE_BG)
        draw.line([(x0, title_h), (W, title_h)], fill=C_SEP)
        title = self.rng.choice(self.names)
        title = _truncate(draw, title, self.font_title, chat_w - 80)
        tw, th = _text_size(draw, title, self.font_title)
        draw.text((x0 + 16, (title_h - th) // 2), title, fill=C_TEXT, font=self.font_title)

        # bottom input region
        input_bar_h = 36
        msg_input_h = int(H * self.rng.uniform(0.10, 0.16))
        msg_input_h = max(70, min(140, msg_input_h))
        send_h = 28
        send_w = 64
        bottom_pad = 10

        input_area_top = H - msg_input_h - input_bar_h
        # input_bar
        ib_y0 = input_area_top
        ib_y1 = ib_y0 + input_bar_h
        draw.rectangle([x0, ib_y0, W, H], fill=C_INPUT_AREA)
        draw.line([(x0, ib_y0), (W, ib_y0)], fill=C_SEP)

        # toolbar icons
        ibar_names = ['ibar_emoji.png', 'ibar_scissors.png', 'ibar_image.png',
                      'ibar_folder.png', 'ibar_cloud.png', 'ibar_phone.png', 'ibar_more.png']
        ix = x0 + 12
        iy = ib_y0 + (input_bar_h - 22) // 2
        for nm in ibar_names:
            ic = _load_icon(self.icons_dir, nm, 22)
            _paste_rgba(img, ic, (ix, iy))
            ix += 30
        # right side quick meeting text
        qm = u'\u5feb\u901f\u4f1a\u8bae'
        qtw, qth = _text_size(draw, qm, self.font_sm)
        draw.text((W - qtw - 40, ib_y0 + (input_bar_h - qth) // 2), qm, fill=C_TEXT_SEC, font=self.font_sm)

        # input_bar label: left cluster of icons
        labels.append((CLS_INPUT_BAR, x0 + 8, ib_y0 + 4, x0 + 8 + 30 * len(ibar_names), ib_y1 - 4))

        # message_input area (big white zone)
        mi_y0 = ib_y1
        mi_y1 = H - bottom_pad - send_h - 4
        # keep a bit of space for send button row
        labels.append((CLS_MESSAGE_INPUT, x0 + 8, mi_y0 + 4, W - 8, H - 8))

        # send button
        sb_x1 = W - 16
        sb_x0 = sb_x1 - send_w
        sb_y1 = H - bottom_pad
        sb_y0 = sb_y1 - send_h
        send_active = sc.get('send_active', self.rng.random() < 0.25)
        s_bg = C_SEND_BG_ACTIVE if send_active else C_SEND_BG
        s_fg = C_SEND_TEXT_ACTIVE if send_active else C_SEND_TEXT
        draw.rounded_rectangle([sb_x0, sb_y0, sb_x1, sb_y1], radius=4, fill=s_bg)
        st = u'发送(S)'
        stw, sth = _text_size(draw, st, self.font_sm)
        draw.text((sb_x0 + (send_w - stw) / 2, sb_y0 + (send_h - sth) / 2 - 1),
                  st, fill=s_fg, font=self.font_sm)
        labels.append((CLS_SEND_BUTTON, sb_x0, sb_y0, sb_x1, sb_y1))

        # message viewport
        msg_top = title_h
        msg_bot = ib_y0
        viewport = (x0, msg_top, W, msg_bot)

        mode = sc['msg_mode']
        if mode == 'empty' or sc['page'] == 'contacts':
            # empty state hint
            tip = u'\u6682\u65e0\u6d88\u606f' if sc['page'] == 'chat' else u'\u9009\u62e9\u8054\u7cfb\u4eba\u5f00\u59cb\u804a\u5929'
            ttw, tth = _text_size(draw, tip, self.font_md)
            draw.text((x0 + (chat_w - ttw) // 2, (msg_top + msg_bot) // 2), tip,
                      fill=C_TEXT_PLACEHOLDER, font=self.font_md)
            return

        # build message list
        msgs = self._build_messages(mode)
        bubble_gap = 10
        avatar_side = 0  # refs often without per-message avatars
        max_bubble_w = int(chat_w * 0.55)

        # estimate total height for scroll
        sizes = []
        for m in msgs:
            sizes.append(self._measure_bubble(draw, m, max_bubble_w))

        total_h = sum(s[1] for s in sizes) + bubble_gap * (len(sizes) + 1)
        view_h = msg_bot - msg_top
        if sc['msg_scroll'] and total_h > view_h:
            # start partially above
            max_off = total_h - view_h + 40
            y = msg_top + bubble_gap - self.rng.randint(20, max(40, max_off))
        else:
            # bottom-align if not scrolling, or top if sparse
            if mode in ('sparse', 'incoming', 'outgoing') and total_h < view_h - 40:
                y = msg_top + 20
            else:
                y = msg_bot - total_h - 10
                if y > msg_top + 10:
                    pass
                else:
                    y = msg_top + 10

        for m, (bw, bh) in zip(msgs, sizes):
            if m['kind'] == 'time':
                tw, th = _text_size(draw, m['text'], self.font_sm)
                tx = x0 + (chat_w - tw) // 2
                ty = y
                # only draw if somewhat visible
                if ty + th > msg_top and ty < msg_bot:
                    draw.text((tx, ty), m['text'], fill=C_TEXT_SEC, font=self.font_sm)
                y += th + bubble_gap
                continue

            if m['kind'] == 'card':
                bh = max(bh, 80)
                bw = min(max_bubble_w, 220)
                if m['dir'] == 'in':
                    bx0 = x0 + 16
                else:
                    bx0 = W - 16 - bw
                by0 = y
                box = (bx0, by0, bx0 + bw, by0 + bh)
                vis = _clip_box(box, viewport)
                if vis:
                    self._draw_card(img, draw, box, m, vis)
                    cls = CLS_INCOMING if m['dir'] == 'in' else CLS_OUTGOING
                    labels.append((cls, vis[0], vis[1], vis[2], vis[3]))
                y += bh + bubble_gap
                continue

            # text bubble
            if m['dir'] == 'in':
                bx0 = x0 + 16
                fill = C_INCOMING_ALT if self.rng.random() < 0.35 else C_INCOMING
                cls = CLS_INCOMING
            else:
                bx0 = W - 16 - bw
                fill = C_OUTGOING
                cls = CLS_OUTGOING
            by0 = y
            box = (bx0, by0, bx0 + bw, by0 + bh)
            vis = _clip_box(box, viewport)
            if vis:
                self._draw_bubble(img, draw, box, m['text'], fill, vis)
                labels.append((cls, vis[0], vis[1], vis[2], vis[3]))
            y += bh + bubble_gap
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
            if rng.random() < 0.12:
                msgs.append({
                    'kind': 'card',
                    'dir': d,
                    'text': rng.choice([u'\u4ea7\u54c1\u4ecb\u7ecd', u'\u5b63\u5ea6\u62a5\u544a', u'\u4f1a\u8bae\u9080\u8bf7']),
                })
            else:
                text = rng.choice(self.messages)
                # sometimes long
                if rng.random() < 0.2:
                    text = text + u'\uff0c' + rng.choice(self.messages)
                msgs.append({'kind': 'text', 'dir': d, 'text': text})
        return msgs

    def _measure_bubble(self, draw, m, max_w):
        if m['kind'] == 'time':
            tw, th = _text_size(draw, m['text'], self.font_sm)
            return (tw, th)
        if m['kind'] == 'card':
            return (min(max_w, 220), 90)
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

    def _draw_bubble(self, img, draw, box, text, fill, vis):
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
        for ln in lines:
            bd.text((pad_x, ty), ln, fill=C_TEXT + (255,), font=font)
            ty += line_h
        # paste visible crop
        vx0, vy0, vx1, vy1 = [int(v) for v in vis]
        src_x0 = vx0 - x0
        src_y0 = vy0 - y0
        crop = bubble.crop((src_x0, src_y0, src_x0 + (vx1 - vx0), src_y0 + (vy1 - vy0)))
        img.paste(crop, (vx0, vy0), crop)

    def _draw_card(self, img, draw, box, m, vis):
        x0, y0, x1, y1 = [int(v) for v in box]
        bw, bh = x1 - x0, y1 - y0
        card = Image.new('RGBA', (bw, bh), (0, 0, 0, 0))
        cd = ImageDraw.Draw(card)
        cd.rounded_rectangle([0, 0, bw - 1, bh - 1], radius=6,
                             fill=C_CARD_BG + (255,), outline=C_CARD_BORDER + (255,))
        # fake image area
        cd.rectangle([8, 8, bw - 8, 48], fill=(200, 210, 220, 255))
        title = m.get('text', u'\u94fe\u63a5')
        cd.text((10, 54), _truncate(cd, title, self.font_sm, bw - 20),
                fill=C_TEXT + (255,), font=self.font_sm)
        cd.text((10, 72), u'\u7f51\u9875', fill=C_TEXT_SEC + (255,), font=self.font_sm)
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
