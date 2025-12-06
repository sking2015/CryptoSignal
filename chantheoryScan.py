import pandas as pd
import numpy as np
from hyperliquidDataMgr import MarketDataManager
import traceback
import asyncio
from datetime import datetime

class ChanLunStrategy:
    def __init__(self):
        self.data_manager = MarketDataManager()
        
        # --- 核心状态机 ---
        self.state = 'NEUTRAL' 
        
        # 记忆变量
        self.last_1b_price = None  
        self.last_1b_idx = 0       # 记录一买发生的时间索引(用于过期判断)
        
        self.last_1s_price = None  
        self.last_1s_idx = 0
        
        self.last_pivot_ts = 0     # 去重锁

    def calculate_indicators(self, df):
        """计算缠论指标"""
        if df is None or len(df) < 50: return None
        df = df.copy()
        
        # MACD (12, 26, 9)
        df['ema_fast'] = df['close'].ewm(span=12, adjust=False).mean()
        df['ema_slow'] = df['close'].ewm(span=26, adjust=False).mean()
        df['diff'] = df['ema_fast'] - df['ema_slow']
        df['dea'] = df['diff'].ewm(span=9, adjust=False).mean()
        df['macd'] = 2 * (df['diff'] - df['dea'])
        
        # 均线系统
        df['ma5'] = df['close'].rolling(window=5).mean()
        df['ma60'] = df['close'].rolling(window=60).mean()
        
        # [新增] MA60 斜率 (Slope)
        # 计算过去5根K线 MA60 的变化率，放大1000倍方便比较
        df['ma60_slope'] = (df['ma60'] - df['ma60'].shift(5)) / df['ma60'].shift(5) * 1000
        
        # 辅助: 实体与影线
        df['body'] = abs(df['close'] - df['open'])
        df['lower_shadow'] = df[['close', 'open']].min(axis=1) - df['low']
        df['upper_shadow'] = df['high'] - df[['close', 'open']].max(axis=1)
        
        return df

    def get_zigzag_pivots(self, df, deviation=0.01):
        """ZigZag 笔识别"""
        pivots = []
        trend = 0 
        last_pivot_price = df['close'].iloc[0]
        last_pivot_idx = 0
        
        for i in range(1, len(df)):
            curr_price = df['close'].iloc[i]
            
            if trend == 0:
                if curr_price > last_pivot_price * (1 + deviation):
                    trend = 1
                    pivots.append({'idx': 0, 'price': last_pivot_price, 'type': -1}) 
                    last_pivot_price = curr_price
                    last_pivot_idx = i
                elif curr_price < last_pivot_price * (1 - deviation):
                    trend = -1
                    pivots.append({'idx': 0, 'price': last_pivot_price, 'type': 1}) 
                    last_pivot_price = curr_price
                    last_pivot_idx = i
            
            elif trend == 1: # 上升
                if curr_price > last_pivot_price:
                    last_pivot_price = curr_price
                    last_pivot_idx = i
                elif curr_price < last_pivot_price * (1 - deviation):
                    pivots.append({'idx': last_pivot_idx, 'price': last_pivot_price, 'type': 1})
                    trend = -1
                    last_pivot_price = curr_price
                    last_pivot_idx = i
            
            elif trend == -1: # 下跌
                if curr_price < last_pivot_price:
                    last_pivot_price = curr_price
                    last_pivot_idx = i
                elif curr_price > last_pivot_price * (1 + deviation):
                    pivots.append({'idx': last_pivot_idx, 'price': last_pivot_price, 'type': -1})
                    trend = 1
                    last_pivot_price = curr_price
                    last_pivot_idx = i
        
        pivots.append({'idx': len(df)-1, 'price': df['close'].iloc[-1], 'type': trend})
        return pivots

    def calculate_macd_area(self, df, start_idx, end_idx):
        if start_idx >= end_idx: return 0.0
        return df['macd'].iloc[start_idx:end_idx].abs().sum()

    def check_trigger(self, curr, prev, mode='buy'):
        """K线形态触发器"""
        if mode == 'buy':
            # 阳包阴 OR 刺透 OR 站上MA5 OR 长下影
            is_engulfing = curr['close'] > prev['open'] and curr['close'] > curr['open'] and prev['close'] < prev['open']
            is_ma_break = curr['close'] > curr['ma5']
            return is_engulfing or is_ma_break
            
        elif mode == 'sell':
            # 阴包阳 OR 跌破MA5 OR 长上影
            is_engulfing = curr['close'] < prev['open'] and curr['close'] < curr['open'] and prev['close'] > prev['open']
            is_ma_break = curr['close'] < curr['ma5']
            return is_engulfing or is_ma_break

    def analyze_snapshot(self, df_main, df_sub):
        """V9.0: 趋势斜率过滤 + 零轴验证"""
        if df_main is None or len(df_main) < 100: return None
        
        # ZigZag 识别 (1% 阈值)
        pivots = self.get_zigzag_pivots(df_main, deviation=0.01)
        if len(pivots) < 4: return None
        
        curr = df_main.iloc[-1]
        curr_idx = len(df_main) - 1
        prev = df_main.iloc[-2]
        
        last_pivot = pivots[-1]      
        confirmed_pivot = pivots[-2] 
        
        # [重要] MA60 斜率
        # slope > 0.5: 强向上, slope < -0.5: 强向下, -0.5~0.5: 震荡
        slope = curr['ma60_slope']
        
        signal_info = None

        # ==============================================================================
        # 🟢 买点逻辑 (Buy Side)
        # ==============================================================================
        
        # --- 状态过期检查 ---
        # 如果等待 2B 超过 40 根 K线，还没等到，说明 1B 失效，重置状态
        if self.state == 'WAITING_FOR_2B':
            if curr_idx - self.last_1b_idx > 40:
                self.state = 'NEUTRAL'
        
        if self.state == 'NEUTRAL' or self.state == 'WAITING_FOR_1S':
            # [1B 探测]
            if last_pivot['type'] == -1: # 正在下跌
                # 只有在乖离率较大时(跌破MA60)，或者斜率向下时，才去摸底
                if curr['close'] < curr['ma60']:
                    idx_bot_1 = pivots[-3]['idx']
                    idx_top_1 = pivots[-4]['idx'] if len(pivots) > 3 else 0
                    idx_top_2 = pivots[-2]['idx']
                    price_bot_1 = pivots[-3]['price']
                    
                    # 1. 创新低
                    if curr['close'] < price_bot_1:
                        # 2. 面积背驰
                        area_1 = self.calculate_macd_area(df_main, idx_top_1, idx_bot_1)
                        area_2 = self.calculate_macd_area(df_main, idx_top_2, curr_idx)
                        
                        if area_2 < area_1:
                            # 3. K线触发
                            if self.check_trigger(curr, prev, 'buy'):
                                self.state = 'WAITING_FOR_2B'
                                self.last_1b_price = curr['low']
                                self.last_1b_idx = curr_idx
                                return {
                                    "type": "1B", "action": "buy", "price": curr['close'], 
                                    "desc": "一买(趋势背驰)", "stop_loss": curr['low']*0.99
                                }

        elif self.state == 'WAITING_FOR_2B':
            # [2B 探测]
            # 止损：跌破 1B
            if curr['close'] < self.last_1b_price:
                self.state = 'NEUTRAL'
                return None
            
            # [铁律] 如果均线还在大角度向下 (Slope < -0.5)，严禁做二买！
            # 这就是你之前高位接盘和半山腰接盘的原因
            if slope < -0.5:
                return None 

            if confirmed_pivot['type'] == -1: # 确认了一个底
                if confirmed_pivot['idx'] != self.last_pivot_ts:
                    # 1. Higher Low
                    if confirmed_pivot['price'] > self.last_1b_price:
                        
                        # [铁律] 零轴穿越验证
                        # 检查 1B 到 2B 之间，MACD 是否曾经强势过 (Diff > 0)
                        # 这代表中间那波反弹是“真反弹”
                        check_range = df_main.iloc[self.last_1b_idx : curr_idx]
                        has_crossed_zero = (check_range['diff'] > 0).any()
                        
                        if has_crossed_zero:
                            # 2. 确认回升
                            if curr['close'] > confirmed_pivot['price']:
                                self.last_pivot_ts = confirmed_pivot['idx']
                                return {
                                    "type": "2B", "action": "buy", "price": curr['close'], 
                                    "desc": "二买(回踩确认)", "stop_loss": confirmed_pivot['price']
                                }

        # ==============================================================================
        # 🔴 卖点逻辑 (Sell Side)
        # ==============================================================================
        
        # 状态过期检查
        if self.state == 'WAITING_FOR_2S':
            if curr_idx - self.last_1s_idx > 40:
                self.state = 'NEUTRAL'

        if self.state == 'NEUTRAL' or self.state == 'WAITING_FOR_2B':
            # [1S 探测]
            if last_pivot['type'] == 1: # 正在上涨
                # 只有价格在 MA60 上方才考虑顶背驰
                if curr['close'] > curr['ma60']:
                    idx_top_1 = pivots[-3]['idx']
                    idx_bot_1 = pivots[-4]['idx'] if len(pivots) > 3 else 0
                    idx_bot_2 = pivots[-2]['idx']
                    price_top_1 = pivots[-3]['price']
                    
                    # 1. 创新高
                    if curr['close'] > price_top_1:
                        # 2. 面积背驰
                        area_1 = self.calculate_macd_area(df_main, idx_bot_1, idx_top_1)
                        area_2 = self.calculate_macd_area(df_main, idx_bot_2, curr_idx)
                        
                        if area_2 < area_1:
                            # 3. K线触发
                            if self.check_trigger(curr, prev, 'sell'):
                                self.state = 'WAITING_FOR_2S'
                                self.last_1s_price = curr['high']
                                self.last_1s_idx = curr_idx
                                return {
                                    "type": "1S", "action": "sell", "price": curr['close'], 
                                    "desc": "一卖(顶背驰)", "stop_loss": curr['high']*1.01
                                }

        elif self.state == 'WAITING_FOR_2S':
            # [2S 探测]
            if curr['close'] > self.last_1s_price:
                self.state = 'NEUTRAL'
                return None
            
            # [铁律] 如果均线还在大角度向上 (Slope > 0.5)，严禁做二卖！
            # 防止在主升浪里摸顶
            if slope > 0.5:
                return None

            if confirmed_pivot['type'] == 1: # 确认了一个顶
                if confirmed_pivot['idx'] != self.last_pivot_ts:
                    # 1. Lower High
                    if confirmed_pivot['price'] < self.last_1s_price:
                        
                        # [铁律] 零轴验证
                        # 中间必须跌破过零轴
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

    def detect_signals(self, symbol, main_lvl='30m', sub_lvl='5m'):
        """入口函数：修复次级别数据不足导致无信号的问题"""
        
        # 1. 计算时间倍率 (例如 1h / 5m = 12)
        # 简单映射
        lv_map = {'5m':5, '15m':15, '30m':30, '1h':60, '2h':120, '4h':240, '1d':1440}
        m_val = lv_map.get(main_lvl, 30)
        s_val = lv_map.get(sub_lvl, 5)
        ratio = max(1, m_val // s_val)
        
        # 2. 动态计算 limit
        # 如果主级别要分析 300 根，次级别至少需要 300 * ratio
        main_limit = 500
        sub_limit = main_limit * ratio + 200 # 多加一点 buffer
        sub_limit = min(sub_limit, 4500) # 限制上限

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