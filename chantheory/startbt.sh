#!/bin/bash

# 脚本名称: start.sh
# 描述: 仅启动 Gunicorn 后端服务。

# --- 配置区 ---
VENV_DIR="../venv"
LOG_DIR="." # 日志文件与脚本同级
APP_MODULE="chantheoryserver:app" # 应用模块
APP_NAME="chantheoryserver"
WORKERS=4
# --- 配置区结束 ---

echo "--- 启动 Gunicorn 服务 ---"

# 1. 检查虚拟环境
if [ ! -d "$VENV_DIR" ]; then
    echo "错误：虚拟环境 $VENV_DIR 不存在。"
    exit 1
fi

# 2. 激活虚拟环境 (Gunicorn 会使用这个环境的 Python)
source "$VENV_DIR/bin/activate"
echo "已激活虚拟环境: $VENV_DIR"

# 3. 切换到应用所在的目录 (🚨 关键修复)
# 这一步确保 core/hyperliquid_data.db 路径是正确的
APP_DIR=$(dirname $(readlink -f "$0"))
cd "$APP_DIR"
echo "已切换到工作目录: $APP_DIR"

# 4. 启动 Gunicorn 进程 (使用 -c 参数配置)
# -c: 配置文件 (可以省略，直接用命令行参数)
# -w: worker 数量
# -b: 监听地址
# -D: 后台守护进程启动
gunicorn \
  --chdir "$APP_DIR" \
  -w $WORKERS \
  -b 0.0.0.0:5000 \
  -D \
  --access-logfile "$LOG_DIR/access.log" \
  --error-logfile "$LOG_DIR/error.log" \
  --pid "$LOG_DIR/$APP_NAME.pid" \
  "$APP_MODULE"

PID=$(cat "$LOG_DIR/$APP_NAME.pid")
echo "Gunicorn 服务已在后台启动。"
echo "进程 ID (PID): $PID"

# 5. 退出虚拟环境
deactivate
echo "虚拟环境已退出。"

echo "你可以使用 'tail -f $LOG_DIR/$APP_NAME.log' 或 'tail -f $LOG_DIR/error.log' 查看日志。"