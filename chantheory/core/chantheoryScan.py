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
        # 🎛️ V38.0 缠论正宗 + 量化特种兵参数
        # ==============================================================================
        # 1. 缠论结构参数
        self.MIN_K_IN_BI = 4       # 成笔最小K线数
        self.BI_LOOKBACK = 3       # 中枢构建笔数
        self.DIVERGENCE_FACTOR = 0.9 # 背驰判定因子 (后一笔力度 < 前一笔 * 0.9)
        
        # 2. 辅助指标参数 (用于过滤假信号)
        self.RSI_HIGH = 75         # 1卖/2卖 辅助压力位
        self.RSI_LOW = 25          # 1买/2买 辅助支撑位

        # 3. 量化特种兵参数 (波动率突破)
        self.BOLL_WINDOW = 20      
        self.BOLL_STD = 2.0        
        self.VOL_MULTIPLIER = 1.5  
        # ==============================================================================

    # ---------------------------------------------------------
    # 1. 基础处理：K线包含合并 (缠论基石)
    # ---------------------------------------------------------
    def preprocess_klines(self, df):
        if df is None or len(df) < 5: return []
        
        bars = []
        # 使用 itertuples 提高遍历速度
        for row in df.itertuples():
            bars.append({
                'ts': row.timestamp, 
                'h': row.high, 'l': row.low, 'o': row.open, 'c': row.close, 'v': row.volume,
                'macd': getattr(row, 'macd', 0), 
                'rsi': getattr(row, 'rsi', 50),
                'upper': getattr(row, 'upper', 0), 
                'lower': getattr(row, 'lower', 0), 
                'vol_ma': getattr(row, 'vol_ma', 0) 
            })
            
        merged_bars = []
        if not bars: return []
        merged_bars.append(bars[0])
        direction_up = True 
        
        for i in range(1, len(bars)):
            curr = bars[i]
            prev = merged_bars[-1]
            
            # 包含关系处理：High <= High_prev 且 Low >= Low_prev (或者反之)
            is_included = (curr['h'] <= prev['h'] and curr['l'] >= prev['l']) or \
                          (curr['h'] >= prev['h'] and curr['l'] <= prev['l'])
            
            if is_included:
                if direction_up: # 向上合并：高点取高，低点取高
                    prev['h'] = max(curr['h'], prev['h']); prev['l'] = max(curr['l'], prev['l'])
                else:            # 向下合并：高点取低，低点取低
                    prev['h'] = min(curr['h'], prev['h']); prev['l'] = min(curr['l'], prev['l'])
                
                prev['c'] = curr['c']; prev['v'] += curr['v']; prev['end_ts'] = curr['ts']
                # 指标跟随最新K线
                prev['macd'] = curr['macd']; prev['rsi'] = curr['rsi']
                prev['upper'] = curr['upper']; prev['lower'] = curr['lower']; prev['vol_ma'] = curr['vol_ma']
            else:
                # 确定新方向
                if curr['h'] > prev['h'] and curr['l'] > prev['l']: direction_up = True
                elif curr['h'] < prev['h'] and curr['l'] < prev['l']: direction_up = False
                curr['end_ts'] = curr['ts']
                merged_bars.append(curr)
        return merged_bars

    # ---------------------------------------------------------
    # 2. 找笔 (Bi) & 力度计算 (Dynamics)
    # ---------------------------------------------------------
    def find_bi(self, merged_bars):
        if len(merged_bars) < self.MIN_K_IN_BI + 1: return []
        fx_list = []
        
        # 识别顶底分型
        for i in range(1, len(merged_bars)-1):
            prev, curr, next_b = merged_bars[i-1], merged_bars[i], merged_bars[i+1]
            if curr['h'] > prev['h'] and curr['h'] > next_b['h']:
                fx_list.append({'type': 'top', 'idx': i, 'val': curr['h'], 'bar': curr})
            elif curr['l'] < prev['l'] and curr['l'] < next_b['l']:
                fx_list.append({'type': 'bot', 'idx': i, 'val': curr['l'], 'bar': curr})
        
        bi_list = []
        if not fx_list: return []
        curr_fx = fx_list[0]
        
        # 连笔逻辑
        for i in range(1, len(fx_list)):
            next_fx = fx_list[i]
            # 必须是一顶一底交替
            if curr_fx['type'] == next_fx['type']:
                # 连续同向取极值
                if curr_fx['type'] == 'top':
                    if next_fx['val'] > curr_fx['val']: curr_fx = next_fx
                else:
                    if next_fx['val'] < curr_fx['val']: curr_fx = next_fx
                continue
            
            # 成笔条件：中间间隔 K 线数量达标
            if next_fx['idx'] - curr_fx['idx'] >= (self.MIN_K_IN_BI - 1):
                # === 动力学核心：计算 MACD 面积 ===
                macd_area = 0
                for k in range(curr_fx['idx'], next_fx['idx'] + 1):
                    macd_area += abs(merged_bars[k]['macd'])
                
                bi_list.append({
                    'start_idx': curr_fx['idx'], 'end_idx': next_fx['idx'],
                    'start_val': curr_fx['val'], 'end_val': next_fx['val'],
                    'type': 1 if curr_fx['type'] == 'bot' else -1, # 1=向上笔, -1=向下笔
                    'start_ts': curr_fx['bar']['ts'], 'end_ts': next_fx['bar']['end_ts'],
                    'macd_area': macd_area 
                })
                curr_fx = next_fx
        return bi_list

    # ---------------------------------------------------------
    # 3. 找中枢 (ZhongShu) - 几何学核心
    # ---------------------------------------------------------
    def get_zhongshu(self, bi_list):
        if len(bi_list) < self.BI_LOOKBACK: return None
        # 取最后三笔构建中枢
        segments = bi_list[-self.BI_LOOKBACK:] 
        # ZG: 三笔高点中的最小值
        zg = min([max(b['start_val'], b['end_val']) for b in segments]) 
        # ZD: 三笔低点中的最大值
        zd = max([min(b['start_val'], b['end_val']) for b in segments])  
        
        if zg > zd: 
            return {'zg': zg, 'zd': zd}
        return None

    # ---------------------------------------------------------
    # 4. 指标计算
    # ---------------------------------------------------------
    def calculate_indicators(self, df):
        if df is None or len(df) < 100: return None
        df = df.copy()
        
        # 均线
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
        
        # 布林带 & 成交量 (为量化特种兵服务)
        std = df['close'].rolling(window=self.BOLL_WINDOW).std()
        df['upper'] = df['ma20'] + (std * self.BOLL_STD)
        df['lower'] = df['ma20'] - (std * self.BOLL_STD)
        df['vol_ma'] = df['volume'].rolling(window=20).mean()

        return df

    # ---------------------------------------------------------
    # 5. 核心分析逻辑 V38.0 (The Trinity)
    # ---------------------------------------------------------
    def analyze_snapshot(self, symbol, main_lvl, df_main, df_sub):
        if df_main is None or len(df_main) < 100: return None
        
        curr = df_main.iloc[-1]
        prev = df_main.iloc[-2]
        price = curr['close']
        
        merged_bars = self.preprocess_klines(df_main)
        bi_list = self.find_bi(merged_bars)
        
        if len(bi_list) < 5: return None
        
        # 关键变量定义
        last_bi = bi_list[-1]    # 正在走或刚走完的一笔
        prev_bi = bi_list[-2]    # 上一笔
        compare_bi = bi_list[-3] # 同向对比笔 (用于背驰比较)
        zs = self.get_zhongshu(bi_list) # 最近的一个中枢
        
        # ========================================================
        # 🛡️ 优先级 0: 量化特种兵 (PanicS & RocketB)
        # 逻辑：非结构性行情，直接根据动能和波动率干预
        # ========================================================
        
        # PanicS (恐慌瀑布): 放量跌破布林下轨
        if price < curr['lower'] and curr['close'] < curr['open']:
             if curr['volume'] > curr['vol_ma'] * self.VOL_MULTIPLIER:
                 # 避免在地板上做空 (RSI > 20)
                 if curr['rsi'] > 20: 
                     return {"type": "PanicS", "action": "sell", "price": price, 
                            "desc": "恐慌抛售(放量破下轨)", "stop_loss": curr['high']}
                            
        # RocketB (火箭发射): 放量突破布林上轨
        if price > curr['upper'] and curr['close'] > curr['open']:
             if curr['volume'] > curr['vol_ma'] * self.VOL_MULTIPLIER:
                 if curr['rsi'] < 80:
                     return {"type": "RocketB", "action": "buy", "price": price, 
                            "desc": "火箭发射(放量破上轨)", "stop_loss": curr['low']}

        # ========================================================
        # 🔴 卖点体系 (1S, 2S, 3S) - 刚好反过来
        # ========================================================
        
        # 【1S: 第一类卖点】(趋势背驰)
        # 条件：向上笔 + 创新高 + 面积背驰
        if last_bi['type'] == 1: 
            if last_bi['end_val'] > compare_bi['end_val']: # 创新高
                if last_bi['macd_area'] < compare_bi['macd_area'] * self.DIVERGENCE_FACTOR: # 动力衰竭
                    # 辅助确认：K线滞涨
                    if curr['close'] < curr['open']:
                        return {"type": "1S", "action": "sell", "price": price, 
                               "desc": f"一卖(顶背驰) 力度衰竭", "stop_loss": last_bi['end_val']}
        
        # 【2S: 第二类卖点】(结构确认)
        # 条件：向上笔 + 不创新高 (Lower High)
        if last_bi['type'] == 1:
            if last_bi['end_val'] < compare_bi['end_val']: # 没过前高
                # 辅助确认：RSI 没过热
                if curr['rsi'] < 70 and curr['close'] < curr['open']:
                    return {"type": "2S", "action": "sell", "price": price, 
                           "desc": f"二卖(反弹不过高)", "stop_loss": last_bi['end_val']}

        # 【3S: 第三类卖点】(中枢破坏/反抽)
        # 条件：中枢存在 + 向上笔 + 高点 < ZD (根本摸不到中枢下沿)
        if zs and last_bi['type'] == 1:
            if last_bi['end_val'] < zs['zd']:
                # 这是一个极其危险的信号，往往对应主跌浪
                if curr['close'] < curr['open']:
                    return {"type": "3S", "action": "sell", "price": price, 
                           "desc": f"三卖(确认跌势) 阻力:{zs['zd']:.2f}", "stop_loss": zs['zd']}

        # ========================================================
        # 🟢 买点体系 (1B, 2B, 3B)
        # ========================================================

        # 【1B: 第一类买点】(趋势背驰)
        # 条件：向下笔 + 创新低 + 面积背驰
        if last_bi['type'] == -1:
            if last_bi['end_val'] < compare_bi['end_val']: # 创新低
                if last_bi['macd_area'] < compare_bi['macd_area'] * self.DIVERGENCE_FACTOR: # 动力衰竭
                    # 辅助确认：K线止跌 (阳包阴或下影线)
                    if curr['close'] > curr['open']:
                        return {"type": "1B", "action": "buy", "price": price, 
                               "desc": f"一买(底背驰) 力度衰竭", "stop_loss": last_bi['end_val']}

        # 【2B: 第二类买点】(结构确认)
        # 条件：向下笔 + 不创新低 (Higher Low)
        if last_bi['type'] == -1:
            if last_bi['end_val'] > compare_bi['end_val']: # 没破前低
                # 辅助确认：RSI 抬头
                if curr['rsi'] > prev['rsi'] and curr['close'] > curr['open']:
                    return {"type": "2B", "action": "buy", "price": price, 
                           "desc": f"二买(回踩不破低)", "stop_loss": last_bi['end_val']}

        # 【3B: 第三类买点】(中枢破坏/回踩)
        # 条件：中枢存在 + 向下笔 + 低点 > ZG (回踩不进中枢上沿)
        if zs and last_bi['type'] == -1:
            if last_bi['end_val'] > zs['zg']:
                # 这是主升浪的特征
                if curr['close'] > curr['open']:
                    return {"type": "3B", "action": "buy", "price": price, 
                           "desc": f"三买(空中加油) 支撑:{zs['zg']:.2f}", "stop_loss": zs['zg']}

        return None

    def detect_signals(self, symbol, main_lvl='30m', sub_lvl='5m'):
        try:
            self.data_manager.update_data(symbol, main_lvl)
            df_main = self.data_manager.load_data_for_analysis(symbol, main_lvl, limit=1000)
            df_main = self.calculate_indicators(df_main)
            signal = self.analyze_snapshot(symbol, main_lvl, df_main, None)
            
            if signal:
                return self.print_signal(symbol, signal['desc'], main_lvl, sub_lvl, 
                                       signal['price'], signal['stop_loss'], is_buy=(signal['action']=='buy'))
        except Exception as e:
            pass
        return ""

    def print_signal(self, symbol, type_name, main, sub, price, stop_loss, is_buy=True):
        emoji = "🚀" if is_buy else "🌊" 
        action = "做多" if is_buy else "做空"
        mess = f"{emoji} [缠论-{action}] {symbol} ({main}) | {type_name}\n   现价: {price} | 止损: {stop_loss:.4f}\n"
        print(mess)
        return mess