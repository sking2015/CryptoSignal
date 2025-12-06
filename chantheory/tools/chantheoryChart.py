import pandas as pd
import numpy as np
import mplfinance as mpf
import sqlite3
import warnings

# 忽略警告
warnings.filterwarnings('ignore')

class ChanLunVisualizer:
    def __init__(self, db_path='hyperliquid_data.db'):
        self.db_path = db_path

    def load_data(self, symbol, interval, limit=200):
        """读取数据并计算MACD"""
        try:
            conn = sqlite3.connect(self.db_path)
            # 读取多一点数据用于EMA计算
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
            
            # MACD计算
            exp12 = df['close'].ewm(span=12, adjust=False).mean()
            exp26 = df['close'].ewm(span=26, adjust=False).mean()
            df['diff'] = exp12 - exp26
            df['dea'] = df['diff'].ewm(span=9, adjust=False).mean()
            df['macd'] = (df['diff'] - df['dea']) * 2
            
            # 严格保持 limit=200 以复现你的买卖点结果
            return df.tail(limit)
        except Exception as e:
            print(f"数据读取错误: {e}")
            return None

    def find_fractals(self, df):
        """识别分型"""
        df = df.copy()
        df['fractal'] = 0 
        highs = df['high'].values
        lows = df['low'].values
        
        for i in range(2, len(df) - 2):
            if (highs[i] > highs[i-1] and highs[i] > highs[i+1] and
                highs[i] > highs[i-2] and highs[i] > highs[i+2]):
                df.iloc[i, df.columns.get_loc('fractal')] = 1
            elif (lows[i] < lows[i-1] and lows[i] < lows[i+1] and 
                  lows[i] < lows[i-2] and lows[i] < lows[i+2]):
                df.iloc[i, df.columns.get_loc('fractal')] = -1
        return df

    def construct_bi(self, df):
        """构造笔 (Bi)"""
        bi_points = [] 
        last_type = 0 
        fractals = df[df['fractal'] != 0]
        
        for index, row in fractals.iterrows():
            curr_type = row['fractal']
            if last_type == 0:
                if curr_type == 1: point = (index, row['high'])
                else: point = (index, row['low'])
                bi_points.append(point)
                last_type = curr_type
                continue
            
            if curr_type == 1 and last_type == -1: # 底->顶
                if len(df.loc[bi_points[-1][0]:index]) > 3: 
                    bi_points.append((index, row['high']))
                    last_type = 1
                else:
                    if row['high'] > bi_points[-1][1]: 
                        bi_points.pop()
                        bi_points.append((index, row['high']))
            elif curr_type == -1 and last_type == 1: # 顶->底
                if len(df.loc[bi_points[-1][0]:index]) > 3:
                    bi_points.append((index, row['low']))
                    last_type = -1
                else:
                    if row['low'] < bi_points[-1][1]: 
                        bi_points.pop()
                        bi_points.append((index, row['low']))
        return bi_points

    # ==========================================
    # 核心修正：线段生长与破坏算法
    # ==========================================
    def construct_segments(self, bi_points):
        """
        构造线段：基于特征序列的破坏逻辑
        """
        if not bi_points or len(bi_points) < 4: 
            return []
        
        # 初始化
        seg_points = [bi_points[0]]
        
        # 确定初始方向：由前两笔决定
        # direction: 1 为向上线段, -1 为向下线段
        direction = 1 if bi_points[1][1] > bi_points[0][1] else -1
        
        # 当前待定的极值点（High or Low）
        current_extremum = bi_points[1]
        current_extremum_idx = 1
        
        i = 2
        while i < len(bi_points):
            curr_point = bi_points[i]
            
            if direction == 1: # === 当前是向上线段 ===
                # 1. 也是向上笔的终点（偶数/奇数取决于起始，直接比较价格）
                if curr_point[1] > bi_points[i-1][1]: 
                    # 如果创出新高，线段继续生长，更新极值
                    if curr_point[1] >= current_extremum[1]:
                        current_extremum = curr_point
                        current_extremum_idx = i
                
                # 2. 检查线段破坏（需要看是否有顶分型结构）
                # 我们需要从 current_extremum_idx 开始往后看三笔：下-上-下
                # 至少要有3笔才能形成破坏结构
                if i > current_extremum_idx + 2:
                    # 获取极值后的关键点
                    # P_peak (extremum) -> P1(下) -> P2(上) -> P3(下)
                    # 对应索引: current_extremum_idx, +1, +2, +3
                    # 注意：i 必须遍历到 P3 才能确认破坏
                    
                    p1 = bi_points[current_extremum_idx + 1] # 下
                    p2 = bi_points[current_extremum_idx + 2] # 上
                    p3 = bi_points[current_extremum_idx + 3] if current_extremum_idx + 3 < len(bi_points) else None
                    
                    if p3:
                        # 破坏条件：
                        # 1. 反弹不过高 (P2 < Peak) - 笔的定义保证了这点
                        # 2. 跌破前低 (P3 < P1) 
                        # 3. 简单的特征序列顶分型
                        if p3[1] < p1[1] and p2[1] < current_extremum[1]:
                            # 确认线段结束于 current_extremum
                            seg_points.append(current_extremum)
                            
                            # 状态反转
                            direction = -1
                            # 新的起始点是 current_extremum，新的待定极值是 P1
                            # 但为了循环继续，我们将索引 i 重置到 P1 的位置继续寻找底
                            # 实际上 P3 是新线段的一个潜在低点
                            current_extremum = p3 # 暂时假设 P3 是最低
                            current_extremum_idx = current_extremum_idx + 3
                            i = current_extremum_idx
                            continue

            elif direction == -1: # === 当前是向下线段 ===
                # 1. 向下笔的终点
                if curr_point[1] < bi_points[i-1][1]:
                    # 创新低，更新极值
                    if curr_point[1] <= current_extremum[1]:
                        current_extremum = curr_point
                        current_extremum_idx = i
                
                # 2. 检查破坏：上-下-上
                if i > current_extremum_idx + 2:
                    p1 = bi_points[current_extremum_idx + 1] # 上
                    p2 = bi_points[current_extremum_idx + 2] # 下
                    p3 = bi_points[current_extremum_idx + 3] if current_extremum_idx + 3 < len(bi_points) else None
                    
                    if p3:
                        # 破坏条件：
                        # 1. 回调不破低 (P2 > Peak)
                        # 2. 升破前高 (P3 > P1)
                        if p3[1] > p1[1] and p2[1] > current_extremum[1]:
                            seg_points.append(current_extremum)
                            direction = 1
                            current_extremum = p3
                            current_extremum_idx = current_extremum_idx + 3
                            i = current_extremum_idx
                            continue
            
            i += 1
            
        # 将最后一个待定的极值点加入，作为未完成线段的终点
        if current_extremum != seg_points[-1]:
            seg_points.append(current_extremum)
        # 如果最后一个点不是极值点，连接到最新点
        if seg_points[-1] != bi_points[-1]:
            seg_points.append(bi_points[-1])
            
        return seg_points

    def identify_centers(self, bi_points):
        """识别中枢"""
        centers = [] 
        if len(bi_points) < 4: return centers
        i = 0
        while i < len(bi_points) - 3:
            p0, p1, p2, p3 = bi_points[i], bi_points[i+1], bi_points[i+2], bi_points[i+3]
            high1, low1 = max(p0[1], p1[1]), min(p0[1], p1[1])
            high2, low2 = max(p1[1], p2[1]), min(p1[1], p2[1])
            high3, low3 = max(p2[1], p3[1]), min(p2[1], p3[1])
            zg = min(high1, high2, high3)
            zd = max(low1, low2, low3)
            
            if zg > zd: 
                end_idx = i + 3
                extension_end_time = p3[0]
                for k in range(i + 3, len(bi_points) - 1):
                    pk_next = bi_points[k+1]
                    pk_high = max(bi_points[k][1], pk_next[1])
                    pk_low = min(bi_points[k][1], pk_next[1])
                    if pk_low > zg or pk_high < zd: break
                    else:
                        extension_end_time = pk_next[0]
                        end_idx = k
                centers.append({'start_date': p0[0], 'end_date': extension_end_time, 'zg': zg, 'zd': zd})
                i = end_idx 
            else: i += 1
        return centers

    def detect_buy_points(self, df, bi_points):
        """识别买点 (保留原始逻辑)"""
        buy_signals = []
        if len(bi_points) < 4: return buy_signals
        
        for i in range(3, len(bi_points), 2):
            curr_bottom = bi_points[i]   
            prev_top = bi_points[i-1]    
            prev_bottom = bi_points[i-2] 
            prev_top_prev = bi_points[i-3]
            
            if curr_bottom[1] >= prev_top[1]: continue 
            
            if curr_bottom[1] < prev_bottom[1]:
                try:
                    curr_macd = df.loc[prev_top[0]:curr_bottom[0]]['macd'].min()
                    prev_macd = df.loc[prev_top_prev[0]:prev_bottom[0]]['macd'].min()
                    if curr_macd < 0 and curr_macd > prev_macd:
                         buy_signals.append((curr_bottom[0], curr_bottom[1], 'B1'))
                except: pass
            elif curr_bottom[1] > prev_bottom[1]:
                buy_signals.append((curr_bottom[0], curr_bottom[1], 'B2'))
        return buy_signals

    def detect_sell_points(self, df, bi_points):
        """识别卖点 (保留原始逻辑)"""
        sell_signals = [] 
        if len(bi_points) < 4: return sell_signals
        first_ts = bi_points[0][0]
        start_idx = 3 if df.at[first_ts, 'fractal'] == -1 else 4
        
        for i in range(start_idx, len(bi_points), 2):
            curr_top = bi_points[i]      
            prev_top = bi_points[i-2]    
            prev_bottom = bi_points[i-1] 
            prev_bottom_prev = bi_points[i-3] 
            
            if curr_top[1] <= prev_bottom[1]: continue

            if curr_top[1] > prev_top[1]:
                try:
                    curr_macd_max = df.loc[prev_bottom[0]:curr_top[0]]['macd'].max()
                    prev_macd_max = df.loc[prev_bottom_prev[0]:prev_top[0]]['macd'].max()
                    if curr_macd_max > 0 and curr_macd_max < prev_macd_max:
                         sell_signals.append((curr_top[0], curr_top[1], 'S1'))
                except: pass
            elif curr_top[1] < prev_top[1]:
                sell_signals.append((curr_top[0], curr_top[1], 'S2'))
        return sell_signals

    def plot_chart(self, df, bi_points, seg_points, centers, buy_signals, sell_signals):
        """绘图"""
        bi_lines = bi_points
        rectangles = []
        for c in centers:
            rect = [(c['start_date'], c['zg']), (c['end_date'], c['zg']),
                    (c['end_date'], c['zd']), (c['start_date'], c['zd']), (c['start_date'], c['zg'])]
            rectangles.append(rect)

        plots = []
        time_map = {t: i for i, t in enumerate(df.index)}
        
        if buy_signals:
            buy_markers = [np.nan] * len(df)
            has_buy = False
            for ts, price, label in buy_signals:
                if ts in time_map:
                    buy_markers[time_map[ts]] = price * 0.99
                    has_buy = True
            if has_buy:
                plots.append(mpf.make_addplot(buy_markers, type='scatter', markersize=80, marker='^', color='m'))

        if sell_signals:
            sell_markers = [np.nan] * len(df)
            has_sell = False
            for ts, price, label in sell_signals:
                if ts in time_map:
                    sell_markers[time_map[ts]] = price * 1.01
                    has_sell = True
            if has_sell:
                plots.append(mpf.make_addplot(sell_markers, type='scatter', markersize=80, marker='v', color='g'))

        s = mpf.make_mpf_style(base_mpf_style='charles', gridstyle=':', y_on_right=True)
        print(f"统计: {len(bi_points)-1} 笔, {len(centers)} 中枢, 买点: {len(buy_signals)}, 卖点: {len(sell_signals)}")
        
        # 将线段数据打印出来以便调试
        print(f"识别线段节点数: {len(seg_points)}")

        all_lines = rectangles + [bi_lines]
        colors = ['yellow'] * len(rectangles) + ['red']
        linewidths = [1.5] * len(rectangles) + [1.0]

        if seg_points and len(seg_points) > 1:
             all_lines.append(seg_points)
             colors.append('blue') # 线段用蓝色显示
             linewidths.append(2.5) # 线段更粗

        mpf.plot(df, type='candle', style=s, 
                 addplot=plots if plots else None,
                 alines=dict(alines=all_lines, colors=colors, linewidths=linewidths, alpha=0.8),
                 volume=True, figratio=(14, 8), title="ChanLun Structure", panel_ratios=(4, 1),
                 warn_too_much_data=10000)

if __name__ == "__main__":
    viz = ChanLunVisualizer()
    symbol = 'BTC'
    df = viz.load_data(symbol, '30m', limit=200) # 保持200
    
    if df is not None:
        df = viz.find_fractals(df)
        bi_points = viz.construct_bi(df)
        seg_points = viz.construct_segments(bi_points) 
        centers = viz.identify_centers(bi_points)
        buys = viz.detect_buy_points(df, bi_points)
        sells = viz.detect_sell_points(df, bi_points)
        viz.plot_chart(df, bi_points, seg_points, centers, buys, sells)
    else:
        print("无数据。")