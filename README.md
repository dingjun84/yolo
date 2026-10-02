# yolo26 — Ultralytics YOLO26 CPU 微调环境

Intel Mac (x86_64) 上的 CPU 微调环境，已在 2026-09-22 验证可用。

## 关键前提：这台机器是 Intel Mac

`i7-9750H / macOS 26.6.2 / x86_64`。这带来一个必须知道的硬约束：

| 渠道 | macOS x86_64 支持情况 |
| --- | --- |
| PyPI `pip install torch` | **止于 torch 2.2.2**，2.3.0 起官方不再构建 Intel Mac wheel |
| conda-forge `osx-64` | **持续维护**，已到 pytorch 2.13.0 / torchvision 0.28.0 |

所以本环境**PyTorch 必须走 conda-forge**，不要用 pip 装 torch —— 否则会被降级到 2024 年 3 月的 2.2.2，与 YOLO26 新算子存在兼容风险。

## 组件版本

| 组件 | 版本 | 来源 |
| --- | --- | --- |
| conda | 25.7.0 | Miniconda3 (x86_64) → `/Users/admin/miniconda3` |
| python | 3.11.16 | conda-forge |
| torch | 2.13.0 (CPU) | conda-forge `osx-64` |
| torchvision | 0.28.0 (CPU) | conda-forge `osx-64` |
| ultralytics | 8.4.156 | conda-forge (noarch) |
| numpy / opencv | 2.4.6 / 5.0.0 | conda-forge |

环境位置：`.conda/envs/yolo26`（项目内 prefix 环境，占用约 2.2G，已在 `.gitignore` 中排除）

## 使用

### 激活环境

项目根目录有 `init.sh`，**用 `source` 运行**，不要用 `./`：

```bash
source ./init.sh     # ✅ 在当前 shell 生效
./init.sh            # ❌ 在子进程里跑，激活影响不到你的终端（会有警告提示）
```

它会自动补上 conda hook、激活环境、切到项目目录，并打印自检信息。幂等，重复 source 没问题。

也可以手动激活。注意这是 **prefix 环境，没有短名字**，`conda activate yolo26` 会报
`EnvironmentNameNotFound`，必须写完整路径：

```bash
conda activate /Users/admin/Desktop/workspace/yolo26/.conda/envs/yolo26
```

嫌长就在 `~/.zshrc` 里加个别名：

```bash
alias yolo26='source /Users/admin/Desktop/workspace/yolo26/init.sh'
```

新终端里如果提示 `conda: command not found`，**重开一次终端**即可（`conda init` 已写入 `~/.zshrc`，
只对之后启动的 shell 生效）；不想重开就临时执行：

```bash
source ~/miniconda3/etc/profile.d/conda.sh
```

注意已设置 `auto_activate_base: false`，新终端**不会**自动激活 base，避免污染你原有的 python3.11 环境。

### 不激活就跑脚本的两种方式

```bash
# 方式 A：conda run（一次性，跑完即退，适合脚本/CI）
conda run -p /Users/admin/Desktop/workspace/yolo26/.conda/envs/yolo26 python your_script.py

# 方式 B：直接调环境内的解释器（IDE 里配置 interpreter 就用这条路径）
/Users/admin/Desktop/workspace/yolo26/.conda/envs/yolo26/bin/python your_script.py
```

方式 B 的路径同样适用于 IDE 的 Python Interpreter 设置项。

### 推理测试脚本 `infer.py`

把图片路径当参数传进去就行，支持单张 / 多张 / 整个目录（递归）/ http(s) URL：

```bash
python infer.py bus.jpg
python infer.py img1.jpg img2.png --conf 0.4
python infer.py ./samples/                 # 整目录递归
python infer.py ./samples/ --json          # 额外输出 JSON 报告
python infer.py bus.jpg --model yolo26s.pt --imgsz 416
python infer.py bus.jpg --no-save          # 只看统计不落图
```

常用参数：

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--model` | 项目内 `yolo26n.pt` | 也可传 `yolo26s.pt` 这样的模型名（自动下载） |
| `--imgsz` | 640 | CPU 上想快就降到 416 |
| `--conf` | 0.25 | 漏检多就调低 |
| `--iou` | 0.7 | NMS 阈值 |
| `--name` | `predict` | 输出到 `runs/<name>`，已存在会自动递增避免覆盖 |
| `--no-save` | 关 | 不保存标注图 |
| `--json` | 关 | 输出 `report.json`（含每张图的类别、置信度、耗时） |

输出示例：

```
ultralytics 8.4.156 | torch 2.13.0 | device cpu
共 4 个输入 | imgsz=640 conf=0.25 iou=0.7
------------------------------------------------------------------------
[1/4] 000000000036.jpg
      person ×1 (最高 0.86)
      umbrella ×1 (最高 0.83)
      耗时 推理 135.8ms (预处理 5.5 / 后处理 1.5)
------------------------------------------------------------------------
合计 13 个目标，覆盖 6 个类别
类别分布: person×6、horse×2、elephant×2、umbrella×1、dog×1、backpack×1
平均单张: 推理 135.8ms (预处理 5.5 / 后处理 1.5)
结果目录: /Users/admin/Desktop/workspace/yolo26/runs/predict
```

路径不存在或目录里没有图片时退出码为 2 并给出明确提示，便于脚本串联。

### 检测推理服务 `server.py`

把微调好的权重挂成 HTTP 服务，默认监听 `0.0.0.0:8080`（同网络下的设备都能访问）。

> 完整的字段说明、错误码、客户端示例、跨机访问排查表 → **[API.md](API.md)**

```bash
./serve.sh                    # 0.0.0.0:8080
./serve.sh --port 9000        # 换端口
./serve.sh --host 127.0.0.1   # 只允许本机访问
```

端口、权重、置信度等都可以调，完整参数见 `./serve.sh --help`。

| 接口 | 方法 | 用途 |
| --- | --- | --- |
| `/` | GET | 演示页：拖图片进去就能看标注结果 |
| `/health` | GET | 健康检查，返回模型路径、类别表、uptime |
| `/classes` | GET | 11 个类别的 id → 名称映射 |
| `/predict` | POST | 传图 → JSON 检测结果 |
| `/predict/image` | POST | 传图 → 标注好的 JPEG |

`/predict` 支持三种传图方式，按优先级：

```bash
# 1. multipart 表单（字段名 file / image / img 都行）
curl -X POST -F "file=@shot.png" "http://127.0.0.1:8080/predict?conf=0.3"

# 2. 原始二进制
curl -X POST --data-binary @shot.png -H "Content-Type: image/png" \
     "http://127.0.0.1:8080/predict"

# 3. JSON（base64 或 URL）
curl -X POST -H "Content-Type: application/json" \
     -d '{"image_base64":"...","conf":0.3}' http://127.0.0.1:8080/predict
curl -X POST -H "Content-Type: application/json" \
     -d '{"url":"https://example.com/shot.png"}' http://127.0.0.1:8080/predict
```

可用查询参数：`conf`（默认 0.25）、`iou`（0.7）、`imgsz`（1280）、`max_det`（300），
另外 `annotated=1` 会让 `/predict` 顺带把标注图以 base64 塞进 JSON。

返回结构：

```json
{
  "success": true,
  "image": {"width": 2336, "height": 1536},
  "params": {"conf": 0.25, "iou": 0.7, "imgsz": 1280, "max_det": 300},
  "count": 9,
  "class_counts": {"conversation_item": 4, "search_bar": 1, "self_avatar": 1},
  "speed_ms": {"preprocess": 15.18, "inference": 348.97, "postprocess": 4.55},
  "detections": [
    {"class_id": 7, "class_name": "conversation_item", "conf": 0.71,
     "xyxy": [x1, y1, x2, y2], "xywh": [cx, cy, w, h],
     "center": [cx, cy], "size": [w, h], "area_ratio": 0.042}
  ]
}
```

`detections` 按置信度降序，`xyxy` 是原图像素坐标，可直接画框或用 `center` 做点击坐标。

#### imgsz 必须是 1280 —— 这是训练分辨率，不是性能旋钮

本权重训自 `data_wxwork.yaml`，训练命令就用的 `imgsz=1280`
（见 `runs/train/wxwork_ui/args.yaml`）。**推理分辨率与训练不一致等于换了个尺度考模型**，
不要照搬 COCO 的 640。

企业微信桌面版截图一般 2000×1500 以上，导航图标、发送按钮这类目标在整图里只有十几到几十像素，
`imgsz=640` 相当于先把图缩掉 3 倍多，小图标直接缩没了。同一张 2336×1536 截图实测：

| imgsz | 检出目标数 | 单张推理 |
| --- | --- | --- |
| 640 | 1 | ~105 ms |
| 960 | 6 | ~175 ms |
| **1280（训练分辨率）** | **9** | **~280 ms** |

所以默认走 1280，别为了省那 200ms 往下调。另外实测 `torch.set_num_threads` 在 1/4/6 之间
对耗时几乎无影响（瓶颈在单核卷积而非线程调度），调线程数换不来速度，别在这上面浪费时间。

#### 并发与部署

内置 Flask 开发服务器开了 `threaded=True`，够本地和局域网用。推理本身用全局锁串行化，
因为 ultralytics 的 `predict` 不是可重入的 —— 并发请求会排队而不是抢崩模型。

要长期对外跑，建议换 WSGI server 并加反向代理：

```bash
pip install waitress
waitress-serve --host 0.0.0.0 --port 8080 --call server:make_app
```

`make_app()` 是现成的 WSGI 工厂，配置走环境变量：
`YOLO26_MODEL` / `YOLO26_IMGSZ` / `YOLO26_CONF` / `YOLO26_IOU` / `YOLO26_MAX_DET`。

**外网访问**：`0.0.0.0` 只解决「同一网络可达」。要从公网访问还需要路由器端口映射，
或者用 `cloudflared tunnel --url http://localhost:8080` 这类内网穿透；直接把 8080 暴到公网
前记得先在 `server.py` 里加鉴权。

### 微调

```bash
# 从 YOLO26n 预训练权重微调（CPU 建议 batch 放小）
yolo train model=yolo26n.pt data=your_data.yaml epochs=100 imgsz=640 batch=4 device=cpu
```

### 推理 / 验证 / 导出

```bash
yolo predict model=yolo26n.pt source=image.jpg device=cpu
yolo val     model=runs/train/smoke/weights/best.pt data=coco8.yaml device=cpu
yolo export  model=yolo26n.pt format=onnx imgsz=640   # Intel Mac 可导出 ONNX / OpenVINO
```

## 目录约定

已通过 `yolo settings` 把输出重定向到项目内，训练产物不会散落到 home 目录：

| 目录 | 用途 |
| --- | --- |
| `datasets/` | 数据集（已有自带的 coco8 冒烟集） |
| `weights/` | 预训练权重 |
| `runs/` | 训练 / 验证 / 推理输出 |

数据配置写在 `data.yaml`，参考 `datasets/coco8/coco8.yaml` 的格式。

## 已验证的冒烟结果

- **推理**：`yolo26n.pt` 对 `bus.jpg` 输出 4 persons + 1 bus，CPU 单图推理 181.7ms
- **微调**：`yolo26n.pt` + coco8（4 图）+ 3 epoch + batch=4 + imgsz=640
  → 权重正常落盘 `runs/train/smoke/weights/best.pt`，val mAP50 = 0.943 / mAP50-95 = 0.67

## 性能参考

CPU 微调很慢，`i7-9750H` 上 640 分辨率单图推理约 180–190ms（约 5 FPS）。
真实数据集微调建议：

- `imgsz` 降到 416 或 320 起步，先跑通再放大
- `batch` 视内存给 4–8，配合 `patience` 早停
- 想验证链路就先用 `epochs=3` + 小数据集，别一上来就 full run

## 镜像与配置说明

- `~/.condarc`：conda-forge 走清华 TUNA 镜像（实测比官方快约 4 倍），通道优先级设为 `strict`
- Anaconda `defaults` 通道的 URL 也已指向 TUNA，用于绕过 Anaconda ToS 的非交互式拦截
- `~/Library/Application Support/Ultralytics/settings.json`：datasets / weights / runs 路径指向本项目

如果换机器或想改用官方源，删掉 `~/.condarc` 里对应的镜像地址即可。

## 常见问题

### `./init.sh` 报 `CondaError: Run 'conda init' before 'conda activate'`

**这是子进程不继承 shell 函数导致的，不是 hook 没装。**

`conda activate` 依赖的是 conda 注入 shell 的**函数**。`./init.sh` 会 fork 一个子进程：
子进程**继承 PATH**（所以能找到 `~/miniconda3/condabin/conda` 这个**二进制**），
但**不继承函数**——shell 函数无法传给子进程。于是 `conda` 退化成二进制调用，直接抛这个错。

判断方法（在交互式终端里敲）：

```bash
type conda
# "conda is a shell function from ~/.zshrc"  → 你的终端本身是好的
```

那就说明问题只出在 `./` 上。**改成 `source ./init.sh` 即可。**

另外一层原因：就算 `./init.sh` 跑通了，它在子进程里激活，**退出后你的终端环境不变**。
所以「用脚本激活环境」这件事，本质上必须用 `source`。

### 其它激活相关报错

`conda activate` **依赖 conda 注入的 shell 函数**，不是可执行文件。当 `conda` 命令解析到二进制
（`~/miniconda3/condabin/conda`）而不是 shell 函数时，就会报这个错。典型场景：

- 终端窗口是**在 `conda init` 之前**打开的（hook 只对之后启动的 shell 生效）
- 在**非 zsh** 的 shell 里（本机的 hook 只写进了 `~/.zshrc`）
- 在 IDE 的 task / 脚本里用了非交互 shell

自检（看 `conda` 到底是什么）：

```bash
type conda
# 输出 "conda is a shell function"                        → hook 已加载，正常
# 输出 "conda is /Users/admin/miniconda3/condabin/conda"  → hook 没加载，就是这个问题
```

**立刻修复（任何 shell 都有效）：**

```bash
source ~/miniconda3/etc/profile.d/conda.sh
conda activate /Users/admin/Desktop/workspace/yolo26/.conda/envs/yolo26
```

**根治**：关掉当前终端窗口重开一次。

**更省事的做法**：如果目标只是跑脚本，根本不需要 activate，直接调环境内的解释器即可：

```bash
/Users/admin/Desktop/workspace/yolo26/.conda/envs/yolo26/bin/python infer.py bus.jpg
```

### 新终端里 `conda: command not found`

`conda init` 只对之后启动的 shell 生效，重开终端即可；不想重开就用上面的 `source` 一行。

### 怎么确认自己在用哪个环境

```bash
which python        # 应指向 .conda/envs/yolo26/bin/python
echo $CONDA_PREFIX
```

如果 `which python` 指向 `/usr/local/bin/python3.11`，说明环境没激活，`import torch` 会
`ModuleNotFoundError` —— 这不是环境装坏了，是跑错解释器了。
