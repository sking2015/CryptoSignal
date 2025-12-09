#!/bin/bash

# 脚本名称: start.sh
# 描述: 启动 Gunicorn 后端服务 (单进程安全模式)

# --- 配置区 ---
VENV_DIR="../venv"
LOG_DIR="." 
APP_MODULE="chantheoryserver:app"
APP_NAME="chantheoryserver"

# 🚨 关键修改点1: 切换到单进程模式，消除 SQLite 写入死锁问题。
WORKERS=1 

# 🚨 关键修改点2: 大幅增加超时时间，避免 worker 被 Gunicorn 杀死。
TIMEOUT=300 
# --- 配置区结束 ---

echo "--- 启动 Gunicorn 服务 (单进程安全模式) ---"

if [ ! -d "$VENV_DIR" ]; then
    echo "错误：虚拟环境 $VENV_DIR 不存在。"
    exit 1
fi

source "$VENV_DIR/bin/activate"
# 获取并切换到应用所在的目录，确保数据库路径正确
APP_DIR=$(dirname $(readlink -f "$0"))
cd "$APP_DIR"
echo "工作目录: $APP_DIR"

# 停止旧进程 (如果存在)
if [ -f "$LOG_DIR/$APP_NAME.pid" ]; then
    OLD_PID=$(cat "$LOG_DIR/$APP_NAME.pid")
    echo "正在停止旧进程 PID: $OLD_PID ..."
    kill $OLD_PID 2>/dev/null
    sleep 2
fi

# 启动 Gunicorn
# --chdir 用于确保 db_path 路径正确
gunicorn \
  --chdir "$APP_DIR" \
  -w $WORKERS \
  -b 0.0.0.0:5000 \
  -D \
  --timeout $TIMEOUT \
  --access-logfile "$LOG_DIR/access.log" \
  --error-logfile "$LOG_DIR/error.log" \
  --pid "$LOG_DIR/$APP_NAME.pid" \
  "$APP_MODULE"

sleep 1

PID=$(cat "$LOG_DIR/$APP_NAME.pid")
echo "✅ Gunicorn 服务已启动 (Timeout: ${TIMEOUT}s, Workers: ${WORKERS})。"
echo "进程 ID: $PID"

deactivate