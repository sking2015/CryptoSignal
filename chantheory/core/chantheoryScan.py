import pandas as pd
import numpy as np
from hyperliquidDataMgr import MarketDataManager
import pickle
import time

class ChanLunStrategy:
    def __init__(self, data_manager=None):
        self.data_manager = data_manager if data_manager else MarketDataManager()
        self.states = {} 
        self.EXPIRATION_BARS = 60

        # ==============================================================================
        # 🎛️ V35.0 背驰引擎参数 (Divergence Engine)
        # ==============================================================================
        # 1. 背驰判定阈值
        # 后一笔的面积必须小于前一笔的 85% 才算背驰 (0.85)，防止微弱差异导致的误判
        self.DIVERGENCE_FACTOR = 0.85 
        
        # 2. 1买/1卖 的 RSI 辅助 (不再是硬门槛，而是宽松区间)
        # 1买时 RSI 只要不高于 45 即可 (之前是30)，重点看背驰
        self.BUY1_MAX_RSI = 45
        # 1卖时 RSI 只要不低于 55 即可
        self.SELL1_MIN_RSI = 55

        # 3. 结构参数
        self.MIN_K_IN_BI = 4       
        self.BI_LOOKBACK = 3       
        # ==============================================================================

    # ---------------------------------------------------------
    # 1. 基础处理：包含合并
    # ---------------------------------------------------------
    def preprocess_klines(self, df):
        if df is None or len(df) < 50: return []
        bars = []
        for _, row in df.iterrows():
            bars.append({
                'ts': row['timestamp'], 'h': row['high'], 'l': row['low'], 
                'o': row['open'], 'c': row['close'], 'v': row['volume'],
                'macd': row.get('macd', 0), 'diff': row.get('diff', 0), 
                'dea': row.get('dea', 0), 'rsi': row.get('rsi', 50),
                'ema12': row.get('ema12', 0)
            })
        merged_bars = []
        if not bars: return []
        merged_bars.append(bars[0])
        direction_up = True 
        for i in range(1, len(bars)):
            curr = bars[i]
            prev = merged_bars[-1]
            is_included = (curr['h'] <= prev['h'] and curr['l'] >= prev['l']) or \
                          (curr['h'] >= prev['h'] and curr['l'] <= prev['l'])
            if is_included:
                if direction_up:
                    prev['h'] = max(curr['h'], prev['h']); prev['l'] = max(curr['l'], prev['l'])
                else:
                    prev['h'] = min(curr['h'], prev['h']); prev['l'] = min(curr['l'], prev['l'])
                prev['c'] = curr['c']; prev['v'] += curr['v']; prev['end_ts'] = curr['ts']
                # 累加动能：合并K线时，把包含的 MACD 值取绝对值累加，作为该K线的能量
                # 注意：这里简化处理，只取最新的指标，面积在 find_bi 计算
                prev['macd'] = curr['macd']; prev['diff'] = curr['diff']; prev['rsi'] = curr['rsi']
                prev['ema12'] = curr['ema12']
            else:
                if curr['h'] > prev['h'] and curr['l'] > prev['l']: direction_up = True
                elif curr['h'] < prev['h'] and curr['l'] < prev['l']: direction_up = False
                curr['end_ts'] = curr['ts']
                merged_bars.append(curr)
        return merged_bars

    # ---------------------------------------------------------
    # 2. 找笔 (Bi) + 计算力度 (MACD Area)
    # ---------------------------------------------------------
    def find_bi(self, merged_bars):
        if len(merged_bars) < self.MIN_K_IN_BI + 1: return []
        fx_list = []
        for i in range(1, len(merged_bars)-1):
            prev, curr, next_b = merged_bars[i-1], merged_bars[i], merged_bars[i+1]
            if curr['h'] > prev['h'] and curr['h'] > next_b['h']:
                fx_list.append({'type': 'top', 'idx': i, 'val': curr['h'], 'bar': curr})
            elif curr['l'] < prev['l'] and curr['l'] < next_b['l']:
                fx_list.append({'type': 'bot', 'idx': i, 'val': curr['l'], 'bar': curr})
        
        bi_list = []
        if not fx_list: return []
        curr_fx = fx_list[0]
        
        for i in range(1, len(fx_list)):
            next_fx = fx_list[i]
            if curr_fx['type'] == next_fx['type']:
                if curr_fx['type'] == 'top':
                    if next_fx['val'] > curr_fx['val']: curr_fx = next_fx
                else:
                    if next_fx['val'] < curr_fx['val']: curr_fx = next_fx
                continue
            
            if next_fx['idx'] - curr_fx['idx'] >= (self.MIN_K_IN_BI - 1):
                # === 🚨 计算本笔的 MACD 面积 (力度) ===
                # 遍历 merged_bars 从 start_idx 到 end_idx
                # 注意：这里我们遍历合并后的K线，虽然不是最精确的原始tick，但足够反应力度
                macd_area = 0
                for k in range(curr_fx['idx'], next_fx['idx'] + 1):
                    # 取绝对值累加
                    macd_area += abs(merged_bars[k]['macd'])
                
                bi_list.append({
                    'start_idx': curr_fx['idx'], 'end_idx': next_fx['idx'],
                    'start_val': curr_fx['val'], 'end_val': next_fx['val'],
                    'type': 1 if curr_fx['type'] == 'bot' else -1, 
                    'start_ts': curr_fx['bar']['ts'], 'end_ts': next_fx['bar']['end_ts'],
                    'macd_area': macd_area # 核心新增字段
                })
                curr_fx = next_fx
        return bi_list

    # ---------------------------------------------------------
    # 3. 计算中枢
    # ---------------------------------------------------------
    def get_zhongshu(self, bi_list):
        if len(bi_list) < self.BI_LOOKBACK: return None
        segments = bi_list[-self.BI_LOOKBACK:] 
        min_high = min([max(b['start_val'], b['end_val']) for b in segments]) 
        max_low = max([min(b['start_val'], b['end_val']) for b in segments]) 
        if min_high > max_low: 
            return {'zg': min_high, 'zd': max_low}
        return None

    def calculate_indicators(self, df):
        if df is None or len(df) < 100: return None
        df = df.copy()
        df['ma5'] = df['close'].rolling(window=5).mean()
        df['ma20'] = df['close'].rolling(window=20).mean() 
        df['ma60'] = df['close'].rolling(window=60).mean() 
        df['ema12'] = df['close'].ewm(span=12, adjust=False).mean()
        df['ema26'] = df['close'].ewm(span=26, adjust=False).mean()
        df['diff'] = df['ema12'] - df['ema26']
        df['dea'] = df['diff'].ewm(span=9, adjust=False).mean()
        df['macd'] = 2 * (df['diff'] - df['dea'])
        
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        df['slope'] = (df['ma20'] - df['ma20'].shift(3)) / df['ma20'].shift(3) * 100
        return df

    # ---------------------------------------------------------
    # 4. 核心分析逻辑 V35 (Divergence Restoration)
    # ---------------------------------------------------------
    def analyze_snapshot(self, symbol, main_lvl, df_main, df_sub):
        if df_main is None or len(df_main) < 100: return None
        
        curr = df_main.iloc[-1]
        prev = df_main.iloc[-2]
        price = curr['close']
        
        merged_bars = self.preprocess_klines(df_main)
        bi_list = self.find_bi(merged_bars)
        
        if len(bi_list) < 5: return None
        
        last_bi = bi_list[-1] 
        prev_bi = bi_list[-2]
        compare_bi = bi_list[-3] # 用于比较力度的前一笔（同向）

        zs = self.get_zhongshu(bi_list) 
        
        # 辅助变量
        last_low = min(last_bi['start_val'], last_bi['end_val'])
        dist_from_low_pct = (price - last_low) / last_low
        is_chasing_high = dist_from_low_pct > 0.015

        # ========================================================
        # 🟢 1买 (1B) - 趋势背驰买点 (Trend Divergence)
        # 逻辑：价格创新低 + MACD面积减小 + K线反转
        # ========================================================
        if last_bi['type'] == -1: # 当前是向下笔
            # 1. 价格创新低 (对比前一个向下笔)
            if last_bi['end_val'] < compare_bi['end_val']:
                
                # 2. 力度背驰 (MACD Area)
                # 当前笔的力度 < 前一笔力度 * 0.85
                if last_bi['macd_area'] < compare_bi['macd_area'] * self.DIVERGENCE_FACTOR:
                    
                    # 3. 辅助过滤
                    # RSI 不要在高位 (比如不要 > 45)
                    # 且当前K线出现底分型/反转 (阳包阴/刺透)
                    if curr['rsi'] < self.BUY1_MAX_RSI:
                         is_reversal_k = curr['close'] > curr['open'] and curr['close'] > prev['close']
                         
                         if is_reversal_k:
                             return {"type": "1B", "action": "buy", "price": price, 
                                    "desc": f"一买(趋势背驰) 力度:{last_bi['macd_area']:.0f}/{compare_bi['macd_area']:.0f}", 
                                    "stop_loss": last_bi['end_val']}

        # ========================================================
        # 🔴 1卖 (1S) - 趋势背驰卖点
        # 逻辑：价格创新高 + MACD面积减小 + K线反转
        # ========================================================
        if last_bi['type'] == 1: # 当前是向上笔
            # 1. 价格创新高
            if last_bi['end_val'] > compare_bi['end_val']:
                
                # 2. 力度背驰
                if last_bi['macd_area'] < compare_bi['macd_area'] * self.DIVERGENCE_FACTOR:
                    
                    # 3. 辅助过滤
                    if curr['rsi'] > self.SELL1_MIN_RSI: # RSI > 55
                         is_reversal_k = curr['close'] < curr['open'] and curr['close'] < prev['close']
                         
                         if is_reversal_k:
                             return {"type": "1S", "action": "sell", "price": price, 
                                    "desc": f"一卖(顶背驰) 力度:{last_bi['macd_area']:.0f}/{compare_bi['macd_area']:.0f}", 
                                    "stop_loss": last_bi['end_val']}

        # ========================================================
        # 🟢 2买 (2B) - 保持 V34 的稳健逻辑
        # ========================================================
        if last_bi['type'] == -1: 
            if last_bi['end_val'] > compare_bi['end_val']: # 不创新低
                if not is_chasing_high:
                    if curr['rsi'] > prev['rsi'] and curr['close'] > curr['open']:
                         return {"type": "2B", "action": "buy", "price": price, 
                                "desc": f"二买(结构确认) 离底{dist_from_low_pct*100:.2f}%", "stop_loss": last_bi['end_val']}

        # ========================================================
        # 🔴 3卖 (3S) & TrendS - 保持 V34 的精确打击逻辑
        # ========================================================
        if zs and last_bi['type'] == -1: 
            if last_bi['end_val'] < zs['zd']: 
                if curr['rsi'] > 30 and price < zs['zd']:
                    if price < curr['ma20'] and curr['close'] < curr['open']:
                         return {"type": "3S", "action": "sell", "price": price, 
                                "desc": f"三卖(确认跌势) 阻力:{zs['zd']:.2f}", "stop_loss": zs['zd']}

        # TrendS (反抽被拒)
        if curr['slope'] < -0.1 and price < curr['ma20'] and curr['rsi'] > 35:
             resistance_line = curr['ema12']
             touched_resistance = curr['high'] >= resistance_line * 0.999 
             rejection_confirmed = curr['close'] < resistance_line
             is_weak_candle = (curr['close'] < curr['open']) and (curr['close'] < prev['close'])
             
             if touched_resistance and rejection_confirmed and is_weak_candle:
                  return {"type": "TrendS", "action": "sell", "price": price, 
                          "desc": "顺势空(反抽EMA12被拒)", "stop_loss": curr['high']}

        # 3B (三买)
        if zs and last_bi['type'] == -1:
             if last_bi['end_val'] > zs['zg']:
                 if abs(price - curr['ma20']) / price < 0.01:
                     return {"type": "3B", "action": "buy", "price": price, 
                            "desc": "三买(均线回踩)", "stop_loss": zs['zg']}

        return None

    def detect_signals(self, symbol, main_lvl='30m', sub_lvl='5m'):
        limit = 1000
        self.data_manager.update_data(symbol, main_lvl)
        df_main = self.data_manager.load_data_for_analysis(symbol, main_lvl, limit=limit)
        df_main = self.calculate_indicators(df_main)
        signal = self.analyze_snapshot(symbol, main_lvl, df_main, None)
        if signal:
            return self.print_signal(symbol, signal['desc'], main_lvl, sub_lvl, 
                                   signal['price'], signal['stop_loss'], is_buy=(signal['action']=='buy'))
        return ""

    def print_signal(self, symbol, type_name, main, sub, price, stop_loss, is_buy=True):
        emoji = "🚀" if is_buy else "🌊" 
        action = "做多" if is_buy else "做空"
        mess = f"{emoji} [缠论-{action}] {symbol} ({main}) | {type_name}\n   现价: {price} | 止损: {stop_loss:.4f}\n"
        print(mess)
        return mess