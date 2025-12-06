import pandas as pd
import numpy as np
from hyperliquidDataMgr import MarketDataManager


class ChanLunStrategy:
    def __init__(self):
        self.data_manager = MarketDataManager()
        
        self.state = 'NEUTRAL' 
        self.last_1b_price = None  
        self.last_1b_idx = 0       
        self.last_1s_price = None  
        self.last_1s_idx = 0
        self.last_pivot_ts = 0     

        # --- [V15.0] 参数 ---
        self.SLOPE_THRESHOLD = 0.35
        self.EXPIRATION_BARS = 60
        # 动态参数由 get_dynamic_config 计算

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
        """ATR 动态门槛配置"""
        curr_atr = df['atr'].iloc[-1]
        curr_price = df['close'].iloc[-1]
        
        if np.isnan(curr_atr) or curr_price == 0:
            return 0.01, 30, 2.0
            
        atr_pct = curr_atr / curr_price
        
        # 1. ZigZag 阈值
        zz_dev = np.clip(atr_pct * 1.2, 0.008, 0.03)
        
        # 2. 恐慌门槛
        if atr_pct > 0.02: 
            rsi_buy = 22; vol_mult = 2.5
        elif atr_pct > 0.01:
            rsi_buy = 28; vol_mult = 2.0
        else:
            rsi_buy = 32; vol_mult = 1.6 # ETH这种低波币，成交量门槛稍微降一点
            
        return zz_dev, rsi_buy, vol_mult

    def get_zigzag_pivots(self, df, deviation):
        """
        [V15 升级] ZigZag 记录更多信息 (RSI, Diff)
        """
        pivots = []
        trend = 0 
        last_pivot_price = df['close'].iloc[0]
        last_pivot_idx = 0
        
        # 辅助：获取某一时刻的 RSI 和 Diff
        def get_metrics(idx):
            return {
                'rsi': df['rsi'].iloc[idx],
                'diff': df['diff'].iloc[idx]
            }

        for i in range(1, len(df)):
            curr_price = df['close'].iloc[i]
            
            if trend == 0:
                if curr_price > last_pivot_price * (1 + deviation):
                    trend = 1
                    # 记录底点
                    metrics = get_metrics(0)
                    pivots.append({'idx': 0, 'price': last_pivot_price, 'type': -1, **metrics}) 
                    last_pivot_price = curr_price
                    last_pivot_idx = i
                elif curr_price < last_pivot_price * (1 - deviation):
                    trend = -1
                    # 记录顶点
                    metrics = get_metrics(0)
                    pivots.append({'idx': 0, 'price': last_pivot_price, 'type': 1, **metrics}) 
                    last_pivot_price = curr_price
                    last_pivot_idx = i
            
            elif trend == 1:
                if curr_price > last_pivot_price:
                    last_pivot_price = curr_price
                    last_pivot_idx = i
                elif curr_price < last_pivot_price * (1 - deviation):
                    # 确立顶点
                    metrics = get_metrics(last_pivot_idx)
                    pivots.append({'idx': last_pivot_idx, 'price': last_pivot_price, 'type': 1, **metrics})
                    trend = -1
                    last_pivot_price = curr_price
                    last_pivot_idx = i
            
            elif trend == -1:
                if curr_price < last_pivot_price:
                    last_pivot_price = curr_price
                    last_pivot_idx = i
                elif curr_price > last_pivot_price * (1 + deviation):
                    # 确立底点
                    metrics = get_metrics(last_pivot_idx)
                    pivots.append({'idx': last_pivot_idx, 'price': last_pivot_price, 'type': -1, **metrics})
                    trend = 1
                    last_pivot_price = curr_price
                    last_pivot_idx = i
        
        # 最后一个未完成的笔
        metrics = get_metrics(len(df)-1)
        pivots.append({'idx': len(df)-1, 'price': df['close'].iloc[-1], 'type': trend, **metrics})
        return pivots

    def calculate_macd_area(self, df, start_idx, end_idx):
        if start_idx >= end_idx: return 0.0
        return df['macd'].iloc[start_idx:end_idx].abs().sum()

    def check_trigger(self, curr, prev, vol_mult, mode='buy'):
        """V15 触发器"""
        is_high_volume = curr['volume'] > curr['vol_ma5'] * vol_mult
        
        if mode == 'buy':
            # 形态: 阳包阴 OR 长下影 OR 站上MA5
            is_shape = (curr['close'] > prev['open'] and curr['close'] > curr['open']) or \
                       (curr['lower_shadow'] > curr['body'] * 1.5) or \
                       (curr['close'] > curr['ma5'] and curr['close'] > curr['open'])
            
            return is_shape or (is_high_volume and curr['close'] > curr['open'])
            
        elif mode == 'sell':
            is_shape = (curr['close'] < prev['open'] and curr['close'] < curr['open']) or \
                       (curr['upper_shadow'] > curr['body'] * 1.5) or \
                       (curr['close'] < curr['ma5'] and curr['close'] < curr['open'])
            
            return is_shape or (is_high_volume and curr['close'] < curr['open'])

    def analyze_snapshot(self, df_main, df_sub):
        """V15.0: 三维背驰 (面积/点/RSI)"""
        if df_main is None or len(df_main) < 100: return None
        
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
        
        signal_info = None

        # ==============================================================================
        # 🟢 买点探测 (Buy Side)
        # ==============================================================================
        
        if self.state == 'WAITING_FOR_2B':
            if curr_idx - self.last_1b_idx > self.EXPIRATION_BARS:
                self.state = 'NEUTRAL'
        
        if self.state == 'NEUTRAL' or self.state == 'WAITING_FOR_1S':
            
            # --- [逻辑A: 恐慌买入] ---
            if curr['close'] < curr['ma60'] and rsi < rsi_panic_buy:
                if curr['volume'] > curr['vol_ma5'] * vol_mult:
                    if curr['close'] > curr['open'] or curr['lower_shadow'] > curr['body']*2:
                        self.state = 'WAITING_FOR_2B'
                        self.last_1b_price = curr['low']
                        self.last_1b_idx = curr_idx
                        return {
                            "type": "1B", "action": "buy", "price": curr['close'], 
                            "desc": "一买(恐慌V反)", "stop_loss": curr['low']*0.98
                        }

            # --- [逻辑B: 结构背驰 (三维验证)] ---
            if last_pivot['type'] == -1: 
                if curr['close'] < curr['ma60'] and rsi < 65:
                    
                    idx_bot_1 = pivots[-3]['idx']
                    idx_top_1 = pivots[-4]['idx'] if len(pivots) > 3 else 0
                    idx_top_2 = pivots[-2]['idx']
                    price_bot_1 = pivots[-3]['price']
                    
                    # 必须是新低
                    if curr['close'] < price_bot_1: 
                        
                        # 1. 面积背驰 (能量)
                        area_1 = self.calculate_macd_area(df_main, idx_top_1, idx_bot_1)
                        area_2 = self.calculate_macd_area(df_main, idx_top_2, curr_idx)
                        is_area_div = area_2 < area_1
                        
                        # 2. 点背驰 (速度) - 比较 Diff 最低点
                        # 注意：需要比较 pivots[-3] 记录的 diff 和当前的 diff
                        diff_1 = pivots[-3].get('diff', -999)
                        diff_2 = curr['diff']
                        is_point_div = diff_2 > diff_1
                        
                        # 3. [新增] RSI背驰 (动量)
                        rsi_1 = pivots[-3].get('rsi', 0)
                        rsi_2 = curr['rsi']
                        is_rsi_div = rsi_2 > rsi_1
                        
                        # 综合判定：满足任意一种背驰即可，但必须有 K线触发
                        is_any_div = is_area_div or is_point_div or is_rsi_div
                        
                        if is_any_div: 
                            if self.check_trigger(curr, prev, vol_mult, 'buy'):
                                
                                # 生成描述
                                reasons = []
                                if is_area_div: reasons.append("面积")
                                if is_point_div: reasons.append("点")
                                if is_rsi_div: reasons.append("RSI")
                                desc = f"一买({'|'.join(reasons)}背驰)"
                                
                                self.state = 'WAITING_FOR_2B'
                                self.last_1b_price = curr['low']
                                self.last_1b_idx = curr_idx
                                return {
                                    "type": "1B", "action": "buy", "price": curr['close'], 
                                    "desc": desc, "stop_loss": curr['low']*0.99
                                }

        elif self.state == 'WAITING_FOR_2B':
            # [2B 探测]
            if curr['close'] < self.last_1b_price:
                self.state = 'NEUTRAL'
                return None
            
            if slope < -self.SLOPE_THRESHOLD: return None
            if rsi > 70: return None 

            if confirmed_pivot['type'] == -1:
                if confirmed_pivot['idx'] != self.last_pivot_ts:
                    if confirmed_pivot['price'] > self.last_1b_price: 
                        
                        check_range = df_main.iloc[self.last_1b_idx : curr_idx]
                        has_crossed_zero = (check_range['diff'] > 0).any()
                        
                        if has_crossed_zero:
                            if curr['close'] > confirmed_pivot['price']:
                                self.last_pivot_ts = confirmed_pivot['idx']
                                return {
                                    "type": "2B", "action": "buy", "price": curr['close'], 
                                    "desc": "二买(回踩确认)", "stop_loss": confirmed_pivot['price']
                                }

        # ==============================================================================
        # 🔴 卖点探测 (Sell Side)
        # ==============================================================================
        
        if self.state == 'WAITING_FOR_2S':
            if curr_idx - self.last_1s_idx > self.EXPIRATION_BARS:
                self.state = 'NEUTRAL'

        if self.state == 'NEUTRAL' or self.state == 'WAITING_FOR_2B':
            # [1S]
            if last_pivot['type'] == 1: 
                if curr['close'] > curr['ma60'] and rsi > 40:
                    
                    idx_top_1 = pivots[-3]['idx']
                    idx_bot_1 = pivots[-4]['idx'] if len(pivots) > 3 else 0
                    idx_bot_2 = pivots[-2]['idx']
                    price_top_1 = pivots[-3]['price']
                    
                    if curr['close'] > price_top_1: # 新高
                        area_1 = self.calculate_macd_area(df_main, idx_bot_1, idx_top_1)
                        area_2 = self.calculate_macd_area(df_main, idx_bot_2, curr_idx)
                        is_area_div = area_2 < area_1
                        
                        diff_1 = pivots[-3].get('diff', 999)
                        diff_2 = curr['diff']
                        is_point_div = diff_2 < diff_1
                        
                        rsi_1 = pivots[-3].get('rsi', 100)
                        rsi_2 = curr['rsi']
                        is_rsi_div = rsi_2 < rsi_1
                        
                        if is_area_div or is_point_div or is_rsi_div: 
                            if self.check_trigger(curr, prev, vol_mult, 'sell'):
                                self.state = 'WAITING_FOR_2S'
                                self.last_1s_price = curr['high']
                                self.last_1s_idx = curr_idx
                                return {
                                    "type": "1S", "action": "sell", "price": curr['close'], 
                                    "desc": "一卖(多维力竭)", "stop_loss": curr['high']*1.01
                                }

        elif self.state == 'WAITING_FOR_2S':
            # [2S 探测]
            if curr['close'] > self.last_1s_price:
                self.state = 'NEUTRAL'
                return None
            
            if slope > self.SLOPE_THRESHOLD: return None
            if rsi < 30: return None 

            if confirmed_pivot['type'] == 1: 
                if confirmed_pivot['idx'] != self.last_pivot_ts:
                    if confirmed_pivot['price'] < self.last_1s_price:
                        
                        check_range = df_main.iloc[self.last_1s_idx : curr_idx]
                        has_crossed_zero = (check_range['diff'] < 0).any()
                        
                        if has_crossed_zero:
                            if curr['close'] < confirmed_pivot['price']:
                                self.last_pivot_ts = confirmed_pivot['idx']
                                return {
                                    "type": "2S", "action": "sell", "price": curr['close'], 
                                    "desc": "二卖(反抽不过)", "stop_loss": confirmed_pivot['price']
                                }

        return signal_info

    def get_time_ratio(self, main_lvl, sub_lvl):
        lv_map = {'5m':5, '15m':15, '30m':30, '1h':60, '2h':120, '4h':240, '1d':1440}
        m_val = lv_map.get(main_lvl, 30)
        s_val = lv_map.get(sub_lvl, 5)
        return max(1, m_val // s_val)

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
        
        signal = self.analyze_snapshot(df_main, df_sub)
        
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