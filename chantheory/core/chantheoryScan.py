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
    

    def analyzeEMA_snapshot(self, symbol, main_lvl, df_main, df_sub):
        """
        基于EMA均线乖离率的简单策略
        逻辑：
        1. 卖出：多头排列(7,25 > 99,255) 且 价格 > EMA7 * 1.2 (乖离20%)
        2. 买入：空头排列(7,25 < 99,255) 且 价格 < EMA7 * 0.8 (乖离20%)
        """
        # 1. 基础数据检查
        # 只要数据够计算 EMA255 即可
        if df_main is None or len(df_main) < 260: 
            return None
        
        # 2. 计算均线 (使用Pandas内置ewm函数，无需额外依赖)
        # 注意：这里假设 df_main 已经按时间排序
        close_series = df_main['close']
        
        # 1. 计算均线序7列 (注意这里需要全量序列来判断趋势，而不仅仅是最后一个值)
        ema7_series   = close_series.ewm(span=7, adjust=False).mean()
        ema25_series  = close_series.ewm(span=25, adjust=False).mean()
        ema99_series  = close_series.ewm(span=99, adjust=False).mean()
        ema255_series = close_series.ewm(span=255, adjust=False).mean()
        

        # 获取最新值
        last_p   = close_series.iloc[-2]
        curr_p     = close_series.iloc[-1]
        e7_prev   = ema7_series.iloc[-2]
        e7_curr    = ema7_series.iloc[-1]
        e25_curr   = ema25_series.iloc[-1]
        e99_curr   = ema99_series.iloc[-1]
        e99_prev   = ema99_series.iloc[-2]  # 前一根K线的EMA99
        e255_curr  = ema255_series.iloc[-1]        
                
    
          
            
        # 设定乖离阈值 (用户设定为 20%)
        is_ema99_rising = e99_curr > e99_prev 
        
        if is_ema99_rising:
            # 趋势向上：容易买(1%)，难卖(5%)
            buy_threshold = 0.005
            sell_threshold = 0.1
            trend_desc = "多头趋势"
        else:
            # 趋势向下：容易卖(1%)，难买(5%)
            buy_threshold = 0.005
            sell_threshold = 0.05
            trend_desc = "空头趋势"        

    
        #先来看下右侧信号
        if last_p < e7_prev and curr_p > e7_curr:
            return {
                "type": "EMA7_Break",
                "action": "buy",
                "price": curr_p,
                "desc": f"[{trend_desc}] 短期价格反转趋势: 当前价格反超EMA7 {e7_curr}",
                "stop_loss": curr_p * 1.05
            }   

        if last_p > e7_prev and curr_p < e7_curr:
            return {
                "type": "EMA7_Break",
                "action": "sell",
                "price": curr_p,
                "desc": f"[{trend_desc}] 短期价格反转趋势: 当前价格跌破EMA7 {e7_curr}",
                "stop_loss": curr_p * 1.05
            }                
        
        # ========================================================
        # 🔴 卖出信号逻辑 (趋势向上 + 价格暴涨远离均线)
        # ========================================================
        
        # 1. 均线多头排列验证：短期(7, 25) 必须在 长期(99, 255) 之上
        is_bull_layout = (e7_curr > e99_curr and e7_curr > e255_curr) 
        
        # 2. 乖离率验证：价格比 EMA7 高出 20%
        # 公式：Price > EMA7 * (1 + 0.2)
        # 乖离率判断：当前价 > EMA7 * (1 + sell_threshold)
        if is_bull_layout and curr_p > (e7_curr * (1 + sell_threshold)):
            return {
                "type": "EMA_S",
                "action": "sell",
                "price": curr_p,
                "desc": f"[{trend_desc}] 乖离卖出: 超过EMA7 {int(sell_threshold*100)}%",
                "stop_loss": curr_p * 1.05
            }

        
        # ========================================================
        # 🟢 买入信号逻辑 (EMA_Revert_B)
        # ========================================================
        # 条件：7和25均在99和255之下 (大趋势空头)
        is_bear_layout = (e7_curr < e99_curr and e7_curr < e255_curr) 
        
        # 乖离率判断：当前价 < EMA7 * (1 - buy_threshold)
        if is_bear_layout and curr_p < (e7_curr * (1 - buy_threshold)):
            return {
                "type": "EMA_B",
                "action": "buy",
                "price": curr_p,
                "desc": f"[{trend_desc}] 乖离买入: 低于EMA7 {int(buy_threshold*100)}%",
                "stop_loss": curr_p * 0.95
            }
                

        # 无信号
        return None    

    # ---------------------------------------------------------
    # 5. 核心分析逻辑 V39.0 (逻辑防火墙版)
    # ---------------------------------------------------------
    def analyze_snapshot(self, symbol, main_lvl, df_main, df_sub):
        if df_main is None or len(df_main) < 100: return None
        
        curr = df_main.iloc[-1]
        price = curr['close']
        
        merged_bars = self.preprocess_klines(df_main)
        bi_list = self.find_bi(merged_bars)
        
        if len(bi_list) < 5: return None
        
        # 关键变量
        last_bi = bi_list[-1]    
        compare_bi = bi_list[-3] 
        zs = self.get_zhongshu(bi_list) 
        
        # ========================================================
        # 🛡️ 优先级 0: 量化特种兵 (PanicS & RocketB)
        # ========================================================
        if price < curr['lower'] and curr['close'] < curr['open']:
             if curr['volume'] > curr['vol_ma'] * self.VOL_MULTIPLIER:
                 if curr['rsi'] > 20: 
                     # 特种兵的止损设为当前K线的高点
                     return {"type": "PanicS", "action": "sell", "price": price, 
                            "desc": "恐慌抛售(放量破下轨)", "stop_loss": curr['high']}
                            
        if price > curr['upper'] and curr['close'] > curr['open']:
             if curr['volume'] > curr['vol_ma'] * self.VOL_MULTIPLIER:
                 if curr['rsi'] < 80:
                     return {"type": "RocketB", "action": "buy", "price": price, 
                            "desc": "火箭发射(放量破上轨)", "stop_loss": curr['low']}

        # ========================================================
        # 🔴 卖点体系 (Sell Signals)
        # 🛑 核心原则：做空时，价格必须 < 止损价
        # ========================================================
        
        # 【1S: 一卖】(趋势背驰)
        if last_bi['type'] == 1: 
            if last_bi['end_val'] > compare_bi['end_val']: 
                if last_bi['macd_area'] < compare_bi['macd_area'] * self.DIVERGENCE_FACTOR: 
                    # 🛑 防火墙：确认价格没有突破结构高点
                    stop_loss = last_bi['end_val']
                    if price < stop_loss: 
                        if curr['close'] < curr['open']:
                            return {"type": "1S", "action": "sell", "price": price, 
                                   "desc": f"一卖(顶背驰)", "stop_loss": stop_loss}
        
        # 【2S: 二卖】(反弹不过高)
        if last_bi['type'] == 1:
            if last_bi['end_val'] < compare_bi['end_val']: 
                stop_loss = last_bi['end_val']
                # 🛑 防火墙
                if price < stop_loss:
                    if curr['rsi'] < 70 and curr['close'] < curr['open']:
                        return {"type": "2S", "action": "sell", "price": price, 
                               "desc": f"二卖(结构确认)", "stop_loss": stop_loss}

        # 【3S: 三卖】(离开中枢后反抽不过 ZD)
        if zs and last_bi['type'] == 1:
            if last_bi['end_val'] < zs['zd']:
                # 3S的理论止损是 ZD (中枢下沿)
                stop_loss = zs['zd'] 
                
                # 🛑 防火墙：如果价格已经涨回 ZD 上方，说明不是3卖，是中枢震荡
                if price < stop_loss:
                    if curr['close'] < curr['open']:
                        return {"type": "3S", "action": "sell", "price": price, 
                               "desc": f"三卖(确认跌势)", "stop_loss": stop_loss}

        # ========================================================
        # 🟢 买点体系 (Buy Signals)
        # 🛑 核心原则：做多时，价格必须 > 止损价
        # ========================================================

        # 【1B: 一买】(底背驰)
        if last_bi['type'] == -1:
            if last_bi['end_val'] < compare_bi['end_val']: 
                if last_bi['macd_area'] < compare_bi['macd_area'] * self.DIVERGENCE_FACTOR: 
                    stop_loss = last_bi['end_val']
                    # 🛑 防火墙：确认价格没有跌破结构低点 (虽然底背驰通常是在新低时发，但这里指的是笔结束后的确认)
                    if price > stop_loss:
                        if curr['close'] > curr['open']:
                            return {"type": "1B", "action": "buy", "price": price, 
                                   "desc": f"一买(底背驰)", "stop_loss": stop_loss}

        # 【2B: 二买】(回踩不破低)
        if last_bi['type'] == -1:
            if last_bi['end_val'] > compare_bi['end_val']: 
                stop_loss = last_bi['end_val']
                # 🛑 防火墙
                if price > stop_loss:
                    if curr['rsi'] > 50 and curr['close'] > curr['open']: # 稍微加强RSI要求
                        return {"type": "2B", "action": "buy", "price": price, 
                               "desc": f"二买(结构确认)", "stop_loss": stop_loss}

        # 【3B: 三买】(离开中枢后回踩不破 ZG)
        if zs and last_bi['type'] == -1:
            if last_bi['end_val'] > zs['zg']:
                stop_loss = zs['zg']
                # 🛑 防火墙：如果价格已经跌回 ZG 下方，说明不是3买
                if price > stop_loss:
                    if curr['close'] > curr['open']:
                        return {"type": "3B", "action": "buy", "price": price, 
                               "desc": f"三买(空中加油)", "stop_loss": stop_loss}

        return None

    def detect_signals(self, symbol, main_lvl='30m', sub_lvl='5m'):
        try:
            self.data_manager.update_data(symbol, main_lvl)
            df_main = self.data_manager.load_data_for_analysis(symbol, main_lvl, limit=1000)
            df_main = self.calculate_indicators(df_main)
            # signal = self.analyze_snapshot(symbol, main_lvl, df_main, None)
            signal = self.analyzeEMA_snapshot(symbol, main_lvl, df_main,None)
            
            if signal:
                return self.print_signal(symbol, signal['desc'], main_lvl, sub_lvl, 
                                       signal['price'], signal['stop_loss'], is_buy=(signal['action']=='buy'))
        except Exception as e:
            pass
        return ""

    def print_signal(self, symbol, type_name, main, sub, price, stop_loss, is_buy=True):
        emoji = "🚀" if is_buy else "🌊" 
        action = "做多" if is_buy else "做空"
        mess = f"{emoji} [均线乖离-{action}] {symbol} ({main}) | {type_name}\n   现价: {price} | 止损: {stop_loss:.4f}\n"
        print(mess)
        return mess