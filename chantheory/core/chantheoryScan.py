import pandas as pd
import numpy as np
from hyperliquidDataMgr import MarketDataManager

class ChanLunStrategy:
    def __init__(self):
        self.data_manager = MarketDataManager()
        
        # 状态字典
        self.states = {} 

        # --- [修复] 补全缺失的参数定义 ---
        self.SLOPE_THRESHOLD = 0.35  # 均线斜率阈值 (防止逆势抄底)
        self.EXPIRATION_BARS = 60    # 信号等待超时周期 (K线根数)

    def get_state(self, key):
        if key not in self.states:
            self.states[key] = {
                'state': 'NEUTRAL',
                'last_1b_price': None, 'last_1b_idx': 0,
                'last_1s_price': None, 'last_1s_idx': 0,
                'last_pivot_ts': 0
            }
        return self.states[key]

    def reset_state(self):
        self.states = {}

    def calculate_indicators(self, df):
        if df is None or len(df) < 100: return None
        df = df.copy()
        
        # MACD
        df['ema_fast'] = df['close'].ewm(span=12, adjust=False).mean()
        df['ema_slow'] = df['close'].ewm(span=26, adjust=False).mean()
        df['diff'] = df['ema_fast'] - df['ema_slow']
        df['dea'] = df['diff'].ewm(span=9, adjust=False).mean()
        df['macd'] = 2 * (df['diff'] - df['dea'])
        
        # 均线
        df['ma5'] = df['close'].rolling(window=5).mean()
        df['ma60'] = df['close'].rolling(window=60).mean()
        df['vol_ma5'] = df['volume'].rolling(window=5).mean()
        
        # 斜率
        df['ma60_slope'] = (df['ma60'] - df['ma60'].shift(3)) / df['ma60'].shift(3) * 1000
        
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))

        # ATR
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift()).abs()
        low_close = (df['low'] - df['close'].shift()).abs()
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        df['atr'] = true_range.rolling(14).mean()
        
        # 辅助
        df['body'] = abs(df['close'] - df['open'])
        df['lower_shadow'] = df[['close', 'open']].min(axis=1) - df['low']
        df['upper_shadow'] = df['high'] - df[['close', 'open']].max(axis=1)
        
        return df

    def get_dynamic_config(self, df):
        if len(df) == 0: return 0.01, 30, 2.0
        curr_atr = df['atr'].iloc[-1]
        curr_price = df['close'].iloc[-1]
        
        if pd.isna(curr_atr) or curr_price == 0:
            return 0.01, 30, 2.0
            
        atr_pct = curr_atr / curr_price
        zz_dev = np.clip(atr_pct * 1.2, 0.008, 0.03)
        
        if atr_pct > 0.02: rsi_buy = 22; vol_mult = 2.5
        elif atr_pct > 0.01: rsi_buy = 28; vol_mult = 2.0
        else: rsi_buy = 32; vol_mult = 1.6 
            
        return zz_dev, rsi_buy, vol_mult

    def get_zigzag_pivots(self, df, deviation):
        pivots = []
        trend = 0 
        last_pivot_price = df['close'].iloc[0]
        last_pivot_idx = 0
        
        def get_metrics(idx):
            return {
                'rsi': df['rsi'].iloc[idx],
                'diff': df['diff'].iloc[idx],
                'ts': df['timestamp'].iloc[idx] if 'timestamp' in df.columns else df.index[idx]
            }

        for i in range(1, len(df)):
            curr_price = df['close'].iloc[i]
            if trend == 0:
                if curr_price > last_pivot_price * (1 + deviation):
                    trend = 1
                    pivots.append({'idx': 0, 'price': last_pivot_price, 'type': -1, **get_metrics(0)}) 
                    last_pivot_price = curr_price
                    last_pivot_idx = i
                elif curr_price < last_pivot_price * (1 - deviation):
                    trend = -1
                    pivots.append({'idx': 0, 'price': last_pivot_price, 'type': 1, **get_metrics(0)}) 
                    last_pivot_price = curr_price
                    last_pivot_idx = i
            elif trend == 1:
                if curr_price > last_pivot_price:
                    last_pivot_price = curr_price
                    last_pivot_idx = i
                elif curr_price < last_pivot_price * (1 - deviation):
                    pivots.append({'idx': last_pivot_idx, 'price': last_pivot_price, 'type': 1, **get_metrics(last_pivot_idx)})
                    trend = -1
                    last_pivot_price = curr_price
                    last_pivot_idx = i
            elif trend == -1:
                if curr_price < last_pivot_price:
                    last_pivot_price = curr_price
                    last_pivot_idx = i
                elif curr_price > last_pivot_price * (1 + deviation):
                    pivots.append({'idx': last_pivot_idx, 'price': last_pivot_price, 'type': -1, **get_metrics(last_pivot_idx)})
                    trend = 1
                    last_pivot_price = curr_price
                    last_pivot_idx = i
        
        pivots.append({'idx': len(df)-1, 'price': df['close'].iloc[-1], 'type': trend, **get_metrics(len(df)-1)})
        return pivots

    def calculate_macd_area(self, df, start_idx, end_idx):
        if start_idx >= end_idx: return 0.0
        return df['macd'].iloc[start_idx:end_idx].abs().sum()

    def check_trigger(self, curr, prev, vol_mult, mode='buy'):
        """V16 增强版触发器"""
        is_high_volume = curr['volume'] > curr['vol_ma5'] * vol_mult
        
        if mode == 'buy':
            # 1. 经典反转形态
            is_engulfing = (curr['close'] > prev['open'] and curr['close'] > curr['open']) # 阳包阴
            is_pinbar = (curr['lower_shadow'] > curr['body'] * 1.5) # 长下影
            
            # 2. 关键均线突破 (V16 新增核心)
            # 收盘价站上 MA5，且实体较大
            is_ma_break = curr['close'] > curr['ma5'] and curr['close'] > curr['open']
            
            return (is_engulfing or is_pinbar or is_ma_break) or (is_high_volume and curr['close'] > curr['open'])
            
        elif mode == 'sell':
            is_engulfing = (curr['close'] < prev['open'] and curr['close'] < curr['open'])
            is_pinbar = (curr['upper_shadow'] > curr['body'] * 1.5)
            is_ma_break = curr['close'] < curr['ma5'] and curr['close'] < curr['open']
            
            return (is_engulfing or is_pinbar or is_ma_break) or (is_high_volume and curr['close'] < curr['open'])
        

    def check_sub_structure(self, df_sub, mode='buy'):
        """
        次级别共振检查 (简化版区间套)
        检查次级别是否存在底背驰，或者处于极度超卖/超买状态
        """
        if df_sub is None or len(df_sub) < 30: return False # 数据不足默认不共振? 或者默认通过? 建议保守点返回False
        
        # 为了速度，次级别只看最近的 MACD 和 RSI
        curr = df_sub.iloc[-1]
        
        # 1. RSI 极值过滤 (最简单的共振)
        # 如果主级别看涨，次级别必须不能在高位; 主级别看跌，次级别不能在低位
        if mode == 'buy':
            # 如果次级别 RSI 还在 70 以上，说明次级别还在冲顶，绝对不能买
            if curr['rsi'] > 70: return False 
            # 最好是次级别也处于低位
            if curr['rsi'] < 40: return True 
            
        elif mode == 'sell':
            if curr['rsi'] < 30: return False
            if curr['rsi'] > 60: return True

        # 2. MACD 柱子缩短 (动能衰竭)
        # 比较最近两根柱子
        bar_curr = curr['macd']
        bar_prev = df_sub.iloc[-2]['macd']
        
        if mode == 'buy':
            # 绿柱缩短 (负值变大) 或者 已经翻红
            if bar_curr > bar_prev: return True
        elif mode == 'sell':
            # 红柱缩短 (正值变小) 或者 已经翻绿
            if bar_curr < bar_prev: return True
            
        return False        

    def analyze_snapshot(self, symbol, main_lvl, df_main, df_sub):
        """V16.1: 左侧背驰(含次级别共振) + 右侧V反修正 + 完整二买卖"""
        if df_main is None or len(df_main) < 100: return None
        
        # 状态 Key
        st_key = f"{symbol}_{main_lvl}"
        st = self.get_state(st_key)
        
        zz_dev, rsi_panic_buy, vol_mult = self.get_dynamic_config(df_main)
        pivots = self.get_zigzag_pivots(df_main, deviation=zz_dev)
        if len(pivots) < 4: return None
        
        curr = df_main.iloc[-1]
        curr_idx = len(df_main) - 1
        prev = df_main.iloc[-2]
        
        last_pivot = pivots[-1]      
        confirmed_pivot = pivots[-2] 
        
        slope = curr['ma60_slope']
        rsi = curr['rsi']
        
        # ==============================================================================
        # 🟢 买点探测 (Buy Side)
        # ==============================================================================
        
        # 1. 状态维护：等待二买确认
        if st['state'] == 'WAITING_FOR_2B':
            if curr_idx - st['last_1b_idx'] > self.EXPIRATION_BARS: # 超时
                st['state'] = 'NEUTRAL'
            elif curr['close'] < st['last_1b_price']: # 破前低止损
                st['state'] = 'NEUTRAL' 
        
        if st['state'] == 'NEUTRAL' or st['state'] == 'WAITING_FOR_1S':
            
            # --- 逻辑A: 左侧抄底 ---
            is_left_signal = False
            signal_desc = ""

            # A1. 恐慌底 (无需次级别，直接接飞刀)
            if curr['close'] < curr['ma60'] and rsi < rsi_panic_buy:
                if curr['volume'] > curr['vol_ma5'] * vol_mult:
                    if curr['close'] > curr['open'] or curr['lower_shadow'] > curr['body']*2:
                        is_left_signal = True; signal_desc = "一买(恐慌V反)"

            # A2. 结构背驰 (【关键】加入次级别验证)
            if not is_left_signal and last_pivot['type'] == -1: 
                if curr['close'] < curr['ma60'] and rsi < 65:
                    idx_bot_1 = pivots[-3]['idx']
                    idx_top_1 = pivots[-4]['idx'] if len(pivots) > 3 else 0
                    idx_top_2 = pivots[-2]['idx']
                    price_bot_1 = pivots[-3]['price']
                    
                    if curr['close'] < price_bot_1: 
                        area_1 = self.calculate_macd_area(df_main, idx_top_1, idx_bot_1)
                        area_2 = self.calculate_macd_area(df_main, idx_top_2, curr_idx)
                        
                        diff_1 = pivots[-3].get('diff', -999); diff_2 = curr['diff']
                        rsi_1 = pivots[-3].get('rsi', 0); rsi_2 = curr['rsi']
                        
                        # 主级别背驰条件
                        main_div = (area_2 < area_1 or diff_2 > diff_1 or rsi_2 > rsi_1)
                        
                        if main_div: 
                            # 【新增】次级别共振检查
                            if self.check_sub_structure(df_sub, mode='buy'):
                                if self.check_trigger(curr, prev, vol_mult, 'buy'):
                                    is_left_signal = True; signal_desc = "一买(区间套背驰)"

            if is_left_signal:
                st['state'] = 'WAITING_FOR_2B'
                st['last_1b_price'] = curr['low']
                st['last_1b_idx'] = curr_idx
                return {"type": "1B", "action": "buy", "price": curr['close'], "desc": signal_desc, "stop_loss": curr['low']*0.98}

            # --- 逻辑B: 右侧V反 (无需次级别) ---
            if curr['close'] < curr['ma60'] or rsi < 50:
                if curr['close'] > curr['ma5'] and curr['close'] > curr['open']:
                    if last_pivot['type'] == -1:
                        is_engulf = curr['close'] > prev['open'] and prev['close'] < prev['open']
                        is_vol = curr['volume'] > curr['vol_ma5'] * 1.2
                        is_rsi_up = curr['rsi'] > prev['rsi'] + 2
                        
                        if (is_engulf or is_vol) and is_rsi_up:
                             st['state'] = 'WAITING_FOR_2B'
                             st['last_1b_price'] = curr['low']
                             st['last_1b_idx'] = curr_idx
                             return {"type": "1B", "action": "buy", "price": curr['close'], "desc": "一买(右侧V反)", "stop_loss": curr['low']*0.99}

        # --- 逻辑C: 二买探测 ---
        elif st['state'] == 'WAITING_FOR_2B':
            if curr['close'] < st['last_1b_price']:
                st['state'] = 'NEUTRAL'; return None
            
            if slope < -self.SLOPE_THRESHOLD: return None
            if rsi > 70: return None 

            if confirmed_pivot['type'] == -1:
                if confirmed_pivot['ts'] != st['last_pivot_ts']:
                    if confirmed_pivot['price'] > st['last_1b_price']: 
                        check_range = df_main.iloc[st['last_1b_idx'] : curr_idx]
                        if (check_range['diff'] > 0).any(): # 零轴验证
                            if curr['close'] > confirmed_pivot['price']:
                                st['last_pivot_ts'] = confirmed_pivot['ts']
                                return {"type": "2B", "action": "buy", "price": curr['close'], "desc": "二买(回踩确认)", "stop_loss": confirmed_pivot['price']}

        # ==============================================================================
        # 🔴 卖点探测 (Sell Side)
        # ==============================================================================
        
        if st['state'] == 'WAITING_FOR_2S':
            if curr_idx - st['last_1s_idx'] > self.EXPIRATION_BARS:
                st['state'] = 'NEUTRAL'
        
        if st['state'] == 'NEUTRAL' or st['state'] == 'WAITING_FOR_2B':
            if last_pivot['type'] == 1: 
                if curr['close'] > curr['ma60'] and rsi > 40:
                    idx_top_1 = pivots[-3]['idx']
                    idx_bot_1 = pivots[-4]['idx'] if len(pivots) > 3 else 0
                    idx_bot_2 = pivots[-2]['idx']
                    price_top_1 = pivots[-3]['price']
                    
                    if curr['close'] > price_top_1:
                        area_1 = self.calculate_macd_area(df_main, idx_bot_1, idx_top_1)
                        area_2 = self.calculate_macd_area(df_main, idx_bot_2, curr_idx)
                        
                        diff_1 = pivots[-3].get('diff', 999); diff_2 = curr['diff']
                        rsi_1 = pivots[-3].get('rsi', 100); rsi_2 = curr['rsi']
                        
                        main_div = (area_2 < area_1 or diff_2 < diff_1 or rsi_2 < rsi_1)
                        
                        if main_div: 
                            # 【新增】次级别卖点共振
                            if self.check_sub_structure(df_sub, mode='sell'):
                                if self.check_trigger(curr, prev, vol_mult, 'sell'):
                                    st['state'] = 'WAITING_FOR_2S'
                                    st['last_1s_price'] = curr['high']
                                    st['last_1s_idx'] = curr_idx
                                    return {"type": "1S", "action": "sell", "price": curr['close'], "desc": "一卖(区间套背驰)", "stop_loss": curr['high']*1.01}

        # --- 逻辑D: 二卖探测 ---
        elif st['state'] == 'WAITING_FOR_2S':
            if curr['close'] > st['last_1s_price']:
                st['state'] = 'NEUTRAL'; return None
            
            if slope > self.SLOPE_THRESHOLD: return None
            if rsi < 30: return None 

            if confirmed_pivot['type'] == 1: 
                if confirmed_pivot['ts'] != st['last_pivot_ts']:
                    if confirmed_pivot['price'] < st['last_1s_price']:
                        check_range = df_main.iloc[st['last_1s_idx'] : curr_idx]
                        if (check_range['diff'] < 0).any():
                            if curr['close'] < confirmed_pivot['price']:
                                st['last_pivot_ts'] = confirmed_pivot['ts']
                                return {"type": "2S", "action": "sell", "price": curr['close'], "desc": "二卖(反抽不过)", "stop_loss": confirmed_pivot['price']}

        return None

    def get_time_ratio(self, main_lvl, sub_lvl):
        lv_map = {'5m':5, '15m':15, '30m':30, '1h':60, '2h':120, '4h':240, '1d':1440}
        m_val = lv_map.get(main_lvl, 30)
        s_val = lv_map.get(sub_lvl, 5)
        return max(1, m_val // s_val)

    # ... (Detect Signals 等其他方法保持不变) ...

    def detect_signals(self, symbol, main_lvl='30m', sub_lvl='5m'):
        """入口函数"""
        ratio = self.get_time_ratio(main_lvl, sub_lvl)
        main_limit = 600
        sub_limit = main_limit * ratio + 200
        sub_limit = min(sub_limit, 4800)

        self.data_manager.update_data(symbol, main_lvl)
        self.data_manager.update_data(symbol, sub_lvl)
        
        df_main = self.data_manager.load_data_for_analysis(symbol, main_lvl, limit=main_limit)
        df_sub = self.data_manager.load_data_for_analysis(symbol, sub_lvl, limit=sub_limit)
        
        df_main = self.calculate_indicators(df_main)
        
        signal = self.analyze_snapshot(symbol,main_lvl,df_main, df_sub)
        
        if signal:
            return self.print_signal(symbol, signal['desc'], main_lvl, sub_lvl, signal['price'], signal['stop_loss'], is_buy=(signal['action']=='buy'))
        return ""

    def print_signal(self, symbol, type_name, main, sub, price, stop_loss, is_buy=True):
        emoji = "🟢" if is_buy else "🔴"
        action = "买入" if is_buy else "卖出"
        ret = ""
        mess = f"{emoji} [{action}信号-{type_name}] {symbol} {emoji}"
        print(mess)
        ret += mess + "\n"
        mess = f"   - 级别: 主({main}) + 次({sub})"
        print(mess)
        ret += mess + "\n"
        mess = f"   - 现价: {price}"
        print(mess)
        ret += mess + "\n"
        mess = f"   - 🛑 结构止损: {stop_loss:.4f}"
        print(mess)
        ret += mess + "\n"        
        mess = "-" * 50
        print(mess)
        ret += mess + "\n"         
        return ret