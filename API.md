# YOLO26 企业微信 UI 元素检测 — 接口说明

| 项 | 值 |
| --- | --- |
| 服务地址 | `http://192.168.1.22:8080` |
| 模型 | `weights/yolo26n_detect_wxwork.pt`（YOLO26n 微调，11 类） |
| 推理分辨率 | **1280**（与训练一致，不可下调） |
| 设备 | CPU only |
| 单张耗时 | 约 280–350 ms（2336×1536 截图） |
| 并发 | 请求串行排队（全局锁），非并行 |
| 认证 | 无。仅限内网使用，勿直接暴露公网 |

---

## 一、另一台机器怎么访问

### 前置条件

服务监听在 `0.0.0.0:8080`，即**所有网卡**，不是只绑本机回环 —— 这点已经验证过：
用局域网 IP 自测 `http://192.168.1.22:8080/health` 返回 200。

你只需要满足一条：**另一台机器和服务所在的 Mac 在同一个 `192.168.1.0/24` 网段**。

当前网络拓扑（实测）：

| 项 | 值 |
| --- | --- |
| 本机 IP | `192.168.1.22` |
| 子网掩码 | `255.255.255.0`（/24） |
| 网段 | `192.168.1.1` – `192.168.1.254` |
| 出口网卡 | `en0`（Wi-Fi） |
| macOS 防火墙 | **已关闭**，无需放行任何端口 |

### 直接试

在另一台机器上（同一 Wi-Fi / 同一路由器）：

```bash
curl http://192.168.1.22:8080/health
```

浏览器直接打开 <http://192.168.1.22:8080/> 会看到上传检测的演示页，这是最快的验证方式。

### 通了就完事，不通按这个表排查

| 现象 | 原因 | 怎么确认 / 怎么修 |
| --- | --- | --- |
| `Connection refused` | 服务没在跑 | 在服务机器上执行 `lsof -nP -iTCP:8080 -sTCP:LISTEN`，有输出才算在跑 |
| `Connection refused` | 服务只绑了 `127.0.0.1` | 看 lsof 输出是 `*:8080` 还是 `127.0.0.1:8080`。后者要用 `./serve.sh`（默认 `0.0.0.0`）重启 |
| `No route to host` / 超时 | 两台机器不在同一网段 | 各跑一次 `ifconfig \| grep "inet "`，看前三位是否都是 `192.168.1` |
| 手机热点连的 | 手机热点常做客户端隔离 | 换成同一个路由器下的 Wi-Fi |
| 公司/酒店网络 | AP 隔离或 VLAN 划分，同网段也互不可见 | 换网络，或走下面的穿透方案 |
| 能 ping 通但 HTTP 超时 | 极少见，代理干扰 | 检查客户端有没有设 `HTTP_PROXY`；`curl --noproxy '*' http://192.168.1.22:8080/health` |
| 服务莫名消失 | 服务是前台进程，终端关了或进程被杀就没了 | 用下面的「让它常驻」方式启动 |

### 让它常驻，别依赖终端

```bash
cd /Users/admin/Desktop/workspace/yolo26

# 后台常驻，日志写到 /tmp
nohup ./serve.sh --port 8080 > /tmp/yolo26-serve.log 2>&1 &

# 确认
sleep 20 && tail -20 /tmp/yolo26-serve.log
lsof -nP -iTCP:8080 -sTCP:LISTEN

# 停止
kill $(lsof -t -iTCP:8080 -sTCP:LISTEN)
```

模型加载 + 预热约 25 秒，**启动后要等一会儿才能响应请求**，别刚敲完就 curl。

关终端会带走 `nohup` 的进程的话，用 `disown`：`nohup ./serve.sh > /tmp/yolo26-serve.log 2>&1 & disown`

需要开机自启就写 launchd plist；要真正跨公网，见文末「暴露到公网」。

### IP 变了怎么办

`192.168.1.22` 是路由器 DHCP 分配的，重启路由或长时间离线后可能变。三个选择：

1. 在路由器后台给这台 Mac 的 MAC 绑定静态 IP（推荐）
2. Mac 系统设置里手动配静态 IP
3. 用 mDNS 主机名代替 IP：`http://admindeMacBook-Pro.local:8080`
   （主机名用 `scutil --get LocalHostName` 查；Mac 之间识别的协议，Windows 需装 Bonjour）

---

## 二、通用约定

- 字符编码：UTF-8，所有响应都是 JSON（除 `/predict/image` 和 `/`）
- 请求体上限：**32 MB**
- 推理参数可在 **query string** 或 **JSON body** 里传，query 优先级更高
- `/predict` 的响应永远是 HTTP 200（除非参数/图片非法），业务成败看 `success` 字段
- 图片格式支持：jpg / jpeg / png / bmp / webp / tif / tiff
- **类别一律以名称字符串返回，不会返回裸数字。** 检测结果里的标签字段是
  `detections[].class_name`（如 `"send_button"`），`class_counts` 的 key 同样是名称。
  `detections[].class_id` 只是附带上的数字 id，方便程序做判断用，**不要拿它当展示标签**

### 推理参数

| 参数 | 默认 | 范围 | 说明 |
| --- | --- | --- | --- |
| `conf` | `0.25` | 0–1 | 置信度阈值。漏检就调低，误检就调高 |
| `iou` | `0.7` | 0–1 | NMS IoU 阈值。同一元素被重复框出时调低 |
| `imgsz` | **`1280`** | 64–1920 | **必须保持 1280**，见「实践建议」 |
| `max_det` | `300` | 1–3000 | 单图最大检出数 |

越界值会被自动夹到合法区间，不会报错。

---

## 三、接口详情

### 1. `GET /health` — 健康检查

启动自检、探活用。**返回 `status: "ok"` 才说明模型加载完成。**

```bash
curl http://192.168.1.22:8080/health
```

```json
{
  "status": "ok",
  "model": "/Users/admin/Desktop/workspace/yolo26/weights/yolo26n_detect_wxwork.pt",
  "nc": 13,
  "classes": {"0": "self_avatar", "1": "nav_chat_icon", "...": "..."},
  "schema": "c13",
  "list_item_aliases": ["contact_item", "conversation_item", "list_item"],
  "device": "cpu",
  "torch": "2.13.0",
  "defaults": {"conf": 0.25, "iou": 0.7, "imgsz": 1280, "max_det": 300},
  "uptime_sec": 312.5,
  "host": "xxx.local"
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `status` | string | `ok` = 就绪；`loading` = 模型还没加载完 |
| `nc` | int | 类别数 |
| `classes` | object | id → 类别名（取自当前权重） |
| `schema` | string | `c13`（13 类新权重）/ `c14`（旧 14 类权重）/ `custom` |
| `list_item_aliases` | array | 会被 `logical_name` 统一成 `list_item` 的类别名 |
| `defaults` | object | 服务端默认推理参数 |

---

### 2. `GET /classes` — 类别表

```bash
curl http://192.168.1.22:8080/classes
```

```json
{
  "nc": 13,
  "classes": {
    "0": "self_avatar", "1": "nav_chat_icon", "2": "nav_contacts_icon",
    "3": "search_bar", "4": "list_item", "5": "send_button",
    "6": "incoming_bubble", "7": "outgoing_bubble", "8": "input_bar",
    "9": "single_chat", "10": "group_chat", "11": "contact_send_message",
    "12": "nav_groups_icon"
  },
  "schema": "c13",
  "list_item_aliases": ["contact_item", "conversation_item", "list_item"]
}
```

`classes` 永远是**当前加载的权重**内嵌的类别表：加载旧 14 类权重时这里就是 14 类、
`schema` 为 `"c14"`；13 类新权重为 `"c13"`；其他为 `"custom"`。
```

---

### 3. `POST /predict` — 检测（主力接口）

#### 三种传图方式

按优先级依次尝试，命中即用：

**方式 A：multipart 表单上传**（最常用）

字段名 `file` / `image` / `img` / `upload` 任选一个。

```bash
curl -X POST \
  -F "file=@screenshot.png" \
  "http://192.168.1.22:8080/predict?conf=0.3"
```

**方式 B：原始二进制 body**

```bash
curl -X POST \
  --data-binary @screenshot.png \
  -H "Content-Type: image/png" \
  "http://192.168.1.22:8080/predict"
```

**方式 C：JSON**

`image_base64` 支持带 `data:image/png;base64,` 前缀；也可以改用 `url` 让服务端去拉图。

```bash
# base64
curl -X POST -H "Content-Type: application/json" \
  -d '{"image_base64":"iVBORw0KG...","conf":0.3,"imgsz":1280}' \
  http://192.168.1.22:8080/predict

# 远程 URL
curl -X POST -H "Content-Type: application/json" \
  -d '{"url":"http://192.168.1.31:9000/shot.png"}' \
  http://192.168.1.22:8080/predict
```

> 方式 C 的 JSON 里如果同时写了 `conf`、query 里也写了 `conf`，**query 生效**。

#### 额外参数

| 参数 | 说明 |
| --- | --- |
| `annotated=1` | 在 JSON 里额外返回 `annotated_image`，带框图的 data URL |

```bash
curl -X POST -F "file=@shot.png" \
  "http://192.168.1.22:8080/predict?annotated=1"
```

#### 响应

```json
{
  "success": true,
  "image": {"width": 2336, "height": 1536},
  "params": {"conf": 0.25, "iou": 0.7, "imgsz": 1280, "max_det": 300},
  "count": 9,
  "class_counts": {
    "list_item": 4,
    "incoming_bubble": 1,
    "nav_chat_icon": 1,
    "nav_contacts_icon": 1,
    "search_bar": 1,
    "self_avatar": 1
  },
  "speed_ms": {"preprocess": 15.18, "inference": 348.97, "postprocess": 4.55},
  "detections": [
    {
      "class_id": 4,
      "class_name": "list_item",
      "logical_name": "list_item",
      "conf": 0.9637,
      "xyxy": [152.4, 236.1, 709.3, 410.2],
      "xywh": [430.85, 323.13, 556.9, 174.1],
      "center": [430.85, 323.13],
      "size": [556.9, 174.1],
      "area_ratio": 0.02707
    }
  ]
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `success` | bool | 是否成功 |
| `image.width` / `image.height` | int | **原图**像素尺寸，坐标都基于这个尺寸 |
| `params` | object | 本次实际生效的参数（已夹取过合法范围） |
| `count` | int | 检出目标总数 |
| `class_counts` | object | 类别名 → 数量 |
| `speed_ms` | object | `preprocess` / `inference` / `postprocess`，单位毫秒 |
| `detections` | array | 检测框列表，**按 `conf` 降序** |
| `detections[].class_id` | int | 类别 id（13 类权重 0–12，旧 14 类权重 0–13；附带信息，展示请用 `class_name`） |
| `detections[].class_name` | string | **类别名，即标签**，原样取自权重的 `model.names`，如 `"list_item"`（旧权重为 `"conversation_item"` / `"contact_item"`） |
| `detections[].logical_name` | string | 逻辑类别（**新增字段**）：`list_item` / `conversation_item` / `contact_item` 一律为 `"list_item"`，其余与 `class_name` 相同。调用方按它匹配列表行即可同时兼容新旧权重 |
| `detections[].conf` | float | 置信度，保留 4 位 |
| `detections[].xyxy` | [float×4] | 左上角 + 右下角，`[x1, y1, x2, y2]` |
| `detections[].xywh` | [float×4] | 中心点 + 宽高，`[cx, cy, w, h]` |
| `detections[].center` | [float×2] | 中心点 `[cx, cy]` —— **直接当点击坐标用** |
| `detections[].size` | [float×2] | 框宽高 `[w, h]` |
| `detections[].area_ratio` | float | 框面积占整图比例，可用于过滤超大/超小框 |

#### 错误响应

非 200 时 body 结构统一为 `{"success": false, "error": "中文说明"}`：

| HTTP | `error` 内容 | 触发条件 |
| --- | --- | --- |
| 400 | `JSON body 里需要 image_base64 或 url 字段` | JSON 请求但缺图片字段 |
| 400 | `无法解码图片，请确认是 jpg/png/bmp/webp 等常见格式` | body 不是有效图片 |
| 400 | `没有收到图片：请用 multipart(file 字段)、原始 body 或 JSON({image_base64}) 提交` | 完全没带图 |
| 404 | `接口不存在` | 路径写错（会附带可用路由列表） |
| 413 | `图片超过 32MB 上限` | 文件太大 |
| 500 | `推理失败: ...` | 模型侧异常 |

---

### 4. `POST /predict/image` — 检测并直接返回标注图

传图方式、参数与 `/predict` 完全一致，区别只在于响应是**画好框的 JPEG 二进制**。

```bash
curl -X POST -F "file=@screenshot.png" \
  "http://192.168.1.22:8080/predict/image?imgsz=1280" \
  -o result.jpg
```

| 项 | 值 |
| --- | --- |
| `Content-Type` | `image/jpeg` |
| 质量 | JPEG quality 85 |
| `X-Detections` 响应头 | 检出目标数量（省一次 JSON 解析） |

用 `Content-Type` 判断响应类型：

```python
import requests
r = requests.post("http://192.168.1.22:8080/predict/image",
                  files={"file": open("shot.png", "rb")})
if r.headers["Content-Type"].startswith("image/"):
    open("result.jpg", "wb").write(r.content)
    print("检出", r.headers["X-Detections"], "个")
else:
    print("失败:", r.json()["error"])
```

---

### 5. `GET /` — 演示页

浏览器打开 <http://192.168.1.22:8080/>，拖图进去即可看到框 + 类别统计 + 下载标注图。
自带 conf / iou / imgsz 滑块，适合肉眼验证和调参，不参与程序调用。

---

## 四、类别定义

| id | 名称 | 含义 |
| --- | --- | --- |
| 0 | `self_avatar` | 本人头像（导航区当前登录账号头像） |
| 1 | `nav_chat_icon` | 导航栏「消息」图标 |
| 2 | `nav_contacts_icon` | 导航栏「通讯录」图标 |
| 3 | `search_bar` | 搜索框 |
| 4 | `list_item` | 列表中的一行：会话列表行 / 通讯录联系人行 / 搜索结果行（是哪一种由调用方按当前页面判断） |
| 5 | `send_button` | 发送按钮（输入卡片右下「发送(S)」灰字） |
| 6 | `incoming_bubble` | 接收的消息气泡 |
| 7 | `outgoing_bubble` | 发送的消息气泡 |
| 8 | `input_bar` | 输入区上方工具条整行（表情/附件等，不含白色文字区） |
| 9 | `single_chat` | 分组面板里的单聊图标 |
| 10 | `group_chat` | 分组面板里的群聊图标 |
| 11 | `contact_send_message` | 联系人详情「发消息」 |
| 12 | `nav_groups_icon` | 导航栏「分组」图标 |

#### 13 类（c13）与旧 14 类（c14）

旧 14 类里 `contact_item`(4) 与 `conversation_item`(6) 外观几乎相同，模型经常混淆（contact_item 置信度 <0.4），
现合并为 `list_item`(4)。old14 → new13 映射：0–5 不变，6→4，7→6，8→7，9→8，10→9，11→10，12→11，13→12。
旧标签用 `tools/remap_14_to_13.py` 转换（默认 dry-run，`--apply` 写到新目录 `<src>_c13`，不改原目录）。

兼容策略：

- 服务端**不改写** `class_name` / `class_id` / `class_counts`，它们始终是权重里的真实标签，响应格式不变；
- 每个检测框新增 `logical_name`，把 `conversation_item` / `contact_item` / `list_item` 统一成 `list_item`；
- 所以旧 14 类权重和新 13 类权重可以直接互换，调用方用 `logical_name == "list_item"`（或自己做同样的别名判断，
  llm_rpa 里是 `is_list_item()`）匹配列表行，再按「当前在哪个页面」决定它是会话还是联系人。
- `/health`、`/classes` 里的 `schema` 字段告诉你当前加载的是 `c13` / `c14` / `custom`。

> 类别 id 与训练数据严格绑定，顺序不可调整。
>
> 「id → 名称」的映射在 `server.py` 里以 `CLASS_NAMES_CANONICAL`（13 类）常量硬编码了一份，
> 作为权威兜底：接口对外只吐名称，即使权重被重新导出、丢掉内嵌的类别表，
> 也不会退化成返回 `7` 这种数字。启动时会拿权重的内嵌类别表和这份常量对一遍，
> 不一致会打印警告（并列出差异），但仍以权重内嵌的为准 —— 那是训练时的真实标签。
> 旧 14 类权重会被识别出来（`CLASS_NAMES_LEGACY_C14`），只打印提示、不算异常。

---

## 五、实践建议

### 1. `imgsz` 必须是 1280，别改成 640

这个权重是用 `imgsz=1280` 训练的（见 `runs/train/wxwork_ui/args.yaml`）。
**推理分辨率与训练尺度不一致，等于换了个标准考模型。** 企业微信桌面版截图通常
2000×1500 以上，导航图标、发送按钮这类目标在整图里只有十几到几十像素，
`imgsz=640` 相当于先把图缩掉 3 倍多，小图标直接没了。

同一张 2336×1536 截图实测：

| imgsz | 检出目标数 | 推理耗时 |
| --- | --- | --- |
| 640 | 1 | ~105 ms |
| 960 | 6 | ~175 ms |
| **1280** | **9** | **~280 ms** |

### 2. 交给 RPA 用时直接读 `center`

```python
det = next(d for d in r["detections"] if d["class_name"] == "send_button")
x, y = det["center"]        # 直接就是屏幕像素坐标
```

前提是截图分辨率与屏幕分辨率一致（没有缩放）。若截图做过缩放，需要按
`原图宽 / 截图宽` 等比还原。

### 3. 用 `area_ratio` 过滤脏框

`area_ratio` 过大（如 > 0.5，可能是整窗口被误判）或过小（< 0.0001，噪声）的框建议丢掉。

### 4. 别指望并发

推理有全局锁，请求是**排队**执行的。单张约 300 ms，串行 10 张就是 3 秒。
批量场景请串行发送，别开线程池猛打 —— 只会增加排队延迟，不会更快。
真要提吞吐，把 `imgsz` 之外的路子走：换设备、导出 ONNX/OpenVINO 加速。

### 5. 目前没有鉴权

任何能访问到 `192.168.1.22:8080` 的人都能调。内网自用没问题，
**对外暴露前必须加认证**。

---

## 六、客户端示例

### Python

```python
import requests

BASE = "http://192.168.1.22:8080"


def detect(image_path, conf=0.25, imgsz=1280):
    with open(image_path, "rb") as f:
        r = requests.post(
            f"{BASE}/predict",
            files={"file": f},
            params={"conf": conf, "imgsz": imgsz},
            timeout=60,
        )
    r.raise_for_status()
    data = r.json()
    if not data["success"]:
        raise RuntimeError(data["error"])
    return data


res = detect("shot.png")
print(f"检出 {res['count']} 个目标，耗时 {res['speed_ms']['inference']:.0f}ms")
for d in res["detections"]:
    print(f"  {d['class_name']:<18} {d['conf']:.2f}  center={d['center']}")
```

### JavaScript / 浏览器

```javascript
const BASE = "http://192.168.1.22:8080";

async function detect(file, conf = 0.25) {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(`${BASE}/predict?conf=${conf}&imgsz=1280`, {
    method: "POST",
    body: fd,
  });
  const data = await res.json();
  if (!data.success) throw new Error(data.error);
  return data;
}
```

> 注意：浏览器里跑这段，页面来源和服务不同源，会触发 CORS。`/predict` 是纯接口、
> 没设 `Access-Control-Allow-Origin`，跨域会被拦。**服务端调用不受此限制**；
> 浏览器直连需要在 `server.py` 里加 CORS 头，或走同源反向代理。

### 拿到标注图

```python
r = requests.post("http://192.168.1.22:8080/predict/image",
                  files={"file": open("shot.png", "rb")}, timeout=60)
open("annotated.jpg", "wb").write(r.content)
```

---

## 七、常见问题

**Q：返回 `count: 0`，是服务坏了吗？**
多半不是。先确认 `imgsz` 没被传成 640。再看 `conf`，UI 元素置信度普遍不高（实测高的
0.96、低的 0.3 左右），降到 0.1 试试。都不行就是这张图确实没有训练覆盖的元素。

**Q：同一个元素被框了好几次？**
NMS 没合并干净，把 `iou` 从 0.7 降到 0.5 或 0.4。

**Q：第一次请求特别慢？**
服务启动时已经预热过了。但如果你是刚 `kill` 完重启，模型加载 + 预热要约 25 秒，
这期间请求会失败或超时。`/health` 返回 `ok` 才代表可以打。

**Q：能识别哪些界面？**
只在这个项目的企业微信桌面版截图上微调过，训练集仅 22 张。
换 App、换语言界面、换深色主题，效果都可能明显下降。通用 UI 元素检测需要重新训练。

**Q：耗时 300ms 太慢，能优化吗？**
CPU 推理的物理限制。可行方向：导出 ONNX + OpenVINO（Intel CPU 上有明显加速），
或换 CUDA/Apple Silicon 机器。注意 `imgsz` 不能降，这条路堵死了。

**Q：服务重启后 IP 变了？**
见「IP 变了怎么办」，给路由器绑定静态 IP 是根治办法。
