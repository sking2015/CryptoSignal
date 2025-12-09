import pandas as pd
import numpy as np
from hyperliquidDataMgr import MarketDataManager

class ChanLunStrategy:
    def __init__(self,data_manager=None):
        if data_manager:
            self.data_manager = data_manager
        else:
            self.data_manager = MarketDataManager()
        self.states = {} 
        self.last_trade_result = {}
        self.SLOPE_THRESHOLD = 0.35 
        self.EXPIRATION_BARS = 60

    # ... (get_state, reset_state 保持不变) ...
    # 🚨 [新增] 运行结束后，持久化状态
    def persist_state(self, key):
        """将单个 key 的状态保存到数据库"""
        if key in self.states:
            self.data_manager.save_strategy_state(key, self.states[key])


    def get_state(self, key):
        if key not in self.states:
            # 🚨 [新增] 尝试从数据库加载旧状态
            loaded_state = self.data_manager.load_strategy_state(key)
            if loaded_state:
                self.states[key] = loaded_state
            else:
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

        # [新增] 计算价格的标准差，用于辅助判断波动率
        df['std'] = df['close'].rolling(20).std()
        
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

    def get_macd_history(self, df, idx):
        """
        智能回溯 MACD 历史状态 V2.0 (加入价格锚点)
        功能: 找到当前波段峰值、上一个波段峰值，以及【峰值对应的股价】
        """
        curr_macd = df['macd'].iloc[idx]
        if curr_macd == 0: 
            return {'curr_peak': 0, 'prev_peak': 0, 'prev_peak_price': 0}
        
        is_red = curr_macd > 0
        
        # 1. 寻找当前波段 (Current Wave)
        curr_peak = abs(curr_macd)
        i = idx
        while i >= 0:
            val = df['macd'].iloc[i]
            # 遇到变色，当前波段结束
            if (is_red and val < 0) or (not is_red and val > 0):
                break
            curr_peak = max(curr_peak, abs(val))
            i -= 1
        
        curr_cluster_start = i 
        
        # 2. 跨越中间的异色波段 (Gap Wave)
        j = curr_cluster_start
        found_intermediate = False 
        
        while j >= 0:
            val = df['macd'].iloc[j]
            # 如果我是红柱，我要找中间的绿柱海洋
            if is_red:
                if val < 0: found_intermediate = True 
                if found_intermediate and val > 0: # 终于彼岸，到达上一个红波段
                    break
            else: # 如果我是绿柱
                if val > 0: found_intermediate = True
                if found_intermediate and val < 0:
                    break
            j -= 1
            
        # 3. 寻找上一个波段的峰值 (Previous Wave)
        prev_peak = 0
        prev_peak_price = 0 # 新增：记录上一个波峰出现时的收盘价
        
        if j >= 0: # 只有找到了上一个波段才进这里
            k = j
            while k >= 0:
                val = df['macd'].iloc[k]
                # 如果又变色了，说明上一个波段也找完了
                if (is_red and val < 0) or (not is_red and val > 0):
                    break
                
                # 记录最大值
                if abs(val) > prev_peak:
                    prev_peak = abs(val)
                    # 关键修正：记录峰值时刻的 High 或 Close (这里用 High 更灵敏)
                    prev_peak_price = df['high'].iloc[k] 
                
                k -= 1
            
        return {
            'curr_peak': curr_peak,
            'prev_peak': prev_peak,
            'prev_peak_price': prev_peak_price # 返回上个山头的价格，用于比对
        }


    def analyze_snapshot(self, symbol, main_lvl, df_main, df_sub):
        """V22.0 回归增强版: 基于 V19 内核，精准修复 3S 追空和 3B 逻辑错乱"""
        
        if df_main is None or len(df_main) < 100: return None
        
        st_key = f"{symbol}_{main_lvl}"
        st = self.get_state(st_key)
        
        # 基础数据准备
        curr = df_main.iloc[-1]
        curr_idx = len(df_main) - 1
        prev = df_main.iloc[-2]
        
        zz_dev, rsi_panic_buy, vol_mult = self.get_dynamic_config(df_main)
        pivots = self.get_zigzag_pivots(df_main, deviation=zz_dev)
        if len(pivots) < 4: return None
        
        last_pivot = pivots[-1]      
        confirmed_pivot = pivots[-2] 
        slope = curr['ma60_slope']
        rsi = curr['rsi']

        # 辅助变量：记录交易结果的 Key (用于解决 1S -> 3B 问题)
        res_key = f"{symbol}_{main_lvl}"

        # ==============================================================================
        # 🛡️ 1. 持仓管理与止损 (Position Management)
        # ==============================================================================
        
        # --- 场景 A: 持有多单 (Waiting for 2B) ---
        if st['state'] == 'WAITING_FOR_2B':
            # 1. 强制止损
            if curr['close'] < st['last_1b_price']:
                st['state'] = 'NEUTRAL'
                self.last_trade_result[res_key] = {'type': 'STOP_LOSS_LONG', 'idx': curr_idx}
                return {
                    "type": "STOP_LOSS", "action": "sell", 
                    "price": curr['close'], "desc": "⛔ 止损(多单破位)", "stop_loss": 0
                }
            # 2. 超时
            if curr_idx - st['last_1b_idx'] > self.EXPIRATION_BARS: 
                st['state'] = 'NEUTRAL'
                return None

        # --- 场景 B: 持有空单 (Waiting for 2S) ---
        elif st['state'] == 'WAITING_FOR_2S':
            # 1. 空单止损
            if curr['close'] > st['last_1s_price']:
                st['state'] = 'NEUTRAL'
                
                # 🚨 记录空单止损，用于后续过滤“幽灵3B”
                self.last_trade_result[res_key] = {'type': 'STOP_LOSS_SHORT', 'idx': curr_idx}
                
                return {
                    "type": "STOP_LOSS", "action": "buy", 
                    "price": curr['close'], "desc": "⛔ 止损(空单破位)", "stop_loss": 0
                }
            # 2. 超时
            if curr_idx - st['last_1s_idx'] > self.EXPIRATION_BARS: 
                st['state'] = 'NEUTRAL'
                return None

        # ==============================================================================
        # 🟢 2. 开仓探测 (Open Position) - 仅在空仓时
        # ==============================================================================
        
        if st['state'] == 'NEUTRAL' or st['state'] == 'WAITING_FOR_1S':
            
            # ------------------------------------------------------------------
            # 逻辑 E: 三买 (趋势中继)
            # ------------------------------------------------------------------
            if curr['close'] > curr['ma60'] and slope > 0.05: 
                if last_pivot['type'] == -1: # 底分型
                    if curr['low'] > curr['ma60'] * 0.995: 
                        if 0 < curr['diff'] < curr['std'] * 2.0: 
                             
                             # 🚨 [修复逻辑 1]: 防止 1S 止损后立即报 3B
                             # 只有当当前的 ZigZag 低点是在止损发生【之后】形成的，才算有效回调。
                             # 否则就是用旧结构在追高。
                             is_valid_3b = True
                             last_res = self.last_trade_result.get(res_key)
                             if last_res and last_res.get('type') == 'STOP_LOSS_SHORT':
                                 if last_pivot['idx'] <= last_res['idx']:
                                     is_valid_3b = False

                             if is_valid_3b:
                                 if self.check_trigger(curr, prev, vol_mult, 'buy'):
                                     st['state'] = 'WAITING_FOR_2B'; st['last_1b_price'] = curr['low']; st['last_1b_idx'] = curr_idx
                                     return {"type": "3B", "action": "buy", "price": curr['close'], "desc": "三买(趋势中继)", "stop_loss": curr['low']*0.98}

            # ------------------------------------------------------------------
            # 逻辑 A/B: 一买 (抄底) - 回归 V19 宽松逻辑，找回丢失的买点
            # ------------------------------------------------------------------
            is_left_signal = False
            signal_desc = ""

            # 1. 恐慌 V 反 (RSI 极低 + 放量)
            if curr['close'] < curr['ma60'] and rsi < rsi_panic_buy:
                if curr['volume'] > curr['vol_ma5'] * vol_mult:
                    if curr['close'] > curr['open'] or curr['lower_shadow'] > curr['body']*2:
                        is_left_signal = True; signal_desc = "一买(恐慌V反)"

            # 2. 区间套背驰 (MACD 背驰)
            if not is_left_signal and last_pivot['type'] == -1: 
                if curr['close'] < curr['ma60'] and rsi < 65: # 只要 RSI 不在高位即可
                    
                    idx_top_2 = pivots[-2]['idx']
                    idx_top_1 = pivots[-4]['idx'] if len(pivots) > 3 else 0
                    idx_bot_1 = pivots[-3]['idx']
                    if curr['close'] < pivots[-3]['price']: 
                        area_1 = self.calculate_macd_area(df_main, idx_top_1, idx_bot_1)
                        area_2 = self.calculate_macd_area(df_main, idx_top_2, curr_idx)
                        diff_1 = pivots[-3].get('diff', -999); diff_2 = curr['diff']
                        rsi_1 = pivots[-3].get('rsi', 0); rsi_2 = curr['rsi']
                        
                        # 经典背驰条件
                        if (area_2 < area_1 or diff_2 > diff_1 or rsi_2 > rsi_1): 
                            if self.check_sub_structure(df_sub, mode='buy'): 
                                if self.check_trigger(curr, prev, vol_mult, 'buy'):
                                    is_left_signal = True; signal_desc = "一买(区间套背驰)"

            if is_left_signal:
                st['state'] = 'WAITING_FOR_2B'; st['last_1b_price'] = curr['low']; st['last_1b_idx'] = curr_idx
                return {"type": "1B", "action": "buy", "price": curr['close'], "desc": signal_desc, "stop_loss": curr['low']*0.98}

            # ------------------------------------------------------------------
            # 逻辑 H: 一卖 (逃顶)
            # ------------------------------------------------------------------
            if curr['close'] > curr['ma60']:
                if rsi > 60: 
                    is_stalling = False
                    if curr['high'] > prev['high']: 
                        if curr['close'] < curr['open'] or curr['upper_shadow'] > curr['body'] * 1.5 or curr['close'] < prev['high']: 
                            is_stalling = True
                    if abs(curr['close'] - curr['open']) / curr['close'] < 0.003: is_stalling = True

                    if is_stalling:
                        macd_stats = self.get_macd_history(df_main, curr_idx)
                        curr_bar = abs(curr['macd'])
                        prev_bar = abs(prev['macd'])
                        div_ratio = 1.0
                        if macd_stats['prev_peak'] > 0: div_ratio = macd_stats['curr_peak'] / macd_stats['prev_peak']
                        price_divergence = curr['high'] > macd_stats['prev_peak_price']
                        
                        is_strong_trend = slope > 0.6 
                        is_severe = div_ratio < 0.6 and price_divergence
                        is_shrinking = curr_bar < prev_bar
                        is_standard = False
                        if not is_strong_trend:
                            if div_ratio < 0.85 and price_divergence and is_shrinking:
                                is_standard = True
                        is_internal = False
                        if rsi > 82 and curr_bar < macd_stats['curr_peak'] * 0.8: is_internal = True

                        if is_severe or is_standard or is_internal:
                             if curr['macd'] > 0: 
                                 desc = f"一卖(背驰 r={div_ratio:.2f})"
                                 # 允许反手做空，更新状态
                                 st['state'] = 'WAITING_FOR_2S'; st['last_1s_price'] = curr['high']; st['last_1s_idx'] = curr_idx
                                 return {"type": "1S", "action": "sell", "price": curr['close'], "desc": desc, "stop_loss": curr['high']*1.01}

            # ------------------------------------------------------------------
            # 逻辑 F: 三卖 (下跌中继)
            # ------------------------------------------------------------------
            # 🚨 [修复逻辑 2]: 解决“3S 追空地板”问题
            # 必须增加“超卖保护”：如果 RSI 已经很低，或者离 MA60 太远，禁止三卖。
            
            if st['state'] == 'NEUTRAL':
                if curr['close'] < curr['ma60'] and slope < -0.1:
                    if last_pivot['type'] == 1 and curr['high'] < curr['ma60'] * 1.005:
                        
                        # 核心过滤：
                        # 1. RSI 不能太低 (防止在底部追空)
                        # 2. 乖离率不能太大 (防止在远离均线处杀跌)
                        not_oversold = rsi > 35 
                        not_too_far = curr['close'] > curr['ma60'] * 0.95 
                        
                        if curr['diff'] < 0 and not_oversold and not_too_far:
                             if self.check_trigger(curr, prev, vol_mult, 'sell'):
                                 return {"type": "3S", "action": "sell", "price": curr['close'], "desc": "三卖(下跌中继)", "stop_loss": curr['high']*1.02}

        # 二买/二卖逻辑 (保持不变)
        elif st['state'] == 'WAITING_FOR_2B':
             if confirmed_pivot['type'] == -1 and confirmed_pivot['ts'] != st['last_pivot_ts']:
                if confirmed_pivot['price'] > st['last_1b_price']: 
                     if curr['close'] > confirmed_pivot['price']:
                        st['last_pivot_ts'] = confirmed_pivot['ts']
                        return {"type": "2B", "action": "buy", "price": curr['close'], "desc": "二买(回踩确认)", "stop_loss": confirmed_pivot['price']}
        
        elif st['state'] == 'WAITING_FOR_2S':
            if slope > self.SLOPE_THRESHOLD: return None
            if confirmed_pivot['type'] == 1 and confirmed_pivot['ts'] != st['last_pivot_ts']:
                if confirmed_pivot['price'] < st['last_1s_price']: 
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
        main_limit = 1000
        sub_limit = main_limit * ratio + 500
        sub_limit = min(sub_limit, 4800)

        self.data_manager.update_data(symbol, main_lvl)
        self.data_manager.update_data(symbol, sub_lvl)
        
        df_main = self.data_manager.load_data_for_analysis(symbol, main_lvl, limit=main_limit)
        df_sub = self.data_manager.load_data_for_analysis(symbol, sub_lvl, limit=sub_limit)
        
        df_main = self.calculate_indicators(df_main)
        df_sub = self.calculate_indicators(df_sub)
        
        signal = self.analyze_snapshot(symbol,main_lvl,df_main, df_sub)

        # 🚨 [新增] 运行结束，保存状态
        st_key = f"{symbol}_{main_lvl}"        
        # 🚨 [新增] 运行结束，持久化状态
        self.data_manager.save_strategy_state(st_key, self.states[st_key])        
        
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