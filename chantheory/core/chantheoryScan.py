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
        # 🎛️ V37.0 量化融合参数 (Quant Fusion)
        # ==============================================================================
        # 1. 波动率突破参数 (用于抓瀑布/暴涨)
        self.BOLL_WINDOW = 20      # 布林带周期
        self.BOLL_STD = 2.0        # 布林带宽度
        self.VOL_MULTIPLIER = 1.5  # 放量标准：当前量 > 平均量 * 1.5
        
        # 2. 缠论基础参数
        self.DIVERGENCE_FACTOR = 0.85 
        self.BUY1_MAX_RSI = 45
        self.MIN_K_IN_BI = 4       
        self.BI_LOOKBACK = 3       
        # ==============================================================================

    # ---------------------------------------------------------
    # 1. 基础处理：K线包含合并
    # ---------------------------------------------------------
    def preprocess_klines(self, df):
        if df is None or len(df) < 5: return []
        
        bars = []
        for row in df.itertuples():
            bars.append({
                'ts': row.timestamp, 
                'h': row.high, 'l': row.low, 'o': row.open, 'c': row.close, 'v': row.volume,
                'macd': getattr(row, 'macd', 0), 
                'rsi': getattr(row, 'rsi', 50),
                'upper': getattr(row, 'upper', 0), # 布林上轨
                'lower': getattr(row, 'lower', 0), # 布林下轨
                'vol_ma': getattr(row, 'vol_ma', 0) # 成交量均线
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
                # 继承指标
                prev['macd'] = curr['macd']; prev['rsi'] = curr['rsi']
                prev['upper'] = curr['upper']; prev['lower'] = curr['lower']; prev['vol_ma'] = curr['vol_ma']
            else:
                if curr['h'] > prev['h'] and curr['l'] > prev['l']: direction_up = True
                elif curr['h'] < prev['h'] and curr['l'] < prev['l']: direction_up = False
                curr['end_ts'] = curr['ts']
                merged_bars.append(curr)
        return merged_bars

    # ---------------------------------------------------------
    # 2. 找笔 (Bi)
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
                macd_area = 0
                for k in range(curr_fx['idx'], next_fx['idx'] + 1):
                    macd_area += abs(merged_bars[k]['macd'])
                
                bi_list.append({
                    'start_idx': curr_fx['idx'], 'end_idx': next_fx['idx'],
                    'start_val': curr_fx['val'], 'end_val': next_fx['val'],
                    'type': 1 if curr_fx['type'] == 'bot' else -1, 
                    'start_ts': curr_fx['bar']['ts'], 'end_ts': next_fx['bar']['end_ts'],
                    'macd_area': macd_area 
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

    # ---------------------------------------------------------
    # 4. 指标计算 (引入布林带与成交量)
    # ---------------------------------------------------------
    def calculate_indicators(self, df):
        if df is None or len(df) < 100: return None
        df = df.copy()
        
        # 基础均线
        df['ma5'] = df['close'].rolling(window=5).mean()
        df['ma20'] = df['close'].rolling(window=20).mean() 
        df['ma60'] = df['close'].rolling(window=60).mean() 
        
        # MACD
        df['ema12'] = df['close'].ewm(span=12, adjust=False).mean()
        df['ema26'] = df['close'].ewm(span=26, adjust=False).mean()
        df['diff'] = df['ema12'] - df['ema26']
        df['dea'] = df['diff'].ewm(span=9, adjust=False).mean()
        df['macd'] = 2 * (df['diff'] - df['dea'])
        
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        # 🔥 新增: 布林带 (Bollinger Bands)
        # 用来捕捉极端行情的突破
        std = df['close'].rolling(window=self.BOLL_WINDOW).std()
        df['upper'] = df['ma20'] + (std * self.BOLL_STD)
        df['lower'] = df['ma20'] - (std * self.BOLL_STD)
        
        # 🔥 新增: 成交量均线
        df['vol_ma'] = df['volume'].rolling(window=20).mean()

        return df

    # ---------------------------------------------------------
    # 5. 核心分析逻辑 V37 (Quant Fusion)
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
        compare_bi = bi_list[-3] 
        
        # ========================================================
        # 🌪️ 1. 波动率突破 (抓瀑布/火箭) - 优先于缠论
        # 逻辑：价格突破布林带轨道 + 成交量放大 = 趋势爆发
        # ========================================================
        
        # 【PanicS 恐慌卖出】(抓瀑布)
        # 条件1: 收盘价跌破布林下轨
        # 条件2: 成交量明显放大 (是20日均量的1.5倍以上)
        # 条件3: 阴线实体较大 (Close < Open)
        if price < curr['lower']:
            if curr['volume'] > curr['vol_ma'] * self.VOL_MULTIPLIER:
                if curr['close'] < curr['open']:
                    # 过滤掉已经是下跌末期的情况 (RSI不要太低)
                    if curr['rsi'] > 20: 
                         return {"type": "PanicS", "action": "sell", "price": price, 
                                "desc": "恐慌抛售(放量跌破下轨)", "stop_loss": curr['high']}

        # 【RocketB 火箭买入】(抓急涨)
        # 条件1: 收盘价突破布林上轨
        # 条件2: 成交量放大
        # 条件3: 阳线实体有力
        if price > curr['upper']:
            if curr['volume'] > curr['vol_ma'] * self.VOL_MULTIPLIER:
                if curr['close'] > curr['open']:
                    # 过滤掉已经是上涨末期的情况 (RSI不要太高)
                    if curr['rsi'] < 80:
                        return {"type": "RocketB", "action": "buy", "price": price, 
                                "desc": "火箭发射(放量突破上轨)", "stop_loss": curr['low']}

        # ========================================================
        # 🧘 2. 缠论结构单 (稳健抓转折)
        # 逻辑：当波动率不大时，依靠结构来做高抛低吸
        # ========================================================

        # 【1B 一买】(底背驰)
        if last_bi['type'] == -1: 
            if last_bi['end_val'] < compare_bi['end_val']:
                if last_bi['macd_area'] < compare_bi['macd_area'] * self.DIVERGENCE_FACTOR:
                    if curr['rsi'] < self.BUY1_MAX_RSI:
                         is_reversal_k = curr['close'] > curr['open'] and curr['close'] > prev['close']
                         if is_reversal_k:
                             return {"type": "1B", "action": "buy", "price": price, 
                                    "desc": f"一买(趋势背驰)", "stop_loss": last_bi['end_val']}

        # 【2B 二买】(回踩确认)
        if last_bi['type'] == -1: 
            if last_bi['end_val'] > compare_bi['end_val']: 
                # 不追高逻辑
                dist_from_low_pct = (price - last_bi['end_val']) / last_bi['end_val']
                if dist_from_low_pct < 0.02: # 稍微放宽一点点
                    if curr['rsi'] > prev['rsi'] and curr['close'] > curr['open']:
                         return {"type": "2B", "action": "buy", "price": price, 
                                "desc": f"二买(结构确认)", "stop_loss": last_bi['end_val']}

        # 【3S 三卖】(反抽无力)
        zs = self.get_zhongshu(bi_list)
        if zs and last_bi['type'] == -1: 
            if last_bi['end_val'] < zs['zd']: 
                if price < zs['zd'] and price < curr['ma20']:
                     if curr['close'] < curr['open']:
                         return {"type": "3S", "action": "sell", "price": price, 
                                "desc": f"三卖(确认跌势)", "stop_loss": zs['zd']}
        
        return None

    def detect_signals(self, symbol, main_lvl='30m', sub_lvl='5m'):
        # 增加容错
        try:
            self.data_manager.update_data(symbol, main_lvl)
            df_main = self.data_manager.load_data_for_analysis(symbol, main_lvl, limit=1000)
            df_main = self.calculate_indicators(df_main)
            signal = self.analyze_snapshot(symbol, main_lvl, df_main, None)
            
            if signal:
                return self.print_signal(symbol, signal['desc'], main_lvl, sub_lvl, 
                                       signal['price'], signal['stop_loss'], is_buy=(signal['action']=='buy'))
        except Exception as e:
            # print(f"Error in detect_signals: {e}")
            pass
        return ""

    def print_signal(self, symbol, type_name, main, sub, price, stop_loss, is_buy=True):
        emoji = "🚀" if is_buy else "🌊" 
        action = "做多" if is_buy else "做空"
        mess = f"{emoji} [缠论-{action}] {symbol} ({main}) | {type_name}\n   现价: {price} | 止损: {stop_loss:.4f}\n"
        print(mess)
        return mess