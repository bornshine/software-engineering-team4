#!/usr/bin/env bash
# 实测脚本：在仓库根目录运行 bash tests/run_demo.sh
# 依次执行：分解 -> 一轮多轮对话（改派+确认、接口变更+确认）-> 查看落库状态
# 全程输出写入 outputs/demo_run.log
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p outputs
{
  echo "===== 1. 分解：decompose ====="
  python3 main.py decompose --spec examples/spec.json --deadline 2026-12-25
  echo
  echo "===== 2. 多轮对话：列表 -> 详情 -> 改派+确认 -> 接口变更+确认 -> 变更记录 ====="
  printf '列表\n详情 T-02\n改派 T-01 给 DevAgent-B\n确认\n接口变更 M3\n确认\n变更记录\n退出\n' | python3 main.py chat
  echo
  echo "===== 3. 落库后状态：show ====="
  python3 main.py show
} 2>&1 | tee outputs/demo_run.log
