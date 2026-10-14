@echo off
chcp 936 >nul
setlocal
cd /d "%~dp0"

rem ============================================================
rem  yolo26 -- 在项目目录内建一套 conda 环境（GPU 版），一次性
rem
rem  用法:
rem    setup.cmd              建环境 + 装依赖；环境已存在就只补依赖
rem    setup.cmd --force      删掉旧环境重建
rem    setup.cmd --cpu        不装 CUDA 版 torch，退到 CPU
rem    setup.cmd --cuda-ocr   额外装 OCR 的 CUDA 运行库（约 1.5GB）
rem
rem  默认分工: YOLO 走 GPU, OCR 走 CPU。
rem  OCR 之所以不默认上 GPU, 是本机实测的结果: PP-OCRv4 子模型太小,
rem  在 GTX 1660 上走 CUDA 反而慢 2~3 倍, 还要多下 1.5GB 轮子、多一层
rem  cudnn 版本对齐的坑。要改回 GPU 就加 --cuda-ocr, 再 serve.cmd --ocr-device gpu。
rem
rem  环境位置: 【项目目录】\.conda\envs\yolo26
rem  这个目录已在 .gitignore 里，不会被提交。
rem
rem  装完会跑一次 tools\check_gpu.py 自检。想顺便实测两张卡谁快: 
rem    .conda\envs\yolo26\python.exe tools\check_gpu.py --bench
rem ============================================================

set "ENV_PREFIX=%CD%\.conda\envs\yolo26"
set "PY=%ENV_PREFIX%\python.exe"
set "PY_VER=3.11"
set "PKG_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple"
set "TORCH_INDEX=https://download.pytorch.org/whl/cu128"
rem
rem onnxruntime-gpu 必须钉版本: 从 1.27 起 PyPI 上的默认包是对着 CUDA 13 编的,
rem 而 nvidia-cublas-cu13 / nvidia-cudart-cu13 等在 PyPI 上没有 Windows 轮子,
rem 结果就是 CUDA EP 加载失败、静默回退 CPU —— 接口全绿但没有一点加速。
rem 1.26.0 是对着 CUDA 12.8 编的, 配下面那几个 nvidia-*-cu12 正好。
set "ORT_VER=1.26.0"

rem 本机实测: PyPI 走清华镜像约 6MB/s，PyTorch 官方源直连约 23MB/s，
rem 反而比走代理快。所以这里默认清掉代理变量，避免 pip 绕远路。
rem 如果你的网络必须走代理，先 set YOLO26_KEEP_PROXY=1 再跑本脚本。
if not "%YOLO26_KEEP_PROXY%"=="1" (
  set "HTTP_PROXY="
  set "HTTPS_PROXY="
  set "http_proxy="
  set "https_proxy="
  set "ALL_PROXY="
  set "all_proxy="
)

set "FORCE=0"
set "SKIP_CUDA=0"
set "CUDA_OCR=0"
for %%a in (%*) do (
  if /i "%%a"=="--force" set "FORCE=1"
  if /i "%%a"=="--cpu" set "SKIP_CUDA=1"
  if /i "%%a"=="--cuda-ocr" set "CUDA_OCR=1"
)
if "%SKIP_CUDA%"=="1" set "CUDA_OCR=0"

call :find_conda
if not defined CONDABIN (
  echo [错误] 找不到 conda.exe
  echo        先装 Miniconda，或把 conda 加进 PATH 再跑本脚本
  echo        下载: https://docs.conda.io/en/latest/miniconda.html
  exit /b 1
)

echo.
echo ============================================================
echo  yolo26 环境安装
echo ------------------------------------------------------------
echo  conda     %CONDABIN%
echo  环境      %ENV_PREFIX%
echo  PyPI      %PKG_MIRROR%
if "%SKIP_CUDA%"=="1" (
  echo  torch     CPU 版
  echo  OCR       CPU
) else (
  echo  torch     CUDA 版  索引 %TORCH_INDEX%
  echo  YOLO      GPU
  if "%CUDA_OCR%"=="1" (
    echo  OCR       GPU  --cuda-ocr
  ) else (
    echo  OCR       CPU  ^(实测更快; 要 GPU 加 --cuda-ocr^)
  )
)
echo ============================================================

echo.
echo [1/4] 准备 conda 环境
if exist "%PY%" if "%FORCE%"=="0" goto env_exists

if exist "%ENV_PREFIX%" (
  echo       删除旧环境 --force
  rd /s /q "%ENV_PREFIX%"
)
echo       创建 %ENV_PREFIX%   python=%PY_VER%
"%CONDABIN%" create -y -p "%ENV_PREFIX%" python=%PY_VER%
if errorlevel 1 goto fail
if not exist "%PY%" goto fail
goto install

:env_exists
echo       已存在，跳过创建: %ENV_PREFIX%

:install

echo.
echo [2/4] 更新 pip
"%PY%" -m pip install --upgrade pip -i "%PKG_MIRROR%"
if errorlevel 1 goto fail

echo.
if "%SKIP_CUDA%"=="1" goto torch_cpu

echo [3/4] 安装 PyTorch CUDA 版
echo       索引 %TORCH_INDEX%
"%PY%" -m pip install torch torchvision --index-url "%TORCH_INDEX%"
if errorlevel 1 (
  echo.
  echo [错误] PyTorch CUDA 版安装失败
  echo        退到 CPU 版:  setup.cmd --cpu
  echo        换镜像:       改本文件里的 TORCH_INDEX
  exit /b 1
)
goto torch_done

:torch_cpu
echo [3/4] 安装 PyTorch CPU 版
"%PY%" -m pip install torch torchvision -i "%PKG_MIRROR%"
if errorlevel 1 goto fail

:torch_done

echo.
echo [4/4] 安装其余依赖
"%PY%" -m pip install -i "%PKG_MIRROR%" ultralytics opencv-python numpy flask
if errorlevel 1 goto fail

rem onnxruntime 有个坑: CPU 版 (onnxruntime) 和 GPU 版 (onnxruntime-gpu) 是两个
rem 不同的发行包, 但都往同一个 onnxruntime 目录里装 —— 同时装会互相覆盖文件,
rem pip 有时报错有时静默装坏。所以每次先按本次要的设备把 onnxruntime 摆正,
rem 再装 rapidocr (它依赖的是 CPU 版那个名字)。
echo       onnxruntime
if "%CUDA_OCR%"=="1" (
  echo         GPU 版  onnxruntime-gpu==%ORT_VER%
  "%PY%" -m pip uninstall -y onnxruntime
  "%PY%" -m pip install -i "%PKG_MIRROR%" "onnxruntime-gpu==%ORT_VER%"
) else (
  echo         CPU 版  onnxruntime
  "%PY%" -m pip uninstall -y onnxruntime-gpu
  "%PY%" -m pip install -i "%PKG_MIRROR%" onnxruntime
)
if errorlevel 1 goto fail

echo       OCR: rapidocr-onnxruntime
"%PY%" -m pip install -i "%PKG_MIRROR%" rapidocr-onnxruntime
if errorlevel 1 goto fail

if "%CUDA_OCR%"=="0" goto deps_done

echo       OCR GPU 运行库: CUDA 12（约 1.5GB）
rem onnxruntime 的 CUDA EP 只认 CUDA 12.x + cuDNN 9，和驱动版本不是一回事。
rem 这些 wheel 里的 DLL 由 server.py 的 register_nvidia_dlls 在启动时挂进搜索路径。
rem cuDNN 钉 9.14 一路: 9.27 的前端启发式在 sm_75 上会 HEURISTIC_QUERY_FAILED,
rem conv 节点逐个回退 CPU, 比走 CPU 还慢。
"%PY%" -m pip install -i "%PKG_MIRROR%" nvidia-cuda-runtime-cu12 nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.14.*" nvidia-cufft-cu12
if errorlevel 1 goto fail

rem 实测提醒: 装完在上面的卡上 OCR 走 GPU 反而慢 2~3 倍, 所以启动时默认还是
rem --ocr-device cpu。这个开关等于给「换到大显卡」留的后路。

:deps_done

echo.
echo ====== 自检 ======
if "%CUDA_OCR%"=="1" (
  "%PY%" "tools\check_gpu.py" --ocr-gpu
) else (
  "%PY%" "tools\check_gpu.py"
)
set "RC=%ERRORLEVEL%"

echo.
echo ============================================================
echo  环境就绪: %ENV_PREFIX%
if "%RC%"=="0" (
  if "%CUDA_OCR%"=="1" (
    echo  YOLO 在 GPU 上; OCR 的 CUDA EP 也可用
  ) else (
    echo  YOLO 在 GPU 上; OCR 走 CPU ^(实测比 GPU 快^)
  )
) else if "%RC%"=="2" (
  echo  YOLO 在 GPU 上; OCR 的 CUDA EP 没配好, 走 CPU 即可, 不影响使用
) else (
  echo  自检未全绿，看上面的输出
)
echo.
echo  启动服务   serve.cmd
echo  换端口     serve.cmd --port 9000
if "%CUDA_OCR%"=="1" echo  OCR 走 GPU  serve.cmd --ocr-device gpu
echo ============================================================
exit /b %RC%

:fail
echo.
echo [错误] 安装中断，看上面的 pip 输出。
echo        环境位置: %ENV_PREFIX%
echo        直接再跑一次 setup.cmd 即可续装。
exit /b 1

rem ------------------------------------------------------------
rem  找 conda.exe：优先环境变量，再扫常见安装位置，最后查 PATH
rem ------------------------------------------------------------
:find_conda
set "CONDABIN="
if defined CONDA_EXE if exist "%CONDA_EXE%" set "CONDABIN=%CONDA_EXE%"
if not defined CONDABIN if exist "%USERPROFILE%\miniconda3\Scripts\conda.exe" set "CONDABIN=%USERPROFILE%\miniconda3\Scripts\conda.exe"
if not defined CONDABIN if exist "%USERPROFILE%\anaconda3\Scripts\conda.exe" set "CONDABIN=%USERPROFILE%\anaconda3\Scripts\conda.exe"
if not defined CONDABIN if exist "%LOCALAPPDATA%\miniconda3\Scripts\conda.exe" set "CONDABIN=%LOCALAPPDATA%\miniconda3\Scripts\conda.exe"
if not defined CONDABIN if exist "%ProgramData%\miniconda3\Scripts\conda.exe" set "CONDABIN=%ProgramData%\miniconda3\Scripts\conda.exe"
if not defined CONDABIN if exist "%ProgramData%\anaconda3\Scripts\conda.exe" set "CONDABIN=%ProgramData%\anaconda3\Scripts\conda.exe"
if not defined CONDABIN for /f "delims=" %%i in ('where conda 2^>nul') do if not defined CONDABIN set "CONDABIN=%%i"
exit /b 0
