from flask import Flask, request, jsonify
from flask_cors import CORS
import pandas as pd
import numpy as np
import sqlite3

app = Flask(__name__)
CORS(app)

class ChanLunProcessor:
    def __init__(self, db_path='hyperliquid_data.db'):
        self.db_path = db_path
        # 预读取缓冲区，保证指标计算准确
        self.MACD_CALC_BUFFER = 5000 

    def process(self, symbol, interval, output_limit=2000):
        # 1. 读取全量数据计算 MACD (读取 5000 条，保证 MACD 准确)
        df_full = self.load_data_and_calc(symbol, interval, self.MACD_CALC_BUFFER)
        if df_full is None: return None

        # 2. 切片：模拟本地脚本的"视野"
        # 只截取前端需要的 output_limit (比如 2000 条)
        # 这样 bi/seg 的生成起点就是这 2000 条的开头，与本地脚本逻辑一致
        real_limit = min(output_limit, len(df_full))
        df_display = df_full.tail(real_limit).copy()

        # 3. 计算结构
        df_display = self.find_fractals(df_display)
        
        # 【关键】bi_points 现在包含类型信息: (Time, Price, Type)
        bi_points = self.construct_bi(df_display)
        
        # 线段生成 (使用之前优化的生长算法)
        seg_points = self.construct_segments(bi_points)
        
        centers = self.identify_centers(bi_points)
        
        # 检测买卖点 (逻辑已更新，支持类型检查)
        buys = self.detect_buy_points(df_display, bi_points)
        sells = self.detect_sell_points(df_display, bi_points)

        return self.format_for_frontend(
            df_display, bi_points, seg_points, centers, buys, sells
        )

    def load_data_and_calc(self, symbol, interval, limit):
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
            
            # 截取最后的 limit 条
            df = df.tail(limit)
            
            if len(df) < 50: return None 

            exp12 = df['close'].ewm(span=12, adjust=False).mean()
            exp26 = df['close'].ewm(span=26, adjust=False).mean()
            df['diff'] = exp12 - exp26
            df['dea'] = df['diff'].ewm(span=9, adjust=False).mean()
            df['macd'] = (df['diff'] - df['dea']) * 2
            
            return df
        except Exception as e:
            print(f"DB Error: {e}")
            return None

    def find_fractals(self, df):
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

    # ==========================================
    # 构造笔：携带身份信息 (1=顶, -1=底)
    # ==========================================
    def construct_bi(self, df):
        bi_points = [] 
        last_type = 0 
        fractals = df[df['fractal'] != 0]
        
        for index, row in fractals.iterrows():
            curr_type = row['fractal']
            
            # 初始化第一个点
            if last_type == 0:
                if curr_type == 1: 
                    # (Time, Price, Type)
                    point = (index, row['high'], 1) 
                else: 
                    point = (index, row['low'], -1)
                bi_points.append(point)
                last_type = curr_type
                continue
            
            # 底 -> 顶
            if curr_type == 1 and last_type == -1: 
                if len(df.loc[bi_points[-1][0]:index]) > 3: 
                    bi_points.append((index, row['high'], 1)) # 标记为顶(1)
                    last_type = 1
                else:
                    # 更新低点 (底还是底，类型不变)
                    if row['high'] > bi_points[-1][1]: 
                        bi_points.pop()
                        bi_points.append((index, row['high'], 1))

            # 顶 -> 底
            elif curr_type == -1 and last_type == 1: 
                if len(df.loc[bi_points[-1][0]:index]) > 3:
                    bi_points.append((index, row['low'], -1)) # 标记为底(-1)
                    last_type = -1
                else:
                    # 更新高点 (顶还是顶，类型不变)
                    if row['low'] < bi_points[-1][1]: 
                        bi_points.pop()
                        bi_points.append((index, row['low'], -1))
        return bi_points

    # 线段算法 (兼容三元素元组)
    def construct_segments(self, bi_points):
        if not bi_points or len(bi_points) < 4: return []
        seg_points = [bi_points[0]]
        direction = 1 if bi_points[1][1] > bi_points[0][1] else -1
        current_extremum = bi_points[1]
        current_extremum_idx = 1
        i = 2
        while i < len(bi_points):
            curr_point = bi_points[i]
            if direction == 1:
                if curr_point[1] > bi_points[i-1][1]: 
                    if curr_point[1] >= current_extremum[1]:
                        current_extremum = curr_point
                        current_extremum_idx = i
                if i > current_extremum_idx + 2:
                    p1 = bi_points[current_extremum_idx + 1]
                    p2 = bi_points[current_extremum_idx + 2]
                    p3 = bi_points[current_extremum_idx + 3] if current_extremum_idx + 3 < len(bi_points) else None
                    if p3 and p3[1] < p1[1] and p2[1] < current_extremum[1]:
                        seg_points.append(current_extremum)
                        direction = -1
                        current_extremum = p3
                        current_extremum_idx = current_extremum_idx + 3
                        i = current_extremum_idx
                        continue
            elif direction == -1:
                if curr_point[1] < bi_points[i-1][1]:
                    if curr_point[1] <= current_extremum[1]:
                        current_extremum = curr_point
                        current_extremum_idx = i
                if i > current_extremum_idx + 2:
                    p1 = bi_points[current_extremum_idx + 1]
                    p2 = bi_points[current_extremum_idx + 2]
                    p3 = bi_points[current_extremum_idx + 3] if current_extremum_idx + 3 < len(bi_points) else None
                    if p3 and p3[1] > p1[1] and p2[1] > current_extremum[1]:
                        seg_points.append(current_extremum)
                        direction = 1
                        current_extremum = p3
                        current_extremum_idx = current_extremum_idx + 3
                        i = current_extremum_idx
                        continue
            i += 1
        if current_extremum != seg_points[-1]: seg_points.append(current_extremum)
        if seg_points[-1] != bi_points[-1]: seg_points.append(bi_points[-1])
        return seg_points

    def identify_centers(self, bi_points):
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

    # ==========================================
    # 买卖点检测：强制检查类型，杜绝底标卖
    # ==========================================
    def detect_buy_points(self, df, bi_points):
        buy_signals = []
        if len(bi_points) < 4: return buy_signals
        
        # 遍历所有点
        for i in range(2, len(bi_points)):
            curr_node = bi_points[i]    # (Time, Price, Type)
            
            # 【终极防守】：如果不是底 (-1)，跳过！
            if curr_node[2] != -1: 
                continue
                
            prev_top = bi_points[i-1]
            prev_bottom = bi_points[i-2]
            
            # 基础结构防守：底必须比前一个顶低
            if curr_node[1] >= prev_top[1]: continue
            
            # 1. 一买 (B1)
            if curr_node[1] < prev_bottom[1]:
                if i >= 3:
                    prev_top_prev = bi_points[i-3]
                    try:
                        curr_macd = df.loc[prev_top[0]:curr_node[0]]['macd'].sum()
                        prev_macd = df.loc[prev_top_prev[0]:prev_bottom[0]]['macd'].sum()
                        if curr_macd < 0 and curr_macd > prev_macd:
                             buy_signals.append((curr_node[0], curr_node[1], 'B1'))
                    except: pass
            
            # 2. 二买 (B2)
            elif curr_node[1] > prev_bottom[1]:
                buy_signals.append((curr_node[0], curr_node[1], 'B2'))

        return buy_signals

    def detect_sell_points(self, df, bi_points):
        sell_signals = [] 
        if len(bi_points) < 4: return sell_signals
        
        for i in range(2, len(bi_points)):
            curr_node = bi_points[i] # (Time, Price, Type)
            
            # 【终极防守】：如果不是顶 (1)，跳过！
            if curr_node[2] != 1:
                continue
                
            prev_bottom = bi_points[i-1]
            prev_top = bi_points[i-2]
            
            # 基础结构防守：顶必须比前一个底高
            if curr_node[1] <= prev_bottom[1]: continue

            # 1. 一卖 (S1)
            if curr_node[1] > prev_top[1]:
                if i >= 3:
                    prev_bottom_prev = bi_points[i-3]
                    try:
                        curr_macd_max = df.loc[prev_bottom[0]:curr_node[0]]['macd'].sum()
                        prev_macd_max = df.loc[prev_bottom_prev[0]:prev_top[0]]['macd'].sum()
                        if curr_macd_max > 0 and curr_macd_max < prev_macd_max:
                             sell_signals.append((curr_node[0], curr_node[1], 'S1'))
                    except: pass
            
            # 2. 二卖 (S2)
            elif curr_node[1] < prev_top[1]:
                sell_signals.append((curr_node[0], curr_node[1], 'S2'))
                
        return sell_signals

    def format_for_frontend(self, df, bi, seg, centers, buys, sells):
        dates = df.index.strftime('%Y-%m-%d %H:%M').tolist()
        ohlc = df[['open', 'close', 'low', 'high']].values.tolist()
        volumes = df['volume'].tolist()
        macd_data = {
            'diff': df['diff'].fillna(0).tolist(),
            'dea': df['dea'].fillna(0).tolist(),
            'bar': df['macd'].fillna(0).tolist()
        }
        
        # 前端不需要 Type 字段，只取前两个元素 [Time, Price]
        def fmt_points(points):
            return [[p[0].strftime('%Y-%m-%d %H:%M'), p[1]] for p in points]
        
        def fmt_signals(signals):
            return [[s[0].strftime('%Y-%m-%d %H:%M'), s[1], s[2]] for s in signals]

        def fmt_centers(centers):
            return [[c['start_date'].strftime('%Y-%m-%d %H:%M'), 
                     c['end_date'].strftime('%Y-%m-%d %H:%M'), 
                     c['zg'], c['zd']] for c in centers]

        return {
            'dates': dates,
            'ohlc': ohlc,
            'volume': volumes,
            'macd': macd_data,
            'bi': fmt_points(bi),
            'segments': fmt_points(seg),
            'centers': fmt_centers(centers),
            'buys': fmt_signals(buys),
            'sells': fmt_signals(sells)
        }

processor = ChanLunProcessor()

@app.route('/api/data', methods=['GET'])
def get_data():
    symbol = request.args.get('symbol', 'BTC')
    interval = request.args.get('interval', '30m')
    limit = int(request.args.get('limit', 2000))
    # 修复：参数名统一为 output_limit
    data = processor.process(symbol, interval, output_limit=limit)
    if data:
        return jsonify({'status': 'success', 'data': data})
    else:
        return jsonify({'status': 'error', 'message': 'No data found'}), 404

if __name__ == '__main__':
    print("Starting Flask server at http://localhost:5000")
    app.run(debug=True, port=5000)