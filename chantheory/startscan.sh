#!/bin/bash

# 脚本名称: start.sh
# 描述: 启动 Python 程序到后台，并将输出重定向到日志文件。

# --- 配置区 ---
VENV_DIR="../venv"                     # 虚拟环境目录
LOG_FILE="./chantheory.log"           # 日志文件名
MAIN_SCRIPT="./chantheorymain.py" # 主程序路径
# --- 配置区结束 ---

echo "--- 启动 Python 自动化程序 ---"

# 1. 检查虚拟环境是否存在
if [ ! -d "$VENV_DIR" ]; then
    echo "错误：虚拟环境 $VENV_DIR 不存在。请先运行 'python3 -m venv venv' 创建环境。"
    exit 1
fi

# 2. 激活虚拟环境
source "$VENV_DIR/bin/activate"
echo "已激活虚拟环境: $VENV_DIR"

# 3. 使用 nohup 运行程序
# 2>&1 将标准错误重定向到标准输出 (即日志文件)
nohup python "$MAIN_SCRIPT" > "$LOG_FILE" 2>&1 &

# 获取后台进程 ID
PID=$!
echo "程序已在后台启动。"
echo "进程 ID (PID): $PID"

# 将 PID 写入文件，供停止脚本使用
echo "$PID" > ./chantheory.pid

# 4. 退出虚拟环境（可选，但推荐保留终端在基础环境）
deactivate
echo "虚拟环境已退出。"

echo "你可以使用 'tail -f $LOG_FILE' 查看日志。"
