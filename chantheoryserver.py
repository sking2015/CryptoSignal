from flask import Flask, request, jsonify
from flask_cors import CORS
import pandas as pd
import numpy as np
import sqlite3

app = Flask(__name__)
CORS(app)  # 允许跨域请求，这样你的 HTML 文件可以直接访问 API

# ==========================================
# 缠论核心计算类 (复用之前的逻辑，去除了绘图)
# ==========================================
class ChanLunProcessor:
    def __init__(self, db_path='hyperliquid_data.db'):
        self.db_path = db_path

    def process(self, symbol, interval, limit=1000):
        # 1. 读取数据
        df = self.load_data(symbol, interval, limit)
        if df is None: return None

        # 2. 计算缠论结构
        df = self.find_fractals(df)
        bi_points = self.construct_bi(df)
        seg_points = self.construct_segments(bi_points)
        centers = self.identify_centers(bi_points)
        buys = self.detect_buy_points(df, bi_points)
        sells = self.detect_sell_points(df, bi_points)

        # 3. 格式化数据为前端 ECharts 易读的格式
        result = self.format_for_frontend(df, bi_points, seg_points, centers, buys, sells)
        return result

    def load_data(self, symbol, interval, limit):
        try:
            conn = sqlite3.connect(self.db_path)
            # 读取更多数据以保证指标计算准确，最后裁切
            read_limit = limit + 200 
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
            
            # MACD 计算
            exp12 = df['close'].ewm(span=12, adjust=False).mean()
            exp26 = df['close'].ewm(span=26, adjust=False).mean()
            df['diff'] = exp12 - exp26
            df['dea'] = df['diff'].ewm(span=9, adjust=False).mean()
            df['macd'] = (df['diff'] - df['dea']) * 2
            
            return df.tail(limit)
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

    def construct_bi(self, df):
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
            if curr_type == 1 and last_type == -1: 
                if len(df.loc[bi_points[-1][0]:index]) > 3: 
                    bi_points.append((index, row['high']))
                    last_type = 1
                else:
                    if row['high'] > bi_points[-1][1]: 
                        bi_points.pop()
                        bi_points.append((index, row['high']))
            elif curr_type == -1 and last_type == 1: 
                if len(df.loc[bi_points[-1][0]:index]) > 3:
                    bi_points.append((index, row['low']))
                    last_type = -1
                else:
                    if row['low'] < bi_points[-1][1]: 
                        bi_points.pop()
                        bi_points.append((index, row['low']))
        return bi_points

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
                    p1, p2 = bi_points[current_extremum_idx + 1], bi_points[current_extremum_idx + 2]
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
                    p1, p2 = bi_points[current_extremum_idx + 1], bi_points[current_extremum_idx + 2]
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

    def detect_buy_points(self, df, bi_points):
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

    def format_for_frontend(self, df, bi, seg, centers, buys, sells):
        """将数据转换为 JSON 友好的格式"""
        
        # 转换时间索引为字符串列表
        dates = df.index.strftime('%Y-%m-%d %H:%M').tolist()
        
        # ECharts Candle 格式: [Open, Close, Low, High]
        # 注意：pandas 是 Open, High, Low, Close
        ohlc = df[['open', 'close', 'low', 'high']].values.tolist()
        
        volumes = df['volume'].tolist()
        
        # MACD 数据
        macd_data = {
            'diff': df['diff'].fillna(0).tolist(),
            'dea': df['dea'].fillna(0).tolist(),
            'bar': df['macd'].fillna(0).tolist()
        }
        
        # 辅助函数：转换 (Timestamp, Price) -> [TimeStr, Price]
        def fmt_points(points):
            return [[p[0].strftime('%Y-%m-%d %H:%M'), p[1]] for p in points]
        
        def fmt_signals(signals):
            # [TimeStr, Price, Type]
            return [[s[0].strftime('%Y-%m-%d %H:%M'), s[1], s[2]] for s in signals]

        def fmt_centers(centers):
            # [StartTimeStr, EndTimeStr, ZG, ZD]
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

# ==========================================
# Flask 路由
# ==========================================
processor = ChanLunProcessor()

@app.route('/api/data', methods=['GET'])
def get_data():
    symbol = request.args.get('symbol', 'BTC')
    interval = request.args.get('interval', '30m')
    
    # 默认只取最近 500 条用于前端展示，避免浏览器卡顿
    # 后端实际读取会稍微多一点用于计算
    data = processor.process(symbol, interval, limit=500)
    
    if data:
        return jsonify({'status': 'success', 'data': data})
    else:
        return jsonify({'status': 'error', 'message': 'No data found'}), 404

if __name__ == '__main__':
    # 启动服务，端口 5000
    print("Starting Flask server at http://localhost:5000")
    app.run(debug=True, port=5000)