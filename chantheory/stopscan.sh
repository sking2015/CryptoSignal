#!/bin/bash

# 脚本名称: stop.sh
# 描述: 终止后台运行的 Python 程序。

# --- 配置区 ---
PID_FILE="./chantheory.pid"           # PID 文件名
# --- 配置区结束 ---

echo "--- 终止 Python 自动化程序 ---"

# 1. 检查 PID 文件是否存在
if [ ! -f "$PID_FILE" ]; then
    echo "错误：未找到 PID 文件 ($PID_FILE)。程序可能未运行或启动失败。"
    exit 1
fi

# 2. 读取 PID
PID=$(cat "$PID_FILE")

# 3. 检查进程是否仍在运行
if ps -p $PID > /dev/null
then
   echo "正在终止进程 (PID: $PID)..."
   # 发送 TERM 信号，尝试优雅地终止进程
   kill $PID
   
   # 4. 移除 PID 文件
   rm "$PID_FILE"
   echo "进程终止成功。"
else
   echo "进程 (PID: $PID) 似乎已经停止。"
   # 进程不存在，但 PID 文件还在，移除它
   rm "$PID_FILE"
fi

# 2. 停止 Gunicorn 回测服务端 (暴力停止)
echo "正在终止回测服务端..."
pkill gunicorn
# pkill 命令如果没找到进程会返回非0状态，这里我们不让它报错，只是简单提示
echo "✅ 回测服务端停止指令已发送。"

echo "--- 全部服务已停止 ---"