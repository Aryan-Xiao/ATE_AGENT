#!/bin/bash
# ATE Agent 一键启动脚本
# 用法1:  bash run.sh                    （默认单次分析）
# 用法2:  bash run.sh -i                 （交互模式）
# 用法3:  bash run.sh "对比QC和FT数据"   （自定义分析请求）

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

# 如果虚拟环境不存在，创建并装依赖
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 首次运行，正在创建虚拟环境..."
    python3 -m venv "$VENV_DIR"
    echo "📦 正在安装依赖..."
    "$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt" -q
    echo "✅ 环境就绪"
fi

PYTHON="$VENV_DIR/bin/python3"

# 加载环境变量
if [ -f "$SCRIPT_DIR/.env" ]; then
    export $(grep -v '^#' "$SCRIPT_DIR/.env" | xargs)
fi

# 检查API Key
if [ -z "$LLM_API_KEY" ]; then
    echo "❌ 错误：未设置 LLM_API_KEY"
    echo "   请复制 .env.example 为 .env，然后填入你的API Key"
    exit 1
fi

echo "========================================"
echo "  ATE 数据分析 Agent (ReAct)"
echo "========================================"
echo "API: $LLM_BASE_URL"
echo "模型: $LLM_MODEL"
echo "数据目录: $SCRIPT_DIR/data/"
echo "========================================"
echo ""

cd "$SCRIPT_DIR"

# 根据参数决定模式
if [ "$1" = "-i" ]; then
    # 交互模式
    exec < /dev/tty
    $PYTHON ate_agent.py --interactive
elif [ $# -ge 1 ]; then
    # 有参数 -> 单次分析，参数作为分析请求
    $PYTHON ate_agent.py --request "$*"
else
    # 无参数 -> 默认分析
    $PYTHON ate_agent.py
fi
