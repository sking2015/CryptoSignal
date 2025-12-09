import sys
import os
import time
import pandas as pd
import traceback
from datetime import datetime

# --- [路径修正] ---
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
core_dir = os.path.join(parent_dir, 'core') 
if not os.path.exists(core_dir):
    core_dir = os.path.join(current_dir, 'core')
if core_dir not in sys.path:
    sys.path.append(core_dir)

try:
    from chantheoryScan import ChanLunStrategy
    from hyperliquidDataMgr import MarketDataManager
except ImportError as e:
    print(f"致命错误: 无法导入核心模块。错误信息: {e}")
    sys.exit(1)

def run_state_initialization(symbol: str, main_lvl: str, sub_lvl: str, limit: int = 4000):
    """
    运行完整的历史回测模拟，并将最终状态持久化到数据库。
    """
    print(f"\n🚀 开始状态初始化: {symbol} {main_lvl}/{sub_lvl} (回溯 {limit} 根 K 线)")
    
    db_path = os.path.join(core_dir, 'hyperliquid_data.db')
    mgr = MarketDataManager(db_path=db_path)
    strategy = ChanLunStrategy(mgr)
    
    # 1. 【强制】更新和加载数据 (确保历史数据充足)
    try:
        # 这里调用 update_data 会触发 MarketDataManager 内部的 "策略 A: 历史回补" 逻辑
        # 只要数据库数据不足 400 条，它会拉取 5000 根K线前的所有数据
        mgr.update_data(symbol, main_lvl)
        mgr.update_data(symbol, sub_lvl)
    except Exception as e:
        print(f"⚠️ 数据更新失败 (可能是网络问题)，请检查网络连接: {e}")

    # 加载数据
    ratio = strategy.get_time_ratio(main_lvl, sub_lvl)
    sub_limit = limit * ratio + 500
    
    df_main_full = mgr.load_data_for_analysis(symbol, main_lvl, limit=limit)
    df_sub_full = mgr.load_data_for_analysis(symbol, sub_lvl, limit=sub_limit)
    
    if df_main_full is None or df_sub_full is None:
        print(f"❌ 错误: 无法从数据库加载数据。请检查 DataMgr 运行日志。")
        return

    # 2. 计算指标 (如果 K 线不足 100 根，这里会返回 None！)
    df_main_full = strategy.calculate_indicators(df_main_full)
    df_sub_full = strategy.calculate_indicators(df_sub_full)
    
    # 🚨 【修正】在这里检查 None，而不是让程序崩溃
    if df_main_full is None or df_sub_full is None:
        print(f"❌ 错误: K线数量不足 100 根，无法计算指标。请重新运行本初始化脚本，它会自动尝试补全历史数据。")
        return


    # 3. 开始模拟
    start_idx = 100 
    t0 = time.time()
    
    # 必须重置状态，确保从历史起点开始模拟
    strategy.reset_state() 
    
    final_state = None
    st_key = f"{symbol}_{main_lvl}"

    for i in range(start_idx, len(df_main_full)):
        curr_main_df = df_main_full.iloc[:i+1] 
        current_time = curr_main_df.iloc[-1]['timestamp']
        curr_sub_df = df_sub_full[df_sub_full['timestamp'] <= current_time]
        
        # 调用策略
        signal = strategy.analyze_snapshot(symbol, main_lvl, curr_main_df, curr_sub_df)
        
        # 记录当前状态
        final_state = strategy.states[st_key]


    # 4. 持久化最终状态
    try:
        mgr.save_strategy_state(st_key, final_state)
        
        print(f"\n✅ 初始化完成! 耗时: {time.time()-t0:.2f}s")
        print(f"   最终 K 线时间: {df_main_full.iloc[-1]['timestamp']}")
        print(f"   最终策略状态已保存: {final_state['state']}")
        
    except Exception as e:
        print(f"❌ 致命错误: 状态保存失败。请检查 DataMgr 中的 save_strategy_state 方法。错误: {e}")
        print(traceback.format_exc())

if __name__ == "__main__":
    # 需要初始化的币种和周期组合
    targets = [
        ('XRP', '4h', '30m'), # 你的目标组合
        ('BTC', '1d', '4h'),
        # ... (根据 chantheorymain.py 的配置添加其他组合)
    ]

    for symbol, main_lvl, sub_lvl in targets:
        run_state_initialization(symbol, main_lvl, sub_lvl)
        time.sleep(1)