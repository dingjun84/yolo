#!/usr/bin/env bash
# 启动 YOLO26 企业微信 UI 元素检测推理服务
#
# 用法:
#   ./serve.sh                    # 0.0.0.0:8080
#   ./serve.sh --port 9000        # 换端口
#   ./serve.sh --host 127.0.0.1   # 只允许本机访问
#
# 所有参数原样透传给 server.py，完整列表见 python server.py --help
set -euo pipefail

cd "$(dirname "$0")"

PY=".conda/envs/yolo26/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "[错误] 找不到 conda 环境解释器: $PY" >&2
  echo "       请确认已经按 README 建好 .conda/envs/yolo26" >&2
  exit 1
fi

exec "$PY" server.py "$@"
