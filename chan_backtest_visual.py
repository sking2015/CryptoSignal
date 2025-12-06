import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from chantheoryScan import ChanLunStrategy
from hyperliquidDataMgr import MarketDataManager
from tqdm import tqdm # 进度条，如果没安装可以 pip install tqdm

def run_backtest(symbol='BTC', main_lvl='30m', sub_lvl='5m', limit=1000):
    print(f"🚀 开始回测 {symbol} - 主级别:{main_lvl} 次级别:{sub_lvl}")
    
    # 1. 初始化策略和数据管理器
    strategy = ChanLunStrategy()
    mgr = MarketDataManager()
    
    # 2. 读取足够长的历史数据
    print("正在加载历史数据...")
    # 确保已经执行过 update_data 或者数据库里有数据
    df_main_full = mgr.load_data_for_analysis(symbol, main_lvl, limit=limit)
    df_sub_full = mgr.load_data_for_analysis(symbol, sub_lvl, limit=limit * 4) # 次级别数据要更多
    
    if df_main_full is None or df_sub_full is None:
        print("❌ 错误：本地数据库没有足够的数据，请先运行 chantheoryScan.py 更新数据。")
        return

    # 3. 预先计算指标 (为了加速回测，避免在循环中重复计算)
    # 注意：虽然这里使用了未来数据计算了EMA，但在缠论分型判断中主要依赖结构，
    # 且EMA的递归特性使其在长周期下对初始值的敏感度降低。
    # 严谨回测应在循环内计算，但速度会极慢。此处为验证逻辑折中处理。
    df_main_full = strategy.calculate_indicators(df_main_full)
    df_sub_full = strategy.calculate_indicators(df_sub_full)
    
    buy_signals = []
    sell_signals = []
    
    # 4. 模拟时间推移 (Time-Travel Debugging)
    # 从第 100 根K线开始，因为需要足够的历史数据计算 MA60
    start_idx = 100 
    
    print("正在逐根扫描历史K线...")
    for i in tqdm(range(start_idx, len(df_main_full))):
        # A. 切片主级别数据：模拟“当下”
        curr_main_df = df_main_full.iloc[:i+1].copy() # 包含当前这根
        
        # B. 切片次级别数据：找到时间对齐的数据
        current_time = curr_main_df.iloc[-1]['timestamp']
        curr_sub_df = df_sub_full[df_sub_full['timestamp'] <= current_time].copy()
        
        if len(curr_sub_df) < 60: continue

        # C. 调用纯策略函数
        signal = strategy.analyze_snapshot(curr_main_df, curr_sub_df)
        
        if signal:
            # 记录信号用于绘图
            sig_data = {
                'index': curr_main_df.index[-1], # 记录索引位置
                'time': current_time,
                'price': signal['price'],
                'type': signal['type'], # 1B, 2S etc.
                'desc': signal['desc']
            }
            
            if signal['action'] == 'buy':
                buy_signals.append(sig_data)
            else:
                sell_signals.append(sig_data)

    print(f"\n📊 回测结束。发现买点: {len(buy_signals)} 个, 卖点: {len(sell_signals)} 个")
    
    # 5. 绘图验证
    plot_results(df_main_full, buy_signals, sell_signals, symbol, main_lvl)

def plot_results(df, buys, sells, symbol, interval):
    plt.figure(figsize=(16, 8))
    
    # 绘制价格曲线
    plt.plot(df.index, df['close'], label='Close Price', color='gray', alpha=0.5, linewidth=1)
    # 绘制 MA60 参考线
    plt.plot(df.index, df['ma60'], label='MA60', color='orange', linestyle='--', alpha=0.6)

    # 绘制买点
    for sig in buys:
        plt.scatter(sig['index'], sig['price'], marker='^', color='green', s=100, zorder=5)
        plt.text(sig['index'], sig['price']*0.98, sig['type'], color='green', fontsize=9, ha='center')

    # 绘制卖点
    for sig in sells:
        plt.scatter(sig['index'], sig['price'], marker='v', color='red', s=100, zorder=5)
        plt.text(sig['index'], sig['price']*1.02, sig['type'], color='red', fontsize=9, ha='center')

    plt.title(f"ChanLun Strategy Backtest - {symbol} {interval}")
    plt.legend()
    plt.grid(True, alpha=0.3)
    
    # 保存图片
    filename = f"backtest_{symbol}_{interval}.png"
    plt.savefig(filename)
    print(f"✅ 图表已保存为: {filename}")
    plt.show()

if __name__ == "__main__":
    # 在这里修改你想回测的币种和级别
    # 建议使用 1h + 15m 进行测试，或者 4h + 1h
    run_backtest(symbol='BTC', main_lvl='4h', sub_lvl='30m', limit=1000)