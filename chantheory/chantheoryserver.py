import sys
import os

import pandas as pd
import numpy as np
from flask import Flask, jsonify, request,render_template
from flask_cors import CORS
import time

# --- [路径修正] 确保能引用到 core 目录 ---
current_dir = os.path.dirname(os.path.abspath(__file__))
core_dir = os.path.join(current_dir, 'core') 
if core_dir not in sys.path:
    sys.path.append(core_dir)

from chantheoryScan import ChanLunStrategy
from hyperliquidDataMgr import MarketDataManager


app = Flask(__name__)
CORS(app)

# 初始化
db_path = 'core/hyperliquid_data.db'
mgr = MarketDataManager(db_path=db_path)
strategy = ChanLunStrategy()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/run_backtest')
def run_backtest_endpoint():
    symbol = request.args.get('symbol', 'BTC')
    main_lvl = request.args.get('main_lvl', '1h')
    sub_lvl = request.args.get('sub_lvl', '15m')
    limit = int(request.args.get('limit', 1000))

    print(f"🚀 接到回测请求: {symbol} {main_lvl}/{sub_lvl} (Limit: {limit})")
    
    # 1. 准备数据
    if hasattr(strategy, 'get_time_ratio'):
        ratio = strategy.get_time_ratio(main_lvl, sub_lvl)
    else:
        ratio = 4 # 默认倍率

    main_limit = limit
    sub_limit = int(limit * ratio) + 500
    
    # 确保数据最新
    mgr.update_data(symbol, main_lvl)
    mgr.update_data(symbol, sub_lvl)
    
    # 加载数据
    df_main_full = mgr.load_data_for_analysis(symbol, main_lvl, limit=main_limit)
    df_sub_full = mgr.load_data_for_analysis(symbol, sub_lvl, limit=sub_limit)
    
    if df_main_full is None or df_sub_full is None:
        return jsonify({"status": "error", "message": "数据不足，请检查数据库或网络"}), 404

    # 2. 【核心修复】计算指标并覆盖原变量
    # 这样后续循环中的 curr_main_df 就会包含 'atr', 'macd' 等列了
    df_main_full = strategy.calculate_indicators(df_main_full)
    df_sub_full = strategy.calculate_indicators(df_sub_full)
    
    df_plot = df_main_full # 用于最后画图

    # 3. 开始回测循环
    buy_signals = []
    sell_signals = []
    start_idx = 100 
    
    print(f"🔄 开始回测扫描 {len(df_main_full)} 根K线...")
    t0 = time.time()
    
    # 4 重置策略状态 (如果策略类支持)
    if hasattr(strategy, 'reset_state'):
        strategy.reset_state()

    for i in range(start_idx, len(df_main_full)):
        # 模拟切片：这时的 curr_main_df 已经包含了 calculated_indicators 的结果
        curr_main_df = df_main_full.iloc[:i+1] 
        current_time = curr_main_df.iloc[-1]['timestamp']
        
        # 对齐次级别时间
        curr_sub_df = df_sub_full[df_sub_full['timestamp'] <= current_time]
        
        session_key = f"backtest_{symbol}_{main_lvl}"
        
        # 调用策略 (兼容不同版本的接口)
        signal = None
        try:
            # 尝试 V15 生产版接口 (5参数)
            signal = strategy.analyze_snapshot(symbol, main_lvl, curr_main_df, curr_sub_df)
        except TypeError:
            try:
                # 尝试 V14/V15 开发版接口 (3参数)
                signal = strategy.analyze_snapshot(curr_main_df, curr_sub_df)
            except TypeError:
                # 尝试 run_snapshot_analysis 接口 (最早的回测版)
                if hasattr(strategy, 'run_snapshot_analysis'):
                     signal = strategy.run_snapshot_analysis(curr_main_df, session_key)
        
        if signal:
            sig_data = {
                'time': current_time.strftime('%Y-%m-%d %H:%M'),
                'price': signal['price'],
                'type': signal['type'],
                'desc': signal.get('desc', ''),
                'action': signal['action']
            }
            if signal['action'] == 'buy':
                buy_signals.append(sig_data)
            else:
                sell_signals.append(sig_data)

    print(f"✅ 回测完成，耗时: {time.time()-t0:.2f}s | 信号数: {len(buy_signals)+len(sell_signals)}")

    
    # 5. 组装前端数据
    dates = df_main_full['timestamp'].dt.strftime('%Y-%m-%d %H:%M').tolist()
    ohlc = df_main_full[['open', 'close', 'low', 'high']].values.tolist()
    volumes = df_main_full['volume'].tolist()
    
    # 提取 MA60
    ma60 = df_plot['ma60'].fillna(0).tolist() if 'ma60' in df_plot else []

    # [新增] 提取 MACD 数据 (注意处理 NaN)
    macd_data = {
        'diff': df_plot['diff'].fillna(0).tolist(),
        'dea': df_plot['dea'].fillna(0).tolist(),
        'bar': df_plot['macd'].fillna(0).tolist()
    }
    
    # [新增] 提取 RSI 数据
    rsi_data = df_plot['rsi'].fillna(50).tolist() # 默认填充50中位数

    # 组装买卖点数组
    buys_fmt = [[s['time'], s['price'], s['type'], s['desc']] for s in buy_signals]
    sells_fmt = [[s['time'], s['price'], s['type'], s['desc']] for s in sell_signals]

    return jsonify({
        "status": "success",
        "data": {
            "dates": dates,
            "ohlc": ohlc,
            "volume": volumes,
            "ma60": ma60,
            "macd": macd_data,  # 返回 MACD
            "rsi": rsi_data,    # 返回 RSI
            "buys": buys_fmt,
            "sells": sells_fmt
        }
    })

if __name__ == '__main__':
    print("🚀 缠论回测服务端 (Backtest Service) 启动在 5000 端口...")
    app.run(debug=True, port=5000)