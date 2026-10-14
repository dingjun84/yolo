#!/usr/bin/env python3
"""环境自检：确认 YOLO（torch）吃上了 GPU，并汇报 OCR 的可行设备。

setup.cmd 装完依赖会调一次，平时排查也可以直接跑：

    .conda\\envs\\yolo26\\python.exe tools\\check_gpu.py

⚠️ 关于 OCR 的设备：**OCR 默认就跑 CPU，而且这是有意的**，不是故障。
在 GTX 1660 这类小卡上实测过，PP-OCRv4 的三个子模型都只有几十 MB，走 CUDA
反而慢 2~3 倍 —— 算得动的部分本来就没多少，收益全被主机↔显存搬运和 cuDNN
首次 autotune 吃掉了。所以本脚本只在「装了 onnxruntime-gpu 且你想用」时
才去验证 CUDA EP 能不能真的加载起来。

OCR 那一段的重点：不要信 ort.get_available_providers()。它只返回「有哪些
provider 被编译进来了」，**不代表 CUDA EP 能真的加载成功**。实测踩过坑 ——
装上对着 CUDA 13 编的 onnxruntime-gpu（PyPI 从 1.27 起默认就是 CUDA 13）时，
它照样把 CUDAExecutionProvider 列出来，但 session 创建失败、静默回退 CPU，
接口全绿却毫无加速。所以这里直接解析 onnxruntime_providers_cuda.dll 的 PE
导入表，逐个确认它要的 CUDA DLL 到底在不在，能给出可证伪的结论。

退出码：
    0  YOLO 侧正常（OCR 在 CPU 也照样是 0）
    1  torch 没装上 CUDA 版，或 CUDA 不可用
    2  torch 正常，但 OCR 的 CUDA EP 用不了（只影响 --ocr-device gpu）
"""

from __future__ import annotations

import os
import platform
import struct
import sys
from pathlib import Path

REENABLE_HINT = "setup.cmd --cuda-ocr"


def line(title: str) -> None:
    print(f"\n=== {title} ===")


# --------------------------------------------------------------------------
# PE 导入表解析：拿到一个 DLL 直接静态依赖哪些 DLL
# --------------------------------------------------------------------------
def pe_imports(path: Path) -> list[str]:
    b = path.read_bytes()
    e_lfanew = struct.unpack_from("<I", b, 0x3C)[0]
    if b[e_lfanew:e_lfanew + 4] != b"PE\0\0":
        raise ValueError("不是 PE 文件")
    coff = e_lfanew + 4
    num_sec, = struct.unpack_from("<H", b, coff + 2)
    opt_size, = struct.unpack_from("<H", b, coff + 16)
    opt = coff + 20
    pe32plus = struct.unpack_from("<H", b, opt)[0] == 0x20B
    dd = opt + (112 if pe32plus else 96)

    secs = []
    sh = opt + opt_size
    for i in range(num_sec):
        vsize, vaddr, rsize, raw = struct.unpack_from("<IIII", b, sh + i * 40 + 8)
        secs.append((vaddr, vsize, raw, rsize))

    def rva2off(rva: int) -> int | None:
        for vaddr, vsize, raw, rsize in secs:
            if vaddr <= rva < vaddr + max(vsize, rsize):
                return raw + (rva - vaddr)
        return None

    imp_rva, _ = struct.unpack_from("<II", b, dd + 8)  # 目录 1 = Import
    off = rva2off(imp_rva)
    names: list[str] = []
    if off is None:
        return names
    while True:
        ent = b[off:off + 20]
        if len(ent) < 20 or ent == b"\0" * 20:
            break
        name_rva, = struct.unpack_from("<I", ent, 12)
        if not name_rva:
            break
        no = rva2off(name_rva)
        if no is None:
            break
        names.append(b[no:b.index(b"\0", no)].decode("ascii", "replace"))
        off += 20
    return names


def nvidia_bin_dirs(sp: Path) -> list[Path]:
    return sorted(p for p in (sp / "nvidia").glob("*/bin") if p.is_dir())


def mount_nvidia_dlls(sp: Path) -> list[Path]:
    dirs = nvidia_bin_dirs(sp)
    if os.name == "nt":
        for d in dirs:
            try:
                os.add_dll_directory(str(d))
            except (AttributeError, OSError):
                pass
            os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
    return dirs


def find_dll(name: str, dirs: list[Path], extra: list[Path]) -> Path | None:
    for d in list(dirs) + extra:
        f = d / name
        if f.exists():
            return f
    return None


# --------------------------------------------------------------------------
def check_torch() -> int:
    line("torch (YOLO)")
    try:
        import torch
    except Exception as e:
        print(f"[x] import torch 失败: {e}")
        return 1

    print(f"torch        {torch.__version__}")
    print(f"CUDA build   {torch.version.cuda}")
    avail = torch.cuda.is_available()
    print(f"cuda 可用    {avail}")

    if not avail:
        print("[x] torch.cuda.is_available() 为 False —— 装的多半是 CPU 版 torch")
        print("    修复: setup.cmd --force，或手动")
        print("          pip install torch torchvision --index-url "
              "https://download.pytorch.org/whl/cu128")
        return 1

    n = torch.cuda.device_count()
    print(f"设备数       {n}")
    for i in range(n):
        cap = f"{torch.cuda.get_device_capability(i)[0]}{torch.cuda.get_device_capability(i)[1]}"
        free, total = torch.cuda.mem_get_info(i)
        print(f"  [{i}] {torch.cuda.get_device_name(i)}  sm_{cap}"
              f"  显存 {free / 2**20:.0f}/{total / 2**20:.0f} MiB")
    try:
        import ultralytics

        print(f"ultralytics  {ultralytics.__version__}")
    except Exception as e:
        print(f"[!] ultralytics 不可用: {e}")
        return 1
    return 0


def check_ocr(sp: Path, want_gpu: bool) -> int:
    """want_gpu: 用户是否想用 OCR 的 GPU（--ocr-device gpu）。

    返回 0 表示「OCR 侧没问题」——装了 onnxruntime-gpu 但 EP 起不来、
    而用户本来就想用 CPU，那也不算问题。
    """
    line("onnxruntime (OCR · RapidOCR)")
    try:
        import onnxruntime as ort
    except Exception as e:
        print(f"[x] import onnxruntime 失败: {e}")
        print("    修复: pip install rapidocr-onnxruntime")
        return 2 if want_gpu else 0

    print(f"onnxruntime  {ort.__version__}")
    print(f"编译进来的 provider  {list(ort.get_available_providers())}")
    print("  （注意：上面这行**不能**证明 CUDA EP 可用，下面才作数）")

    capi = sp / "onnxruntime" / "capi"
    dll = capi / "onnxruntime_providers_cuda.dll"
    if not dll.exists():
        print("[i] 这是 CPU 版 onnxruntime —— OCR 走 CPU，正是默认行为，无需处理")
        print(f"    想改走 GPU（本机实测更慢，不建议）: {REENABLE_HINT}")
        return 2 if want_gpu else 0

    # --- 装了 GPU 版，验证 CUDA EP 是否真能加载 ---
    try:
        deps = [n for n in pe_imports(dll)
                if n.lower().startswith(("cublas", "cudart", "cufft", "cudnn", "nvrtc"))]
    except Exception as e:
        print(f"[!] 解析 PE 导入表失败: {e}")
        return 2 if want_gpu else 0

    dirs = nvidia_bin_dirs(sp)
    extra = [capi, Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"]
    print(f"\nCUDA EP 的静态依赖（{dll.name}）：")
    missing: list[str] = []
    for name in deps:
        w = find_dll(name, dirs, extra)
        print(f"  {'[ok]' if w else '[缺]'} {name}")
        if not w:
            missing.append(name)

    if not missing:
        print("\n[ok] 依赖齐全 —— 想要的话，--ocr-device gpu 可用")
        print("     （不想要也无所谓：默认 cpu，实测更快。真正的确认看 /health 的 ocr.on_gpu）")
        return 0

    # 给出可操作的判断：是缺 CUDA 大版本，还是根本没装运行库
    print("\n[!] OCR 的 CUDA EP 起不来（默认不影响使用，OCR 走 CPU 即可）")
    if want_gpu:
        print("    你是显式要 --ocr-device gpu 的，那必须修这个：")
    major_needed = {n.split("_")[-1].replace(".dll", "") for n in missing}
    have = sorted({p.name for d in dirs for p in d.glob("*.dll")})
    if major_needed and have:
        print(f"    这个 onnxruntime_providers_cuda.dll 要 CUDA {sorted(major_needed)} 的运行库，")
        print("    但 site-packages/nvidia 下装的是:")
        for h in have:
            print(f"      - {h}")
        print("    → 大版本对不上。PyPI 上 onnxruntime-gpu 从 1.27 起默认对着 CUDA 13 编译，")
        print("      而 nvidia-cublas-cu13 / nvidia-cudart-cu13 等**没有 Windows 轮子**，")
        print("      所以 Windows 上要走 CUDA 12 分支 —— 固定到 1.26.0：")
        print("        pip install \"onnxruntime-gpu==1.26.0\"")
        print("      （并确保装了 nvidia-cublas-cu12 / nvidia-cudnn-cu12 /")
        print("        nvidia-cuda-runtime-cu12 / nvidia-cufft-cu12）")
    else:
        print("    nvidia-*-cu12 运行库没装上:")
        print("      pip install nvidia-cublas-cu12 nvidia-cudnn-cu12 \\")
        print("                  nvidia-cuda-runtime-cu12 nvidia-cufft-cu12")
    return 2


def bench_ocr() -> None:
    """实测同一张图在 CPU / GPU 上的 OCR 耗时，用数据决定该用哪个。"""
    line("OCR 设备实测（同一张图，各跑 3 次取中位）")
    shot = next(iter(sorted((Path(__file__).resolve().parent.parent
                             / "real_screenshots").glob("*.png"))), None)
    if shot is None:
        print("[i] real_screenshots/ 里没有 png，跳过。")
        print("    想测的话放一张进去，或直接 POST /ocr 对比。")
        return

    try:
        import contextlib
        import io
        import time

        import cv2
        from rapidocr_onnxruntime import RapidOCR
    except Exception as e:
        print(f"[!] 依赖不全，跳过: {e}")
        return

    img = cv2.imread(str(shot))
    work = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    print(f"样例  {shot.name}  {img.shape[1]}x{img.shape[0]} → 放大 2x")

    results: dict[str, float] = {}
    for tag, cuda in (("CPU", False), ("GPU", True)):
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                ocr = RapidOCR(det_use_cuda=cuda, cls_use_cuda=cuda, rec_use_cuda=cuda)
            ocr(work)  # 预热：cuDNN autotune / 线程池初始化不算进来
            ts = []
            for _ in range(3):
                t = time.perf_counter()
                ocr(work)
                ts.append(time.perf_counter() - t)
            results[tag] = sorted(ts)[1]
            print(f"  {tag}  {results[tag]:.3f}s")
        except Exception as e:
            print(f"  {tag}  跑不了: {str(e)[:120]}")

    if len(results) == 2:
        fast = min(results, key=results.get)
        slow = max(results, key=results.get)
        print(f"\n  → {fast} 更快（{results[slow] / results[fast]:.2f}x）")
        if fast == "CPU":
            print("     serve.cmd 默认就是 --ocr-device cpu，不用改。")
        else:
            print("     serve.cmd 默认走 CPU；要用 GPU 得加: --ocr-device gpu")


def check_others() -> None:
    line("其它依赖")
    for mod in ("cv2", "numpy", "flask"):
        try:
            m = __import__(mod)
            try:
                from importlib.metadata import version as _v

                v = _v(mod if mod != "cv2" else "opencv-python")
            except Exception:
                v = getattr(m, "__version__", "?")
            print(f"{mod:<8} {v}")
        except Exception as e:
            print(f"[!] {mod:<8} 不可用: {e}")


def main() -> int:
    args = [a.lower() for a in sys.argv[1:]]
    want_gpu = any(a in ("--ocr-gpu", "--want-ocr-gpu") for a in args)
    do_bench = any(a in ("--bench", "-b") for a in args)

    print(f"Python  {platform.python_version()} ({platform.machine()})")
    print(f"可执行   {sys.executable}")
    print(f"prefix  {sys.prefix}")

    import site as _site

    roots = list(_site.getsitepackages()) + [str(Path(sys.prefix) / "Lib" / "site-packages")]
    sp = next((Path(r) for r in roots if (Path(r) / "onnxruntime").exists()), Path(roots[0]))

    # 顺序有讲究：先 import torch（让它把自己那份 cudnn 用掉），再挂 nvidia 目录。
    # torch 和 onnxruntime 各带一份 cudnn64_9.dll，反过来的话 torch 会 WinError 127。
    rc = check_torch()
    dirs = mount_nvidia_dlls(sp)
    print(f"\n已挂载   {len(dirs)} 个 nvidia DLL 目录（OCR 想走 GPU 时用得上）")

    ocr_rc = check_ocr(sp, want_gpu)
    if rc == 0 and ocr_rc == 2 and want_gpu:
        # 只有「显式要 OCR GPU 但没配好」才升级成失败
        rc = 2
    check_others()

    if do_bench:
        bench_ocr()

    line("结论")
    if rc == 0:
        print("OK —— YOLO 在 GPU 上，OCR 按默认走 CPU（实测更快），可以直接 serve.cmd")
    elif rc == 1:
        print("torch 侧有问题，先修好再起服务")
    else:
        print("torch 侧 OK；OCR 的 CUDA EP 没配好，但 OCR 走 CPU 就行，不影响使用")
    print()
    print("提示：nvidia-smi 看驱动是否正常。驱动自带的 CUDA 版本高于 torch/ORT")
    print("      要求的版本没问题，向下兼容；反过来不行。")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
