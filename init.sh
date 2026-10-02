#!/usr/bin/env bash
# 激活 yolo26 项目的 conda 环境并切到项目目录
#
# ⚠️ 必须用 source 运行，不要用 ./init.sh
#
#    ./init.sh         → 在子进程里跑。子进程能继承 PATH，但**不继承 shell 函数**，
#                        所以 conda 会退化成调二进制，报 "Run 'conda init' before
#                        'conda activate'"。而且就算跑通了，激活结果也影响不到
#                        你当前这个终端。
#    source ./init.sh  → 在当前 shell 里跑，激活和 cd 都真实生效。✅
#
# 用法:
#   source ./init.sh
#   . ./init.sh          # 等价写法

_PROJECT_DIR="/Users/admin/Desktop/workspace/yolo26"
_ENV_PREFIX="$_PROJECT_DIR/.conda/envs/yolo26"
_CONDA_SH="$HOME/miniconda3/etc/profile.d/conda.sh"

# ---- 1. 确保 conda 的 shell 函数可用 ----
# 交互式终端里 hook 已加载；非交互 shell（脚本、子进程）里没有，这里补上。
if [ "$(type -t conda 2>/dev/null)" != "function" ]; then
    if [ -f "$_CONDA_SH" ]; then
        . "$_CONDA_SH"
    else
        echo "错误: 找不到 $_CONDA_SH" >&2
        echo "      请确认 Miniconda 装在 $HOME/miniconda3" >&2
        unset _PROJECT_DIR _ENV_PREFIX _CONDA_SH
        return 1 2>/dev/null || exit 1
    fi
fi

# ---- 2. 环境目录必须存在 ----
if [ ! -x "$_ENV_PREFIX/bin/python" ]; then
    echo "错误: 环境不存在或已损坏: $_ENV_PREFIX" >&2
    echo "      重建方式见 README.md「组件版本」一节" >&2
    unset _PROJECT_DIR _ENV_PREFIX _CONDA_SH
    return 1 2>/dev/null || exit 1
fi

# ---- 3. 激活 ----
conda activate "$_ENV_PREFIX" || {
    echo "激活失败" >&2
    unset _PROJECT_DIR _ENV_PREFIX _CONDA_SH
    return 1 2>/dev/null || exit 1
}

# ---- 4. 切到项目目录 ----
cd "$_PROJECT_DIR" || {
    unset _PROJECT_DIR _ENV_PREFIX _CONDA_SH
    return 1 2>/dev/null || exit 1
}

# ---- 5. 自检 ----
echo "环境已激活"
echo "  CONDA_PREFIX = $CONDA_PREFIX"
echo "  python       = $(command -v python)"
echo "  cwd          = $PWD"

# ---- 6. 判断是 source 还是直接执行，后者要明确提醒 ----
_sourced=0
if [ -n "${ZSH_VERSION:-}" ]; then
    case "${ZSH_EVAL_CONTEXT:-}" in
        *:file*) _sourced=1 ;;
    esac
elif [ -n "${BASH_VERSION:-}" ]; then
    [ "${BASH_SOURCE[0]:-$0}" != "$0" ] && _sourced=1
fi

if [ "$_sourced" -eq 0 ]; then
    echo "" >&2
    echo "⚠️  你是用 ./init.sh 直接执行的，激活只发生在子进程里，" >&2
    echo "    当前终端不受影响。请改用:  source ./init.sh" >&2
fi

unset _PROJECT_DIR _ENV_PREFIX _CONDA_SH _sourced
