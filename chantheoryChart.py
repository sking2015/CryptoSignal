import pandas as pd
import numpy as np
import mplfinance as mpf
import sqlite3

# ==========================================
# 1. 数据与缠论结构处理类
# ==========================================
class ChanLunVisualizer:
    def __init__(self, db_path='hyperliquid_data.db'):
        self.db_path = db_path

    def load_data(self, symbol, interval, limit=300):
        """从数据库读取数据"""
        try:
            conn = sqlite3.connect(self.db_path)
            query = f"""
                SELECT timestamp, open, high, low, close, volume 
                FROM klines 
                WHERE symbol = '{symbol}' AND interval = '{interval}'
                ORDER BY timestamp ASC
            """
            df = pd.read_sql_query(query, conn)
            conn.close()
            if df.empty: return None
            
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            # 计算 MACD 供后续逻辑使用
            # 来源 [3]: DIF是核心，DEA是辅助
            exp12 = df['close'].ewm(span=12, adjust=False).mean()
            exp26 = df['close'].ewm(span=26, adjust=False).mean()
            df['diff'] = exp12 - exp26
            df['dea'] = df['diff'].ewm(span=9, adjust=False).mean()
            df['macd'] = (df['diff'] - df['dea']) * 2
            
            return df.tail(limit)
        except Exception as e:
            print(f"数据读取错误: {e}")
            return None
        
    def find_fractals(self, df):
        """
        识别顶分型和底分型
        来源: 缠论定义，中间K线高点最高为顶分型，低点最低为底分型
        修正：使用 .iloc 消除 FutureWarning 警告
        """
        # 为了安全，先重置索引或确保使用 iloc
        # df['fractal'] = 0  <-- 这种赋值会报 SettingWithCopyWarning，建议如下操作：
        df = df.copy()
        df['fractal'] = 0 
        
        highs = df['high']
        lows = df['low']
        
        # 使用 5 根 K 线判断分型 (简化版包含关系处理)
        for i in range(2, len(df) - 2):
            # 顶分型：中间高点最高，低点也相对较高
            if (highs.iloc[i] > highs.iloc[i-1] and 
                highs.iloc[i] > highs.iloc[i+1] and
                highs.iloc[i] > highs.iloc[i-2] and
                highs.iloc[i] > highs.iloc[i+2]):
                df.iloc[i, df.columns.get_loc('fractal')] = 1
                
            # 底分型：中间低点最低
            elif (lows.iloc[i] < lows.iloc[i-1] and 
                  lows.iloc[i] < lows.iloc[i+1] and 
                  lows.iloc[i] < lows.iloc[i-2] and 
                  lows.iloc[i] < lows.iloc[i+2]):
                df.iloc[i, df.columns.get_loc('fractal')] = -1
        
        return df

    def construct_bi(self, df):
        """
        构造“笔” (Bi)
        逻辑：连接相邻的顶分型和底分型，且中间必须有独立的 K 线
        """
        bi_points = [] # 存储笔的节点 (时间, 价格)
        last_type = 0 # 上一个分型类型
        
        # 提取所有分型点
        fractals = df[df['fractal'] != 0]
        
        for index, row in fractals.iterrows():
            curr_type = row['fractal']
            
            if last_type == 0:
                # 第一个点，初始化
                if curr_type == 1: point = (index, row['high'])
                else: point = (index, row['low'])
                bi_points.append(point)
                last_type = curr_type
                continue
            
            # 必须是一顶一底交替
            if curr_type == 1 and last_type == -1: # 底 -> 顶 (向上笔)
                # === 修正点 1: bi_points[-1][0] 取出时间戳 ===
                if len(df.loc[bi_points[-1][0]:index]) > 3: 
                    bi_points.append((index, row['high']))
                    last_type = 1
                else:
                    # 如果距离太近，更新高点（认为是延伸）
                    # 比较价格，取 bi_points[-1][1]
                    if row['high'] > bi_points[-1][1]: 
                        bi_points.pop()
                        bi_points.append((index, row['high']))

            elif curr_type == -1 and last_type == 1: # 顶 -> 底 (向下笔)
                # === 修正点 2: bi_points[-1][0] 取出时间戳 ===
                if len(df.loc[bi_points[-1][0]:index]) > 3:
                    bi_points.append((index, row['low']))
                    last_type = -1
                else:
                    # 如果距离太近，更新低点
                    # 比较价格，取 bi_points[-1][1]
                    if row['low'] < bi_points[-1][1]:
                        bi_points.pop()
                        bi_points.append((index, row['low']))
        
        return bi_points

    def detect_buy_points(self, df, bi_points):
        """
        基于笔和 MACD 识别买卖点
        修正：
        1. 索引从 [4] 改为 [1] (因为 bi_points 只有 (时间, 价格))
        2. df.loc 切片时使用 [0] 获取时间戳
        """
        buy_signals = [] # (时间, 价格, 类型)
        
        if len(bi_points) < 4: return buy_signals
        
        # 遍历“向下笔”的终点（即底分型点）
        # 笔的索引：0,1,2... 偶数到底如果是向下笔 (假设从顶开始)
        # 这里逻辑是：i 是当前笔的终点。
        
        for i in range(3, len(bi_points), 2):
            curr_bottom = bi_points[i]   # (time, price)
            prev_top = bi_points[i-1]    # (time, price)
            prev_bottom = bi_points[i-2] # (time, price)
            prev_top_prev = bi_points[i-3] # (time, price) - 前前顶
            
            # === 修正点 1: 比较价格用 [1] ===
            # 简单的逻辑检查：底必须比前一个顶低，否则不是下降笔（虽然后续笔逻辑保证了这一点，但作为防守检查）
            if curr_bottom[1] >= prev_top[1]: continue 
            
            # 1. 第一类买点：价格创新低 + 背驰
            # === 修正点 2: 比较价格用 [1] ===
            if curr_bottom[1] < prev_bottom[1]:
                # 获取对应时间段的 MACD
                try:
                    # === 修正点 3: 切片需用时间戳 [0] ===
                    # 当前向下笔的 MACD
                    curr_macd_data = df.loc[prev_top[0]:curr_bottom[0]]['macd']
                    if curr_macd_data.empty: continue
                    curr_macd = curr_macd_data.min()

                    # 前一段向下笔的 MACD
                    prev_macd_data = df.loc[prev_top_prev[0]:prev_bottom[0]]['macd']
                    if prev_macd_data.empty: continue
                    prev_macd = prev_macd_data.min()
                    
                    # 背驰判断：价格新低，但 MACD 动能减弱（值比前一次大）
                    if curr_macd < 0 and curr_macd > prev_macd:
                         # === 修正点 4: 添加信号时解包元组，确保格式为 (时间, 价格, 类型) ===
                         buy_signals.append((curr_bottom[0], curr_bottom[1], 'B1 (Divergence)'))
                except Exception as e:
                    # print(f"MACD计算出错: {e}") 
                    pass
            
            # 2. 第二类买点 (三段结构：下-上-下，不破前低)
            # === 修正点 5: 比较价格用 [1] ===
            elif curr_bottom[1] > prev_bottom[1]:
                # 简单的结构判定：低点抬高
                buy_signals.append((curr_bottom[0], curr_bottom[1], 'B2 (Higher Low)'))

        return buy_signals
    
    # === 新增：识别卖点函数 ===
    def detect_sell_points(self, df, bi_points):
        """
        识别卖点：顶背驰(1卖) 和 顶部降低(2卖)
        修正说明：
        1. 修复 start_idx 判断逻辑，只取第一个点的时间戳。
        2. 修复价格索引，从 [5] 改为 [1]。
        3. 修复切片逻辑，添加 [0] 取时间戳。
        """
        sell_signals = [] 
        if len(bi_points) < 4: return sell_signals
        
        # === 修正点 1: 正确判断起始点分型 ===
        # 获取第一个点的时间戳
        first_ts = bi_points[0][0]
        # 获取该点的分型类型 (-1 底, 1 顶)
        # 使用 .at 快速访问标量值
        first_fractal = df.at[first_ts, 'fractal']
        
        # 确定循环起始点
        # 如果第一个是底(-1)，则序列为: 底(0), 顶(1), 底(2), 顶(3)... -> 从索引 3 开始比较 (3 vs 1)
        # 如果第一个是顶(1)， 则序列为: 顶(0), 底(1), 顶(2), 底(3), 顶(4)... -> 从索引 4 开始比较 (4 vs 2)
        # 为什么不能从 2 开始？因为我们需要计算 MACD 时用到 prev_bottom_prev (i-3)，索引必须 >= 3
        start_idx = 3 if first_fractal == -1 else 4
        
        for i in range(start_idx, len(bi_points), 2):
            curr_top = bi_points[i]      # 当前顶 (time, price)
            prev_top = bi_points[i-2]    # 前一个顶
            prev_bottom = bi_points[i-1] # 中间的底
            prev_bottom_prev = bi_points[i-3] # 前前底 (用于计算前一段MACD)
            
            # === 修正点 2: 价格索引改为 [1] ===
            # 确保结构正常：顶必须比中间的底高
            if curr_top[1] <= prev_bottom[1]: continue

            # === 修正点 3: 价格索引改为 [1] ===
            # 第一类卖点：价格创新高 + MACD顶背驰
            if curr_top[1] > prev_top[1]:
                try:
                    # === 修正点 4: 切片使用 [0] 取时间戳 ===
                    # 获取当前向上笔的 MACD 最大值
                    curr_macd_series = df.loc[prev_bottom[0]:curr_top[0]]['macd']
                    if curr_macd_series.empty: continue
                    curr_macd_max = curr_macd_series.max()
                    
                    # 获取前一段向上笔的 MACD 最大值
                    prev_macd_series = df.loc[prev_bottom_prev[0]:prev_top[0]]['macd']
                    if prev_macd_series.empty: continue
                    prev_macd_max = prev_macd_series.max()
                    
                    # 价格新高，但红柱子高度（力度）变小 (背驰)
                    if curr_macd_max > 0 and curr_macd_max < prev_macd_max:
                         # 记录格式 (时间, 价格, 类型)
                         sell_signals.append((curr_top[0], curr_top[1], 'S1 (Divergence)'))
                except Exception as e: 
                    # print(f"卖点MACD计算错误: {e}")
                    pass
            
            # 第二类卖点：反弹不创新高 (顶比前一个顶低)
            elif curr_top[1] < prev_top[1]:
                sell_signals.append((curr_top[0], curr_top[1], 'S2 (Lower High)'))
                
        return sell_signals
    
    def plot_chart(self, df, bi_points, buy_signals, sell_signals):
        """绘图：红笔，紫买点，绿卖点"""
        
        # 1. 构造笔数据
        bi_lines = bi_points
        
        # 2. 构造买卖点标记
        buy_markers = [np.nan] * len(df)
        sell_markers = [np.nan] * len(df)
        
        time_to_idx = {t: i for i, t in enumerate(df.index)}
        
        # 填充买点 (紫色向上箭头)
        for ts, price, label in buy_signals:
            if ts in time_to_idx:
                idx = time_to_idx[ts]
                buy_markers[idx] = price * 0.99 
        
        # 填充卖点 (绿色向下箭头)
        for ts, price, label in sell_signals:
            if ts in time_to_idx:
                idx = time_to_idx[ts]
                sell_markers[idx] = price * 1.01 # 画在K线上方

        # 设置绘图风格
        mc = mpf.make_marketcolors(up='r', down='g', edge='i', wick='i', volume='in', inherit=True)
        s = mpf.make_mpf_style(marketcolors=mc, gridstyle='--', y_on_right=True)
        
        # 添加图层
        apds = [
            # 买点：紫色 ^
            mpf.make_addplot(buy_markers, type='scatter', markersize=100, marker='^', color='m'), 
            # 卖点：绿色 v
            mpf.make_addplot(sell_markers, type='scatter', markersize=100, marker='v', color='g'),
            # MACD
            mpf.make_addplot(df['diff'], panel=1, color='y', width=1),
            mpf.make_addplot(df['dea'], panel=1, color='w', width=1),
            mpf.make_addplot(df['macd'], panel=1, type='bar', color='c', alpha=0.5),
        ]
        
        title = f"ChanLun: Red Bi & Buy/Sell Points"
        
        # 绘制
        # === 修正点：linewidth -> linewidths (必须是复数) ===
        mpf.plot(df, type='candle', style=s, 
                 addplot=apds,
                 alines=dict(alines=bi_lines, colors='red', linewidths=2, alpha=0.7), # 这里改为 linewidths
                 volume=True, 
                 figratio=(12, 8), 
                 title=title,
                 panel_ratios=(3, 1))

# ==========================================
# 运行可视化
# ==========================================
if __name__ == "__main__":
    # 确保你已经运行过之前的数据获取程序，数据库里有数据
    viz = ChanLunVisualizer()
    
    # 读取 BTC 30分钟数据
    symbol = 'BTC'
    df = viz.load_data(symbol, '30m', limit=200)
    
    if df is not None:
        # 1. 识别分型
        df = viz.find_fractals(df)
        # 2. 构造笔
        bi_structure = viz.construct_bi(df)
        # 3. 识别买点
        buys = viz.detect_buy_points(df, bi_structure)
        sells = viz.detect_sell_points(df, bi_structure) # 新增卖点检测
        
        print(f"识别到 {len(bi_structure)-1} 笔")
        print(f"买点: {len(buys)} 个, 卖点: {len(sells)} 个")
        
        # 4. 绘图
        viz.plot_chart(df, bi_structure, buys,sells)
    else:
        print("数据库中无数据，请先运行数据获取脚本。")