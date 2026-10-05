#!/usr/bin/env python3
"""YOLO26 企业微信 UI 元素检测推理服务

加载 weights/yolo26n_detect_wxwork.pt，对外提供 HTTP 推理接口。
默认监听 0.0.0.0:8080，局域网内任何设备都能访问。

接口:
    GET  /                 浏览器可用的上传/检测演示页
    GET  /health           健康检查（含模型路径、类别、设备）
    GET  /classes          类别列表
    POST /predict          上传图片 -> JSON 检测结果
    POST /predict/image    上传图片 -> 返回标注后的 JPEG
    POST /ocr              上传图片 -> JSON 数组，字段与本机 macosocr/winocr 相同

/predict 支持三种传图方式（按优先级）:
    1. multipart/form-data  字段名 file / image / img（任选）
    2. 原始二进制 body        请求头 Content-Type: image/*
    3. JSON                  {"image_base64": "..."} 或 {"url": "https://..."}

可选查询参数（也支持 JSON body 同名字段）:
    conf=0.25   iou=0.7   imgsz=1280   max_det=300
    annotated=1              # 让 /predict 顺带返回标注图的 base64

用法:
    python server.py                        # 0.0.0.0:8080
    python server.py --port 8080 --conf 0.3
    python server.py --host 127.0.0.1       # 只允许本机访问

关于 imgsz:
    这个权重是 data_wxwork.yaml 上用 imgsz=1280 训出来的（runs/train/wxwork_ui/args.yaml）。
    推理分辨率必须和训练对齐，降到 640 等于让模型去认一张它从没见过的尺度：
    企业微信桌面版截图 2336x1536，导航图标、发送按钮在整图里只有十几到几十像素，
    640 相当于先缩掉 3 倍多，小目标直接消失 —— 同一张截图实测 640 只检出 1 个目标，
    1280 检出 9 个。所以默认就是 1280，不要为了省时间往下调。

/ocr 的成功响应是 JSON 数组，不是包在对象里：
    [{"text":"张三","x":12,"y":40,"w":96,"h":24,"confidence":0.98}]
坐标是原图像素、左上角为原点。引擎是 RapidOCR（ONNX，PP-OCRv4），
第一次请求才加载。默认先放大 2 倍再识别，坐标换算回原图。
查询参数：upscale=2（1–8），text_score=0.3（低于此分的行不返回）。
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import platform
import socket
import threading
import time
import urllib.request
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import torch
from flask import Flask, Response, jsonify, request
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parent

# 应用启动时间，用于 /health 里的 uptime
START_TS = time.time()
# ultralytics 的推理不是可重入的，多线程下必须串行化
INFER_LOCK = threading.Lock()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024  # 单请求 32MB 上限

# 由 main() 在启动时填充
MODEL: YOLO | None = None
MODEL_PATH: str = ""
CLASS_NAMES: dict[int, str] = {}

# 权威类别表：13 类 c13（conversation_item 与 contact_item 合并为 list_item）。
# 接口对外一律返回名称、不返回裸数字 id，这张表保证「数字 -> 名称」这一步永远成立 ——
# 即使权重被重新导出/裁剪掉内嵌 names，也不会退化成返回 "7" 这种数字。
# 实际使用的类别表以权重内嵌的 model.names 为准（见 load_model），所以旧 14 类权重照常可用。
#
# ⚠️ 顺序不可调整：id 是训练时写进标签文件的类别号，改顺序会让所有输出错位。
CLASS_NAMES_CANONICAL: dict[int, str] = {
    0: "self_avatar",              # 本人头像（导航区当前登录账号头像）
    1: "nav_chat_icon",            # 导航栏「消息」图标
    2: "nav_contacts_icon",        # 导航栏「通讯录」图标
    3: "search_bar",               # 搜索框
    4: "list_item",                # 列表中的一行：会话 / 联系人 / 搜索结果（由调用方按页面区分）
    5: "send_button",              # 发送按钮
    6: "incoming_bubble",          # 接收的消息气泡
    7: "outgoing_bubble",          # 发送的消息气泡
    8: "input_bar",                # 工具条整行（表情/附件等，在白色输入区上方）
    9: "single_chat",              # 分组面板里的单聊图标
    10: "group_chat",              # 分组面板里的群聊图标
    11: "contact_send_message",    # 联系人详情「发消息」
    12: "nav_groups_icon",         # 导航栏「分组」图标
}

# 旧 14 类（c14）权重的类别表。只用来识别「这是旧权重」，不参与推理。
CLASS_NAMES_LEGACY_C14: dict[int, str] = {
    0: "self_avatar", 1: "nav_chat_icon", 2: "nav_contacts_icon", 3: "search_bar",
    4: "contact_item", 5: "send_button", 6: "conversation_item", 7: "incoming_bubble",
    8: "outgoing_bubble", 9: "input_bar", 10: "single_chat", 11: "group_chat",
    12: "contact_send_message", 13: "nav_groups_icon",
}

# 列表行的逻辑类别。旧权重输出 conversation_item / contact_item，新权重输出 list_item；
# 每个检测框都带 logical_name 字段，三者统一为 "list_item"，class_name 保持权重原样不改。
LIST_ITEM = "list_item"
LIST_ITEM_ALIASES = frozenset({"list_item", "conversation_item", "contact_item"})


def logical_name(class_name: str) -> str:
    """class_name -> 逻辑类别：列表行三种名字统一成 list_item，其余原样返回。"""
    return LIST_ITEM if class_name in LIST_ITEM_ALIASES else class_name


def schema_of(names: dict[int, str]) -> str:
    if names == CLASS_NAMES_CANONICAL:
        return "c13"
    if names == CLASS_NAMES_LEGACY_C14:
        return "c14"
    return "custom"


# imgsz=1280 必须与训练分辨率一致（runs/train/wxwork_ui/args.yaml: imgsz=1280），
# 不是可调的性能旋钮 —— 降到 640 会大面积漏检，详见文件头部说明
DEFAULTS: dict = {"conf": 0.25, "iou": 0.7, "imgsz": 1280, "max_det": 300}


# --------------------------------------------------------------------------
# 图片解码
# --------------------------------------------------------------------------
def decode_image(data: bytes) -> np.ndarray:
    """bytes -> BGR ndarray，失败抛 ValueError。"""
    buf = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法解码图片，请确认是 jpg/png/bmp/webp 等常见格式")
    return img


def load_from_request() -> np.ndarray:
    """从请求里取出图片，三种传图方式依次尝试。"""
    # 1. multipart 表单
    for field in ("file", "image", "img", "upload"):
        if field in request.files:
            f = request.files[field]
            if f and f.filename:
                return decode_image(f.read())

    ctype = (request.content_type or "").lower()

    # 2. JSON（base64 或 url）
    if ctype.startswith("application/json"):
        payload = request.get_json(silent=True) or {}
        b64 = payload.get("image_base64") or payload.get("base64") or payload.get("image")
        if isinstance(b64, str) and b64:
            if "," in b64[:64] and b64.lstrip().startswith("data:"):
                b64 = b64.split(",", 1)[1]  # 去掉 data:image/png;base64, 前缀
            try:
                return decode_image(base64.b64decode(b64, validate=False))
            except Exception as e:
                raise ValueError(f"image_base64 解码失败: {e}") from e
        url = payload.get("url")
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            return fetch_url(url)
        raise ValueError("JSON body 里需要 image_base64 或 url 字段")

    # 3. 原始二进制
    raw = request.get_data(cache=False, as_text=False)
    if raw:
        return decode_image(raw)

    raise ValueError("没有收到图片：请用 multipart(file 字段)、原始 body 或 JSON({image_base64}) 提交")


def fetch_url(url: str, timeout: int = 10) -> np.ndarray:
    req = urllib.request.Request(url, headers={"User-Agent": "yolo26-infer/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    return decode_image(data)


# --------------------------------------------------------------------------
# 推理
# --------------------------------------------------------------------------
def parse_params() -> dict:
    """合并 query string 和 JSON body 里的推理参数。"""
    src: dict = {}
    if request.is_json:
        body = request.get_json(silent=True) or {}
        for k in ("conf", "iou", "imgsz", "max_det"):
            if k in body:
                src[k] = body[k]
    for k in ("conf", "iou", "imgsz", "max_det"):
        if k in request.args:
            src[k] = request.args[k]

    conf = float(src.get("conf", DEFAULTS["conf"]))
    iou = float(src.get("iou", DEFAULTS["iou"]))
    imgsz = int(src.get("imgsz", DEFAULTS["imgsz"]))
    max_det = int(src.get("max_det", DEFAULTS["max_det"]))

    # 夹到合理区间，避免外部传入离谱值把服务拖垮
    conf = min(max(conf, 0.0), 1.0)
    iou = min(max(iou, 0.0), 1.0)
    imgsz = min(max(imgsz, 64), 1920)
    max_det = min(max(max_det, 1), 3000)
    return {"conf": conf, "iou": iou, "imgsz": imgsz, "max_det": max_det}


def run_inference(img: np.ndarray, params: dict):
    """执行一次推理，返回 ultralytics 的 Results 对象。"""
    if MODEL is None:
        raise RuntimeError("模型尚未加载完成")
    with INFER_LOCK:
        results = MODEL.predict(
            source=img,
            conf=params["conf"],
            iou=params["iou"],
            imgsz=params["imgsz"],
            max_det=params["max_det"],
            device="cpu",
            verbose=False,
        )
    return results[0]


def result_to_dict(r, params: dict) -> dict:
    """把 Results 转成纯 Python 结构。"""
    h, w = r.orig_shape if hasattr(r, "orig_shape") else (None, None)
    boxes = r.boxes
    detections: list[dict] = []
    if boxes is not None and len(boxes):
        xyxy = boxes.xyxy.tolist()
        xywh = boxes.xywh.tolist()
        confs = boxes.conf.tolist()
        clss = [int(c) for c in boxes.cls.tolist()]
        for i, cid in enumerate(clss):
            x1, y1, x2, y2 = (round(v, 2) for v in xyxy[i])
            cx, cy, bw, bh = (round(v, 2) for v in xywh[i])
            name = CLASS_NAMES.get(cid, str(cid))
            detections.append({
                "class_id": cid,
                "class_name": name,
                "logical_name": logical_name(name),
                "conf": round(float(confs[i]), 4),
                "xyxy": [x1, y1, x2, y2],
                "xywh": [cx, cy, bw, bh],
                "center": [cx, cy],
                "size": [bw, bh],
                "area_ratio": round((bw * bh) / float(w * h), 5) if w and h else None,
            })

    detections.sort(key=lambda d: -d["conf"])
    counts = Counter(d["class_name"] for d in detections)
    speed = {k: round(float(v), 2) for k, v in (r.speed or {}).items()}

    return {
        "success": True,
        "image": {"width": w, "height": h},
        "params": params,
        "count": len(detections),
        "class_counts": dict(counts),
        "speed_ms": speed,
        "detections": detections,
    }


def encode_jpeg(img: np.ndarray, quality: int = 85) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError("JPEG 编码失败")
    return buf.tobytes()



# --------------------------------------------------------------------------
# OCR（与 llm_rpa 的 macosocr / winocr 同一份 JSON 契约）
# --------------------------------------------------------------------------
OCR_ENGINE = None
OCR_LOCK = threading.Lock()


def _is_cjk(ch: str) -> bool:
    v = ord(ch)
    return (
        0x3000 <= v <= 0x303F
        or 0x3400 <= v <= 0x4DBF
        or 0x4E00 <= v <= 0x9FFF
        or 0xF900 <= v <= 0xFAFF
        or 0xFF00 <= v <= 0xFFEF
    )


def collapse_cjk_spaces(text: str) -> str:
    """去掉两侧都是中日韩字符的空格，拉丁文之间的空格保留。与 winocr 相同。"""
    chars = list(text)
    out: list[str] = []
    i = 0
    while i < len(chars):
        if chars[i] != " ":
            out.append(chars[i])
            i += 1
            continue
        start = i
        while i < len(chars) and chars[i] == " ":
            i += 1
        prev = chars[start - 1] if start > 0 else ""
        nxt = chars[i] if i < len(chars) else ""
        if not (prev and nxt and _is_cjk(prev) and _is_cjk(nxt)):
            out.extend([" "] * (i - start))
    return "".join(out)


def quad_to_xywh(box) -> tuple[int, int, int, int]:
    xs = [float(p[0]) for p in box]
    ys = [float(p[1]) for p in box]
    x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
    return (
        int(round(x1)),
        int(round(y1)),
        max(0, int(round(x2 - x1))),
        max(0, int(round(y2 - y1))),
    )


def get_ocr():
    """第一次调用才加载 RapidOCR，避免和正在跑的训练抢启动。"""
    global OCR_ENGINE
    if OCR_ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR

        OCR_ENGINE = RapidOCR()
    return OCR_ENGINE


def run_ocr(img: np.ndarray, upscale: float, text_score: float) -> list[dict]:
    work = img
    if abs(upscale - 1.0) > 1e-3:
        work = cv2.resize(
            img, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC
        )
    with OCR_LOCK:
        result, _elapse = get_ocr()(work, text_score=text_score)
    boxes: list[dict] = []
    if not result:
        return boxes
    for item in result:
        quad, raw_text, score = item[0], str(item[1]), float(item[2])
        text = collapse_cjk_spaces(raw_text.strip())
        if not text:
            continue
        if score != score:  # NaN
            score = 0.0
        score = min(max(score, 0.0), 1.0)
        x, y, w, h = quad_to_xywh(quad)
        boxes.append({
            "text": text,
            "x": int(round(x / upscale)),
            "y": int(round(y / upscale)),
            "w": max(0, int(round(w / upscale))),
            "h": max(0, int(round(h / upscale))),
            "confidence": score,
        })
    return boxes


def parse_ocr_params() -> tuple[float, float]:
    src: dict = {}
    if request.is_json:
        body = request.get_json(silent=True) or {}
        for key in ("upscale", "text_score"):
            if key in body:
                src[key] = body[key]
    for key in ("upscale", "text_score"):
        if key in request.args:
            src[key] = request.args[key]
    try:
        upscale = float(src.get("upscale", 2))
    except (TypeError, ValueError) as e:
        raise ValueError("upscale 不是数字") from e
    if not (1.0 <= upscale <= 8.0):
        raise ValueError("upscale 必须在 1 到 8 之间（传 1 表示不放大）")
    try:
        text_score = float(src.get("text_score", 0.3))
    except (TypeError, ValueError) as e:
        raise ValueError("text_score 不是数字") from e
    text_score = min(max(text_score, 0.0), 1.0)
    return upscale, text_score


# --------------------------------------------------------------------------
# 路由
# --------------------------------------------------------------------------
@app.get("/health")
def health():
    return jsonify({
        "status": "ok" if MODEL is not None else "loading",
        "model": MODEL_PATH,
        "nc": len(CLASS_NAMES),
        "classes": CLASS_NAMES,
        "schema": schema_of(CLASS_NAMES),
        "list_item_aliases": sorted(LIST_ITEM_ALIASES),
        "device": "cpu",
        "torch": torch.__version__,
        "defaults": DEFAULTS,
        "uptime_sec": round(time.time() - START_TS, 1),
        "host": socket.gethostname(),
        "ocr": {
            "engine": "rapidocr-onnxruntime",
            "loaded": OCR_ENGINE is not None,
        },
    })


@app.get("/classes")
def classes():
    return jsonify({"nc": len(CLASS_NAMES), "classes": CLASS_NAMES, "schema": schema_of(CLASS_NAMES),
                    "list_item_aliases": sorted(LIST_ITEM_ALIASES)})


@app.post("/predict")
def predict():
    try:
        img = load_from_request()
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": f"读取图片失败: {e}"}), 400

    params = parse_params()
    try:
        r = run_inference(img, params)
    except Exception as e:
        return jsonify({"success": False, "error": f"推理失败: {e}"}), 500

    out = result_to_dict(r, params)
    if request.args.get("annotated") in ("1", "true", "yes"):
        try:
            out["annotated_image"] = "data:image/jpeg;base64," + base64.b64encode(
                encode_jpeg(r.plot())
            ).decode()
        except Exception as e:
            out["annotated_error"] = str(e)
    return jsonify(out)



@app.post("/ocr")
def ocr():
    """返回与 macosocr/winocr 相同的 JSON 数组。失败时才是 {success:false, error}。"""
    try:
        img = load_from_request()
        upscale, text_score = parse_ocr_params()
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": f"读取图片失败: {e}"}), 400
    try:
        boxes = run_ocr(img, upscale, text_score)
    except Exception as e:
        return jsonify({"success": False, "error": f"OCR 失败: {e}"}), 500
    return Response(
        json.dumps(boxes, ensure_ascii=False),
        mimetype="application/json; charset=utf-8",
    )


@app.post("/predict/image")
def predict_image():
    try:
        img = load_from_request()
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400
    try:
        r = run_inference(img, parse_params())
    except Exception as e:
        return jsonify({"success": False, "error": f"推理失败: {e}"}), 500
    resp = Response(encode_jpeg(r.plot()), mimetype="image/jpeg")
    resp.headers["X-Detections"] = str(len(r.boxes) if r.boxes is not None else 0)
    return resp


@app.errorhandler(413)
def too_large(_):
    return jsonify({"success": False, "error": "图片超过 32MB 上限"}), 413


@app.errorhandler(404)
def not_found(_):
    return jsonify({
        "success": False,
        "error": "接口不存在",
        "routes": ["GET /", "GET /health", "GET /classes", "POST /predict", "POST /predict/image", "POST /ocr"],
    }), 404


INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>YOLO26 企业微信 UI 元素检测</title>
<style>
  :root{--bg:#f6f7f9;--card:#fff;--line:#e3e6ea;--txt:#1f2328;--dim:#6b7280;--accent:#c0392b}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--txt);
       font:14px/1.6 -apple-system,"PingFang SC","Helvetica Neue",Arial,sans-serif}
  .wrap{max-width:1180px;margin:0 auto;padding:28px 20px 60px}
  h1{font-size:20px;margin:0 0 4px}
  .sub{color:var(--dim);font-size:13px;margin-bottom:20px}
  .grid{display:grid;grid-template-columns:minmax(0,1fr) 380px;gap:18px}
  @media(max-width:900px){.grid{grid-template-columns:1fr}}
  .card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}
  .drop{border:1.5px dashed #c7ccd3;border-radius:10px;padding:38px 16px;text-align:center;
        color:var(--dim);cursor:pointer;background:#fbfcfd;transition:.15s}
  .drop:hover,.drop.on{border-color:var(--accent);color:var(--accent);background:#fdf4f3}
  #stage{position:relative;line-height:0;margin-top:12px}
  #stage img{width:100%;border-radius:8px;display:block}
  #stage canvas{position:absolute;inset:0;width:100%;height:100%}
  .row{display:flex;gap:10px;align-items:center;margin-bottom:10px}
  .row label{width:58px;color:var(--dim);flex:none}
  input[type=range]{flex:1;accent-color:var(--accent)}
  .val{width:46px;text-align:right;font-variant-numeric:tabular-nums;color:var(--dim)}
  button{background:var(--accent);color:#fff;border:0;border-radius:8px;padding:10px 18px;
         font-size:14px;cursor:pointer}
  button:disabled{opacity:.5;cursor:default}
  .btn2{background:#eef1f4;color:var(--txt)}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th,td{text-align:left;padding:6px 4px;border-bottom:1px solid var(--line)}
  th{color:var(--dim);font-weight:500}
  td.n{font-variant-numeric:tabular-nums;text-align:right}
  .tag{display:inline-block;padding:1px 7px;border-radius:5px;background:#eef1f4;font-size:12px}
  .meta{color:var(--dim);font-size:12px;margin-top:8px;word-break:break-all}
  pre{background:#f6f7f9;border:1px solid var(--line);border-radius:8px;padding:10px;
      max-height:260px;overflow:auto;font-size:12px;margin:10px 0 0}
</style>
</head>
<body>
<div class="wrap">
  <h1>YOLO26 · 企业微信 UI 元素检测</h1>
  <div class="sub" id="sub">模型加载中…</div>

  <div class="grid">
    <div class="card">
      <div class="drop" id="drop">点击选择图片，或把图片拖到这里</div>
      <input type="file" id="file" accept="image/*" hidden>
      <div id="stage"></div>
    </div>

    <div>
      <div class="card">
        <div class="row"><label>置信度</label>
          <input type="range" id="conf" min="0.05" max="0.9" step="0.05" value="0.25">
          <span class="val" id="confv">0.25</span></div>
        <div class="row"><label>IoU</label>
          <input type="range" id="iou" min="0.3" max="0.9" step="0.05" value="0.7">
          <span class="val" id="iouv">0.70</span></div>
        <div class="row"><label>尺寸</label>
          <input type="range" id="imgsz" min="320" max="1600" step="32" value="1280">
          <span class="val" id="imgszv">1280</span></div>
        <div style="display:flex;gap:10px;margin-top:14px">
          <button id="go" disabled>开始检测</button>
          <button id="dl" class="btn2" disabled>下载标注图</button>
        </div>
        <div class="meta" id="meta"></div>
      </div>

      <div class="card" style="margin-top:18px">
        <table><thead><tr><th>类别</th><th class="n">数量</th></tr></thead>
        <tbody id="stats"><tr><td colspan="2" style="color:#6b7280">暂无结果</td></tr></tbody></table>
        <pre id="raw" style="display:none"></pre>
      </div>
    </div>
  </div>
</div>

<script>
const $ = s => document.querySelector(s);
let curFile = null, curUrl = null, lastResult = null;

function bindRange(id, digits){
  const el = $(id), out = $(id + 'v');
  const sync = () => out.textContent = (+el.value).toFixed(digits);
  el.addEventListener('input', sync); sync();
}
bindRange('#conf',2); bindRange('#iou',2); bindRange('#imgsz',0);

fetch('/health').then(r=>r.json()).then(h=>{
  $('#sub').textContent = `模型 ${h.model.split('/').pop()} · ${h.nc} 个类别 · 设备 ${h.device}`;
  $('#go').disabled = h.status !== 'ok';
}).catch(()=> $('#sub').textContent = '健康检查失败');

const drop = $('#drop'), file = $('#file');
drop.onclick = () => file.click();
drop.ondragover = e => { e.preventDefault(); drop.classList.add('on'); };
drop.ondragleave = () => drop.classList.remove('on');
drop.ondrop = e => { e.preventDefault(); drop.classList.remove('on');
  if (e.dataTransfer.files[0]) loadFile(e.dataTransfer.files[0]); };
file.onchange = () => file.files[0] && loadFile(file.files[0]);

function loadFile(f){
  curFile = f;
  if (curUrl) URL.revokeObjectURL(curUrl);
  curUrl = URL.createObjectURL(f);
  $('#stage').innerHTML = `<img id="img" src="${curUrl}">`;
  $('#go').disabled = false; $('#dl').disabled = true;
  $('#meta').textContent = f.name + ' · ' + (f.size/1024).toFixed(0) + ' KB';
  $('#stats').innerHTML = '<tr><td colspan="2" style="color:#6b7280">暂无结果</td></tr>';
  $('#raw').style.display = 'none';
  $('#stage').onload = null;
  const im = $('#img');
  const draw = () => { lastResult = null; };
  (im.complete ? draw() : im.onload = draw)();
}

$('#go').onclick = async () => {
  if (!curFile) return;
  $('#go').disabled = true; $('#go').textContent = '检测中…';
  const fd = new FormData();
  fd.append('file', curFile);
  const qs = new URLSearchParams({conf:$('#conf').value, iou:$('#iou').value, imgsz:$('#imgsz').value});
  try{
    const res = await fetch('/predict?' + qs, {method:'POST', body:fd});
    const data = await res.json();
    if (!data.success) throw new Error(data.error || '未知错误');
    render(data);
  }catch(e){ alert('检测失败：' + e.message); }
  finally{ $('#go').disabled = false; $('#go').textContent = '开始检测'; }
};

function render(d){
  lastResult = d;
  const img = $('#img');
  const paint = () => {
    const stage = $('#stage');
    const old = stage.querySelector('canvas'); if (old) old.remove();
    const c = document.createElement('canvas');
    c.width = img.naturalWidth; c.height = img.naturalHeight;
    const ctx = c.getContext('2d');
    const color = i => `hsl(${(i*61)%360} 72% 45%)`;
    ctx.lineWidth = Math.max(1.5, img.naturalWidth/600);
    ctx.font = `${Math.max(11, img.naturalWidth/70)}px -apple-system,"PingFang SC",sans-serif`;
    ctx.textBaseline = 'top';
    d.detections.forEach(det => {
      const [x1,y1,x2,y2] = det.xyxy;
      const col = color(det.class_id);
      ctx.strokeStyle = col; ctx.strokeRect(x1,y1,x2-x1,y2-y1);
      const label = `${det.class_name} ${det.conf.toFixed(2)}`;
      const tw = ctx.measureText(label).width + 8, th = parseInt(ctx.font) + 6;
      ctx.fillStyle = col;
      ctx.fillRect(x1, Math.max(0, y1-th), tw, th);
      ctx.fillStyle = '#fff';
      ctx.fillText(label, x1+4, Math.max(0, y1-th)+3);
    });
    stage.appendChild(c);
  };
  if (img.complete) paint(); else img.onload = paint;

  const rows = Object.entries(d.class_counts).sort((a,b)=>b[1]-a[1]);
  $('#stats').innerHTML = rows.length
    ? rows.map(([k,v]) => `<tr><td><span class="tag">${k}</span></td><td class="n">${v}</td></tr>`).join('')
      + `<tr><td style="color:#6b7280">合计</td><td class="n"><b>${d.count}</b></td></tr>`
    : '<tr><td colspan="2" style="color:#6b7280">未检测到目标</td></tr>';
  const sp = d.speed_ms || {};
  $('#meta').textContent = `${d.image.width}×${d.image.height} · 推理 ${sp.inference ?? '-'}ms`
    + ` (前处理 ${sp.preprocess ?? '-'} / 后处理 ${sp.postprocess ?? '-'})`;
  $('#raw').textContent = JSON.stringify(d, null, 2);
  $('#raw').style.display = 'block';
  $('#dl').disabled = false;
}

$('#dl').onclick = () => {
  const c = $('#stage').querySelector('canvas'); if (!c) return;
  const a = document.createElement('a');
  a.href = c.toDataURL('image/jpeg', 0.92);
  a.download = (curFile?.name || 'result').replace(/\.[^.]+$/, '') + '_annotated.jpg';
  a.click();
};
</script>
</body>
</html>
"""


@app.get("/")
def index():
    return Response(INDEX_HTML, mimetype="text/html; charset=utf-8")


# --------------------------------------------------------------------------
# 启动
# --------------------------------------------------------------------------
def local_ips() -> list[str]:
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    for name in ("en0", "en1"):
        try:
            for line in os.popen(f"ipconfig getifaddr {name}").read().split():
                if line not in ips:
                    ips.append(line)
        except Exception:
            pass
    return ips


def load_model(path: str):
    """加载权重并填充全局 MODEL / MODEL_PATH / CLASS_NAMES。"""
    global MODEL, MODEL_PATH, CLASS_NAMES
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"权重不存在: {p}")
    t0 = time.time()
    MODEL = YOLO(str(p))
    MODEL_PATH = str(p.resolve())

    embedded = {int(k): str(v) for k, v in (MODEL.names or {}).items()}
    if embedded:
        # 权重内嵌的类别表才是训练时的真实标签，以它为准
        CLASS_NAMES = embedded
    else:
        CLASS_NAMES = dict(CLASS_NAMES_CANONICAL)
        print("[提示] 权重未内嵌类别表，改用 server.py 中的 CLASS_NAMES_CANONICAL")

    print(f"加载模型 {MODEL_PATH}")
    print(f"        {len(CLASS_NAMES)} 个类别，耗时 {time.time() - t0:.2f}s")
    print(f"        类别: {', '.join(f'{i}={n}' for i, n in sorted(CLASS_NAMES.items()))}")

    # 与本项目约定的类别表对一遍，不一致就喊出来 —— 多半是加载了别人的权重
    if embedded and CLASS_NAMES == CLASS_NAMES_LEGACY_C14:
        print("[提示] 这是旧 14 类（c14）权重：会话行/联系人行分别输出 conversation_item / contact_item，"
              "响应里的 logical_name 会把它们统一成 list_item")
    elif embedded and CLASS_NAMES != CLASS_NAMES_CANONICAL:
        print("[警告] 权重内嵌类别表与 server.py 的 CLASS_NAMES_CANONICAL 不一致：")
        for i in sorted(set(embedded) | set(CLASS_NAMES_CANONICAL)):
            a, b = embedded.get(i), CLASS_NAMES_CANONICAL.get(i)
            if a != b:
                print(f"         id {i}: 权重={a!r}  约定={b!r}")
        print("         接口以权重内嵌的为准（那是训练时的真实标签）")

    return MODEL


def make_app():
    """WSGI 工厂，给 waitress / gunicorn 等生产服务器用。

        waitress-serve --host 0.0.0.0 --port 8080 --call server:make_app

    配置一律走环境变量（生产服务器没法传 CLI 参数）：
        YOLO26_MODEL  权重路径
        YOLO26_IMGSZ / YOLO26_CONF / YOLO26_IOU / YOLO26_MAX_DET
    """
    global DEFAULTS
    DEFAULTS = {
        "conf": float(os.environ.get("YOLO26_CONF", 0.25)),
        "iou": float(os.environ.get("YOLO26_IOU", 0.7)),
        "imgsz": int(os.environ.get("YOLO26_IMGSZ", 1280)),
        "max_det": int(os.environ.get("YOLO26_MAX_DET", 300)),
    }
    load_model(os.environ.get("YOLO26_MODEL", str(ROOT / "weights" / "yolo26n_detect_wxchat.pt")))
    warmup()
    return app


def warmup():
    """预跑一次真实尺寸的推理，把 JIT / MKL 初始化的开销挡在首个真实请求之外。"""
    try:
        size = DEFAULTS["imgsz"]
        dummy = np.zeros((size, size, 3), dtype=np.uint8)
        t0 = time.time()
        with INFER_LOCK:
            MODEL.predict(source=dummy, imgsz=size, device="cpu", verbose=False)
        print(f"[warmup] 完成（imgsz={size}），耗时 {time.time() - t0:.2f}s")
    except Exception as e:
        print(f"[warmup] 跳过（{e}）")


def main() -> int:
    global MODEL, MODEL_PATH, CLASS_NAMES, DEFAULTS

    p = argparse.ArgumentParser(description="YOLO26 企业微信 UI 元素检测推理服务")
    p.add_argument("--model", default=str(ROOT / "weights" / "yolo26n_detect_wxwork.pt"))
    p.add_argument("--host", default="0.0.0.0", help="监听地址，0.0.0.0 表示所有网卡（外网/局域网可访问）")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--imgsz", type=int, default=1280, help="推理分辨率，默认 1280（截图小目标不能降）")
    p.add_argument("--conf", type=float, default=0.25)
    p.add_argument("--iou", type=float, default=0.7)
    p.add_argument("--threads", type=int, default=0, help="torch 线程数，0 表示用默认值")
    p.add_argument("--no-warmup", action="store_true")
    args = p.parse_args()

    if not Path(args.model).exists():
        print(f"[错误] 权重不存在: {args.model}")
        return 2

    if args.threads > 0:
        torch.set_num_threads(args.threads)

    DEFAULTS = {"conf": args.conf, "iou": args.iou, "imgsz": args.imgsz, "max_det": 300}

    print(f"Python  {platform.python_version()} ({platform.machine()})")
    print(f"torch   {torch.__version__}  线程 {torch.get_num_threads()}")
    load_model(args.model)

    if not args.no_warmup:
        warmup()

    print("\n服务已启动：")
    print(f"  本机   http://127.0.0.1:{args.port}/")
    for ip in local_ips():
        print(f"  局域网 http://{ip}:{args.port}/")
    if args.host == "0.0.0.0":
        print("  （监听 0.0.0.0，同一网络下的设备都可以访问）")
    print(f"  健康检查 GET  /health")
    print(f"  检测接口 POST /predict   (multipart file / raw image / JSON image_base64)")
    print(f"  标注图   POST /predict/image")
    print(f"  OCR      POST /ocr        (JSON 数组，字段同 macosocr/winocr)")
    print("\nCtrl-C 停止\n")

    app.run(host=args.host, port=args.port, threaded=True, debug=False, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
