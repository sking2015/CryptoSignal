import sys
import os

# --- [路径修正] ---
# 获取当前脚本所在目录 (tools)
current_dir = os.path.dirname(os.path.abspath(__file__))
# 获取上级目录 (ChanLunBot) 的路径
parent_dir = os.path.dirname(current_dir)
# 构建 core 目录的路径
core_dir = os.path.join(parent_dir, 'core')

print("看一下core_dir",core_dir)


# 将 core 目录加入到 Python 的搜索路径中
if core_dir not in sys.path:
    sys.path.append(core_dir)
# ------------------
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates # [新增] 处理时间格式
from chantheoryScan import ChanLunStrategy
from hyperliquidDataMgr import MarketDataManager
from tqdm import tqdm

def run_backtest(symbol='BTC', main_lvl='1h', sub_lvl='15m', limit=1000):
    print(f"🚀 开始回测 {symbol} - 主级别:{main_lvl} 次级别:{sub_lvl}")
    
    db_path = os.path.join(core_dir, 'hyperliquid_data.db')
     
    # 1. 初始化
    strategy = ChanLunStrategy()
    mgr = MarketDataManager(db_path=db_path)   
    
    
    # 2. 自动拉取数据 (使用 detect_signals 里的逻辑保证对齐)
    # 我们这里手动计算一下倍率，确保数据足够
    ratio = strategy.get_time_ratio(main_lvl, sub_lvl)
    main_limit = limit
    sub_limit = int(limit * ratio) + 500
    
    print("正在加载历史数据...")
    df_main_full = mgr.load_data_for_analysis(symbol, main_lvl, limit=main_limit)
    df_sub_full = mgr.load_data_for_analysis(symbol, sub_lvl, limit=sub_limit)
    
    if df_main_full is None or df_sub_full is None:
        print("❌ 错误：数据不足，请先运行 chantheoryScan.py 更新数据")
        return

    # 3. 预计算指标
    df_main_full = strategy.calculate_indicators(df_main_full)
    
    buy_signals = []
    sell_signals = []
    
    # 4. 模拟时间推移
    start_idx = 100 
    print("正在逐根扫描历史K线...")
    
    for i in tqdm(range(start_idx, len(df_main_full))):
        # 模拟切片
        curr_main_df = df_main_full.iloc[:i+1].copy()
        current_time = curr_main_df.iloc[-1]['timestamp']
        
        # 获取对应的次级别切片
        curr_sub_df = df_sub_full[df_sub_full['timestamp'] <= current_time].copy()
        
        # 调用策略
        signal = strategy.analyze_snapshot(curr_main_df, curr_sub_df)
        
        if signal:
            # 记录信号 [修改点: 记录 timestamp 而不是 index]
            sig_data = {
                'time': current_time, 
                'price': signal['price'],
                'type': signal['type'],
                'desc': signal['desc']
            }
            
            if signal['action'] == 'buy':
                buy_signals.append(sig_data)
            else:
                sell_signals.append(sig_data)

    print(f"\n📊 回测结束。发现买点: {len(buy_signals)} 个, 卖点: {len(sell_signals)} 个")
    
    # 5. 绘图
    plot_results(df_main_full, buy_signals, sell_signals, symbol, main_lvl)

def plot_results(df, buys, sells, symbol, interval):
    # 创建画布
    fig, ax = plt.subplots(figsize=(16, 9))
    
    # [修改点] X轴直接使用 timestamp
    dates = df['timestamp']
    
    # 绘制价格线
    ax.plot(dates, df['close'], label='Close Price', color='#7f8c8d', alpha=0.6, linewidth=1.5)
    
    # 绘制均线 (MA60)
    ax.plot(dates, df['ma60'], label='MA60', color='#f39c12', linestyle='--', alpha=0.8, linewidth=1.5)

    # 绘制买点
    for sig in buys:
        # [修改点] 使用 sig['time'] 作为横坐标
        ax.scatter(sig['time'], sig['price'], marker='^', color='#2ecc71', s=120, zorder=5, edgecolors='black')
        ax.text(sig['time'], sig['price']*0.99, sig['type'], color='#27ae60', fontsize=10, ha='center', va='top', fontweight='bold')

    # 绘制卖点
    for sig in sells:
        # [修改点] 使用 sig['time'] 作为横坐标
        ax.scatter(sig['time'], sig['price'], marker='v', color='#e74c3c', s=120, zorder=5, edgecolors='black')
        ax.text(sig['time'], sig['price']*1.01, sig['type'], color='#c0392b', fontsize=10, ha='center', va='bottom', fontweight='bold')

    # [新增] X轴时间格式化
    # 设置主刻度格式：月-日 时:分 (例如 12-06 14:00)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
    # 自动调整刻度间距
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    # 旋转标签防止重叠
    fig.autofmt_xdate()

    # 标题和网格
    plt.title(f"ChanLun Strategy Backtest (V11.0) - {symbol} {interval}", fontsize=14)
    plt.legend(loc='upper left')
    plt.grid(True, alpha=0.25)
    
    # 保存与显示
    filename = f"backtest_{symbol}_{interval}.png"
    plt.savefig(filename, dpi=300) # 提高清晰度
    print(f"✅ 高清图表已保存为: {filename}")
    plt.show()

if __name__ == "__main__":
    # 在这里设置你想回测的参数
    # 建议: limit=1000 以查看更长的时间跨度
    sybName = sys.argv[1]
    run_backtest(symbol=sybName, main_lvl='30m', sub_lvl='5m', limit=1000)