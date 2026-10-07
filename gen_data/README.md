# WeCom (企业微信) 合成 UI 数据集生成器

离线程序：用 Pillow 把「图标/头像图库 + 姓名/消息文本」合成假的企业微信桌面窗口，
并写出 YOLO detect 标签（每张图一个 `.jpg`/`.png` + 同名 `.txt`）。

**不访问网络 / 不调任何 API。** 不训练模型，只负责 `gen_data`。

## 目录

```
gen_data/
  synthesize.py          # CLI 入口
  wecom_ui.py            # 布局 / 绘制 / 标签框
  export_wework_icons.py # 从本机企微客户端 Assets.car 导出真图标（nav / grp 两套预设）
  classes.txt            # 与父目录一致的 13 类 c13（list_item 合并了会话行/联系人行）
  config.example.yaml
  requirements.txt       # pillow, pyyaml(可选)
  assets/
    icons/               # 渲染器实际取图的图标（已换成客户端真图）
    icons_wecom/         # 导出参考目录：全量导出 + _pdf/ 矢量母版
    _icons_backup_20261002/  # 替换前的占位图备份
    avatars/             # 占位头像（可替换为真实裁切）
    names.txt / messages.txt / snippets.txt
  refs/                  # 风格参考截图（narrow_nav / wide_nav / group_filter_*）
  out/images/  out/labels/
```

## 类别（不可改序）

| id | name |
|----|------|
| 0 | self_avatar |
| 1 | nav_chat_icon |
| 2 | nav_contacts_icon |
| 3 | search_bar |
| 4 | list_item（会话列表行 / 通讯录行 / 搜索结果行 / 客户行） |
| 5 | send_button |
| 6 | incoming_bubble |
| 7 | outgoing_bubble |
| 8 | input_bar（工具条整行，在白色输入区上方） |
| 9 | single_chat（单聊） |
| 10 | group_chat（群聊） |
| 11 | contact_send_message（联系人详情「发消息」） |
| 12 | nav_groups_icon（宽栏左下「分组」区标题图标） |

列表行统一为 `list_item`(4)：会话行、通讯录行、搜索结果行、客户行外观接近，合成时同一类；
是会话还是联系人由 llm_rpa 按所在页面决定。

`list_item` 框几何（`wecom_ui.py` 的 `_row_rect` 是唯一真值来源）：
左边界取栏内容区左边界，右边界取栏右分隔线所在像素列，上下取整行行高。
同一张图内所有 `list_item` 等宽等高；不同图栏宽可左右拉动，宽度随之变化，但绝不越过栏右分隔线。

会话列表行标 `list_item`(4)；头像另标 `single_chat`(9) 或 `group_chat`(10)。
通讯录页右侧详情生成 `contact_send_message`(11)，随机深色/浅色主题。
宽栏左下的「分组」标题图标标 `nav_groups_icon`(12)；其下 7 项筛选行（未读/@我/单聊/群聊/
内部聊天/外部聊天/标记）**不单独出框**，只作为界面上下文。

## 依赖

```bash
cd /Users/admin/Desktop/workspace/yolo26/gen_data
pip install -r requirements.txt
# 本机已有 Pillow 9.x 时可直接跑
```

## 运行

```bash
python synthesize.py --count 50 --out out_c13 \
  --avatars assets/avatars --icons assets/icons \
  --names assets/names.txt --messages assets/messages.txt \
  --snippets assets/snippets.txt --seed 0
```

输出：

- `out_c13/wxsyn_00000.jpg` …
- `out_c13/wxsyn_00000.txt` …（YOLO：`class xc yc w h`，相对整图 0–1）
- `out_c13/data_synth.yaml`

切分：`python split_c13.py`（`out_c13` → `splits_c13`，每个 preset 90/10），训练用 `data_c13.yaml`。
旧的 `out_c14` / `splits_c14` / `data_c14.yaml` / `split_c14.py` 保留不动，仅对应旧 14 类。

## 标签与遮挡规则

- 框裁剪到可见区域：列表/消息区若因滚动被裁切，**只标可见部分**。
- 可见高度 &lt; 4px，或面积比 &lt; `5e-5` 的框丢弃。
- 导航角标（红点/数字/99+ 三点）画在图标上，**仍只出一个 icon 框**（badge 算 occlusion，不单独成类）。
- `contacts` 场景的通讯录行、`chat` 场景的会话行、搜索结果行、客户行一律标 `list_item`(4)。
- 选中的「消息」导航高亮蓝底；通讯录页则高亮 contacts。

## 占位资源 vs 你需要替换的

| 已有占位 | 建议你换成真实素材 |
|----------|-------------------|
| `assets/icons/nav_*.png` 几何图标 | **已解决** → 用 `export_wework_icons.py` 从客户端导出真图，见下节 |
| `assets/icons/ibar_*.png` 工具栏 | 输入栏真实 emoji/截图/图片等小图标 |
| `assets/icons/search.png`, `plus.png` | 搜索放大镜、右上角 + |
| `assets/avatars/avatar_*.png` 色块字 | 真实头像图库（方图即可，合成时会缩放到行高） |
| `names.txt` / `messages.txt` / `snippets.txt` | 可追加你业务里的常用人名与话术 |

## 导出真实导航图标（export_wework_icons.py）

企业微信**没有**发布桌面端图标下载。官方发布的 WeUI for Work
（<https://weui.io/work/>）只有移动端 18 个 glyph，不含桌面导航。
真图标打包在本机客户端的：

```
/Applications/企业微信.app/Contents/Resources/Assets.car   # 46.7 MB，3934 个命名资源
```

`export_wework_icons.py` 只用 macOS 自带工具（`assetutil` + `sips`）把图标抠成 PNG：

```bash
# 看映射表 + 每个资源在本机是否可用（矢量 / 位图 / pt 尺寸 / 染色色值）
python export_wework_icons.py --list
python export_wework_icons.py --preset grp --list

# 导出整套导航图标 + 白色版，并保留矢量母版
python export_wework_icons.py --out assets/icons_wecom --keep-pdf --white selected

# 导出「会话分组筛选」面板图标（按面板实测色自动染色）
python export_wework_icons.py --preset grp --out assets/icons --keep-pdf --overwrite
```

两个预设：`nav`（左侧主导航，22/20/16pt）与 `grp`（会话分组筛选面板，统一 16pt）。
`--preset` 支持逗号多选（`--preset nav,grp`），`--names` / `--map` 会叠加在预设之上。

**原理**：矢量资源的 PDF 原文在 car 里是**明文**存放的（全库 3130 个未压缩 PDF），
所以流程是 `assetutil -n <名> -o tmp.car`（裁剪到只剩该资源）→ 按 `%PDF…%%EOF` 切片 →
`sips` 光栅化。不需要 Xcode，不需要第三方库（只有 `--white` / `--tint` 需要 Pillow）。

**尺寸**：默认输出资源**原生 pt 尺寸**（`*_16` → 16×16），也就是渲染器实际取图的尺寸，
1:1 最清晰。注意 `sips` 对 PDF 只按 MediaBox 光栅化（固定 72dpi），`--size` 是光栅化**之后**
的重采样——放大只会糊、不增加信息（`-s dpiWidth` 对 PDF 无效，实测 72/144/288 都还是 16px），
非必要别用。

**踩过的两个坑**（脚本里都已处理）：

1. `assetutil -n` 裁剪后的 car **还会留下同族资源的 PDF**（实测 `icon_todo` 留下 17 个），
   不能取第 1 个。脚本按 `SizeOnDisk` 对号（矢量资源的 SizeOnDisk 恒比 PDF 原文多 225 字节，
   用投票法自动推出这个开销，不写死魔数）。
2. 光按长度对号会**撞车**——`icon_todo` 的 16×16 和 22×22 两个 PDF 都是 3738 字节。
   所以再加一道 MediaBox 校验（期望尺寸从同一资源的位图 rendition 反推），撞车时用它消歧。

**输出命名对齐 `wecom_ui.py`**：未选中 `*_normal` 是 22pt 线稿、选中 `*_selected` 是 20pt 实心，
所以导出的 `nav_chat.png` 是 22×22、`nav_chat_selected.png` 是 20×20，与占位图同名可直接替换。
要覆盖占位图：`--out assets/icons --overwrite`（只影响 nav_* 同名文件）。

**选中态取色**：渲染器 `_load_nav_icon()` 的优先级是
① `nav_X_selected.png`（**蓝色实心**）→ ② `nav_X_selected_white.png`（无蓝色版时，就地把
alpha 保留、RGB 染成 `C_SELECTED_NAV_FG`）→ ③ 退回 `nav_X.png`。
当前企微的选中样式是「浅蓝底胶囊 + 蓝色图标」，所以走的是 ①。
白色版仍然保留，作为「实心蓝底 + 白图标」样式的染色源与兜底。

白色版的来源有三类：

| 来源 | 例子 | 产物 |
|---|---|---|
| `--white` 派生：把 `nav_X_selected.png` 的 alpha 保留、RGB 刷白 | 消息/文档/通讯录/日程/工作台/… | `nav_X_selected_white.png` |
| 客户端原生白色矢量（预设里显式列出的名额） | `main_meeting_16_white` | `nav_meeting_selected_white.png` |
| 无专用资源 → 用同字形漂白 | `icon_todo` | `nav_todo_selected_white.png` |

`recolor()` 是统一的染色原语（`make_white()` 是它染白色的特例）：会先看原图的不透明像素是否
**本来就是目标色**，是则跳过不写盘，所以不会冒出 `_white_white.png` 这类重复文件；名字已带
`_white` 的名额则**就地**刷白。整个流程幂等，可重复跑。

### `grp` 预设：会话分组筛选面板

宽栏左下「分组」区那 8 项，在 car 里是**同一组 16pt 矢量**：`icon_tab_<语义>_16`。
注意这是独立的一族，与主导航的 `icon_tab_<模块>_normal|selected|expand_*` 不是一回事。

| 面板项 | 资源名 | rendition |
|---|---|---|
| 未读 | `icon_tab_unread_16` | `icon_tab_unread_16.pdf` |
| @我 | `icon_tab_atme_16` | `icon_tab_atme_16.pdf` |
| 单聊 | `icon_tab_singleconv_16` | `icon_tab_singleconv_16.pdf` |
| 群聊 | `icon_tab_groupconv_16` | `icon_tab_groupconv_16.pdf` |
| 内部聊天 | `icon_tab_innerconv_16` | `icon_tab_innerconv_16.pdf` |
| 外部聊天 | `icon_tab_externalconv_16` | `icon_tab_externalconv_16.pdf` |
| 标记 | `icon_tab_star_16` | `icon_tab_star_16.pdf` |
| 我的企业 | `icon_corp_switch_expand_normal` | `company_fill_16.pdf` |

同族里还有 `icon_tab_tag_16`（标签）、`icon_tab_summarize_fill_16`（智能总结）备用。

**必须染色**：这些矢量是 Template（fill 为**纯黑**），真实颜色由客户端运行时染上去，
直接用就是黑图标。实测面板取值（`grp` 预设已内置，`--tint auto` 生效）：

| 用途 | 色值 | 说明 |
|---|---|---|
| 描边图标（7 项） | `#62728A` | 预设默认色 |
| 我的企业（实心块） | `#7B8A9D` | 该名额单独指定，比描边色浅 |
| 单聊 选中 | `#267EF0` | 即官方 `blue_btn` |

要换别的色：`--tint '#RRGGBB'` 强制覆盖全部，或 `--tint none` 输出原始黑矢量。

**位图资源的限制**：少数图标在 car 里只有 lzfse 压缩位图（没有明文 PDF），本脚本会跳过并列出
它可用的 rendition。已知的有 `icon_tab_document_*`（文档 tab）、`icon_tab_voipmt_*`（会议）、
`icon_tab_exmail_selected`（邮件选中）。预设里已给出矢量替代：

| 想要 | 位图版（跳过） | 实际使用的矢量替代 |
|---|---|---|
| 邮件（选中） | `icon_tab_exmail_selected`（20pt PNG） | `icon_mail_pressed` → `side_nav_mailbox_selected_24` |
| 文档 | `icon_tab_document_normal`（24pt PNG） | `icon_tab_mail_document_normal` → `wedoc_fill_22`（腾讯文档） |
| 会议 | `icon_tab_voipmt_normal` | `main_meeting_20` / `main_meeting_16` |
| 更多「⋯」 | — | `icon_more_22` → `more_22.pdf`（注意：`icon_expand_more` 是折叠箭头，不是更多） |

**注意**：图标是微信官方版权素材，仅限自用/内部（例如合成训练数据），不要对外分发。
`assets/_icons_backup_20261002/` 是替换前的备份（11 个 `nav_*.png` + 8 个 `grp_*.png`），
要回滚直接拷回 `assets/icons/`。矢量母版统一放在 `assets/icons_wecom/_pdf/`，
部署目录 `assets/icons/` 只留渲染器真正要用的 PNG。

## 希望你在真实截图上标出的区域（校准用）

请在 `refs/` 或 `wxwork_dataset` 真图上框出，便于以后替换占位图与校准尺寸：

1. **self_avatar** 完整方框（含圆角）
2. **nav_chat_icon** / **nav_contacts_icon** 窄栏与宽栏各一张（含文字的整块可点区域）
3. **search_bar**（不含右侧 + 按钮，或注明是否含）
4. **input_bar** 左侧图标簇外接矩形（不含「快速会议」）
5. **send_button** 「发送(S)」
6. **输入空白区**（由 input_bar 底边与 send_button 左边估计，不再单独出 class）
7. 一条完整会话行与一条联系人行（都是 **list_item**）的行高
8. 典型 **incoming_bubble** / **outgoing_bubble**（含圆角 padding）
9. **single_chat** / **group_chat**：会话列表里头像（单人头像 vs 多人拼贴）

窄栏参考：`refs/narrow_nav.jpg`；宽栏参考：`refs/wide_nav.jpg`。

## 高保真典型页（`--preset`）

对齐真实截图的几种固定布局，可单独出图或与随机混合：

| preset | 内容 |
|--------|------|
| `chat_narrow` | 窄图标导航 + 会话列表 + 气泡聊天 + input_bar/send；角标贴图标右上角 |
| `chat_wide` | 宽导航（图标+文字）；数字角标靠行尾，红点仍贴图标右上 |
| `contacts_profile` | 通讯录选中 + list_item 列表 + 右侧资料卡「发消息」(cls 11)，浅色 |
| `contacts_profile_dark` | 同上，右侧资料卡深色（发消息用 `#338CFF`） |
| `forward_dialog` | 转发「发送给」弹窗（只有弹窗）：约 50% 最近聊天模式、50% 搜索模式；别名 `forward_dialog_recent` / `forward_dialog_search` 强制子模式 |

```bash
# 各出一张预览
python3 synthesize.py --count 4 --out out_hifi --format png --seed 42 \
  --preset chat_narrow,chat_wide,contacts_profile,contacts_profile_dark

# 只刷窄栏聊天
python3 synthesize.py --count 20 --out out --preset chat_narrow --seed 1
```

随机模式（不传 `--preset`）约 40% 样本会走上述模板，保证训练集经常碰到高保真布局。
（`forward_dialog` 也在随机池里，默认生成会包含它。）

### `forward_dialog` 标注口径（按真实截图手标）

- 布局：左栏浅灰（约占 45–52% 宽），右栏白；弹窗宽 680–1100、高 520–640，行距 46–54（同图固定）。
  - 最近聊天：搜索框 + 「创建聊天 / 微信 / 更多」三按钮 + 「最近聊天」+ 4–8 行（个人 / 群 / 文件传输助手）；
    右栏「发送给」+ 名片预览 + 留言 + 灰色「发送」+「取消」。
  - 搜索：查询词 + ×；「联系人」1–4 行（命中字蓝色，@公司，第二行如「微信联系人」/公司名）、分隔线、
    「群聊」0–3 行（第二行「包含: 某某」）；勾选的会话列在右栏，「已选择N个聊天」，发送变蓝。
- `search_bar`(3)：左上灰色搜索胶囊。
- `list_item`(4)：左栏每一行；左边 = 头像左 −4（**不含勾选框**），右边 = 搜索框右沿，
  高 = 行距 − 9、以头像中线居中；同图所有行等宽等高。右栏已选会话也是 `list_item`
  （头像左 −8 → 右内边距 +4，同一框高）。
- 不标：分段标题（最近聊天 / 联系人 / 群聊）、三个按钮、分隔线、名片预览、留言框、
  发送 / 取消（这里**不出** `send_button`）、各种 ×、标题文字。底部被弹窗截断的行按 `min_visible_h` 裁剪。

```bash
python3 synthesize.py --count 12 --out out_fwd --preset forward_dialog --seed 7
```
角标约定：`None` 无角标；`0` / `'dot'` 纯红点；`1–99` 数字；`>99` 三点。角标画在图标/头像上，**不单独成类**。

配色已对齐官方色值表：`blue_btn #267EF0`（列表选中 / 发消息）、深色 `#338CFF`、
`red_notification #FF4650`、导航选中浅蓝底 `#C8DEF7` + 蓝图标（非实心蓝底白图标）。

## 场景多样性（脚本内随机）

空聊 / 仅入站 / 仅出站 / 混合；会话少/满；消息疏/密；
列表与消息区滚动遮挡；窄/宽导航；窗口短高/扁宽；
角标 0 / 1–9 / 10–99 / 99+；长名省略号；通讯录页。

## 参考资源（官方配色 / UI 库）

### 1. 企业微信应用深色模式色值表（配色）

- https://developer.work.weixin.qq.com/document/path/94600

官方给出的浅色/深色两套色值（含颜色名、色号、使用场景），用于校准 `wecom_ui.py` 顶部的
`C_*` 配色常量。常用几项对照：

| 颜色名 | 浅色 | 深色 | 用途 |
|--------|------|------|------|
| `blue` | `#3D8BF2` | `#4992F3` | 标准蓝 |
| `blue_btn` | `#267EF0` | `#338CFF` | 蓝色按钮 / icon / 文字链 |
| `blue_nav_bg` | `#3975C6` | `#000000` | 蓝导航栏背景 |
| `blue_bubble_bg` | `#C9E7FF` | `#093159` | 蓝色气泡背景 |
| `white_bubble_bg` | `#FFFFFF` | `#222324` | 气泡背景 |
| `gray_blue_94_bg` | `#EBEDF0` | `#000000` | 聊天页面背景 |
| `gray_blue_97_bg` | `#F5F6F7` | `#000000` | 灰色导航 / 搜索背景 |
| `green` / `orange` / `red` | `#26BF4C` / `#FA8F25` / `#FF6963` | `#2DC252` / `#FC942D` / `#FF736E` | 标准色 |
| `green_wechat` | `#15B628` | `#1BB52D` | 微信相关功能标准色 |
| `red_notification` | `#FF4650 90%` | `#FF5962 90%` | 通知、红点 |
| `black_a7` | `#000000 7%` | `#4D4D4D 35%` | 分割线 / 点击态叠加 |
| `gray_80` / `gray_60` | `#CCCCCC` / `#999999` | `#747678 50%` / `#C3C5C7 50%` | 不重要的信息（如列表时间） |

### 2. WeUI for Work（企业微信 UI 库：样式 / 组件）

- https://weui.io/work/
- 样式表直链：https://weui.io/work/style/weui.css

由微信官方设计团队基于 WeUI 为企业微信开发者设计的 UI 库。页面按组件给出真实样式
（色值 / 圆角 / 字号 / 间距），可作为合成图视觉的参考基准。

组件与章节：Button、List、Input、Toast、Dialog、Progress、Msg（成功/警告提示页）、
Article（大标题/节标题）、Panel、ActionSheet、Icons、SearchBar、Picker、Footer、
Gallery、Flex、Loadmore、Uploader、Preview、Grid、Badge、Slider；
另有 Popout / Mask / Navigation / Content —— WeUI 页面层级说明。

从 `weui.css` 里扒到的关键色值（这套是 weui-work 的值，与上面桌面版色值表**不是同一套**）：

| 选择器 | 色值 | 用途 |
|--------|------|------|
| `.weui-btn_primary` | `#2F7DCD` | 主按钮蓝 |
| `.weui-switch:checked`、`_radio/_checkbox .weui-check:checked` | `#4C84C4` | 选中态（单选 / 复选 / 开关） |
| `.weui-dialog__btn` / `.weui-form-preview__btn` / `.weui-vcode-btn` | `#467DB9` | 弹窗按钮蓝 |
| `.weui-cell_link` / 提示页文字链 | `#586C94` | 文字链 |
| `.weui-icon-success*` | `#09BB07` | 成功绿 |
| `.weui-btn_warn` / `.weui-toptips_warn` | `#E64340` | 警告红 |
| `.weui-icon-warn`、`.weui-icon-cancel`、`.weui-badge` | `#F43530` | icon 警告 / 红点 |
| `.weui-icon-waiting*` / `.weui-icon-info` | `#10AEFF` | 等待 / 信息蓝 |
| `.weui-icon-safe-warn` | `#FFBE00` | 安全警告黄 |

### 用哪套？

- 画**桌面端窗口**（本脚本场景）→ 以第 1 套（应用深色模式色值表）为准。
- 第 2 套（WeUI for Work）偏移动端 / 内嵌 H5 组件，主蓝是 `#2F7DCD`，与桌面端 `blue_btn #267EF0` 不同。

注意：合成图目前只做浅色主题（`C_SELECTED_NAV = #0082FF` 这类是照着截图取的近似值，
与上面两套官方蓝都不一致），深色模式那一列暂未使用。
