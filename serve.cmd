@echo off
chcp 936 >nul
setlocal
cd /d "%~dp0"

rem ============================================================
rem  启动 YOLO26 企业微信 UI 元素检测推理服务（Windows 版 serve.sh）
rem
rem  用法:
rem    serve.cmd                    0.0.0.0:8080
rem    serve.cmd --port 9000        换端口
rem    serve.cmd --host 127.0.0.1   只允许本机访问
rem    serve.cmd --device cpu       强制 YOLO 走 CPU（默认 auto，有 CUDA 就上 GPU）
rem    serve.cmd --ocr-device gpu   OCR 走 GPU（默认 cpu —— 本机实测 CPU 更快）
rem    serve.cmd --model weights\xxx.pt
rem
rem  设备分工: YOLO 默认 GPU, OCR 默认 CPU。这不是偷懒 —— GTX 1660 这类小卡上
rem  PP-OCRv4 走 CUDA 反而慢 2~3 倍, 收益全被主机与显存之间搬运吃掉。
rem  想看自己机器上的实数: python tools\check_gpu.py --bench
rem
rem  所有参数原样透传给 server.py，完整列表见 python server.py --help。
rem  环境不存在就先跑 setup.cmd。
rem ============================================================

set "PY=%CD%\.conda\envs\yolo26\python.exe"
if not exist "%PY%" (
  echo [错误] 找不到 conda 环境解释器: %PY%
  echo        先跑一次 setup.cmd 建好 .conda\envs\yolo26
  exit /b 1
)

echo 解释器  %PY%
echo 设备    YOLO auto（有 CUDA 就上 GPU）/ OCR cpu
echo 提示    模型加载 + 预热要 10 到 30 秒，等它打出「服务已启动」再发请求
echo 提示    监听 0.0.0.0 时 Windows 防火墙会弹窗，勾上「专用网络」局域网才能访问
echo.

"%PY%" server.py %*
