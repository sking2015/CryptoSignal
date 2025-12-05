import pandas as pd
import numpy as np
from hyperliquidDataMgr import MarketDataManager
import traceback
import asyncio
from RobotNotifier import send_message_async
from datetime import datetime

class ChanLunStrategy:
    def __init__(self):
        self.data_manager = MarketDataManager()
        
    def calculate_indicators(self, df):
        """计算缠论辅助指标：MACD + 均线系统"""
        if df is None or len(df) < 60: return None
        
        # MACD (12, 26, 9)
        df['ema_fast'] = df['close'].ewm(span=12, adjust=False).mean()
        df['ema_slow'] = df['close'].ewm(span=26, adjust=False).mean()
        df['diff'] = df['ema_fast'] - df['ema_slow']
        df['dea'] = df['diff'].ewm(span=9, adjust=False).mean()
        df['macd'] = 2 * (df['diff'] - df['dea'])
        
        # 均线系统 (用于辅助判断三买的强趋势)
        df['ma60'] = df['close'].rolling(window=60).mean()
        return df

    def detect_signals(self, symbol, main_lvl='30m', sub_lvl='5m'):
        """
        全面扫描：一买/卖、二买/卖、三买/卖
        """
        # 1. 数据准备
        self.data_manager.update_data(symbol, main_lvl)
        self.data_manager.update_data(symbol, sub_lvl)
        
        df_main = self.data_manager.load_data_for_analysis(symbol, main_lvl, limit=300)
        df_sub = self.data_manager.load_data_for_analysis(symbol, sub_lvl, limit=300)
        
        if df_main is None or df_sub is None: return

        df_main = self.calculate_indicators(df_main)
        df_sub = self.calculate_indicators(df_sub)

        
        # 因为 calculate_indicators 可能会因为数据不足60条而返回 None
        if df_main is None or df_sub is None:
            print(f"数据不足，跳过 {symbol} {main_lvl}/{sub_lvl}") # 可选：打印日志调试
            return ""
              
        
        # 2. 获取当前分型状态
        curr = df_main.iloc[-1]
        prev = df_main.iloc[-2]
        prev2 = df_main.iloc[-3]

        # 基础分型判断
        is_bottom_fractal = (prev['low'] < prev2['low']) and (prev['low'] < curr['low'])
        is_top_fractal = (prev['high'] > prev2['high']) and (prev['high'] > curr['high'])

        # ==========================================
        # 🟢 买点扫描 (Buy Signals)
        # ==========================================
        signal_str = ""
        if is_bottom_fractal:
            # --- 一买 (1B): 底背驰 ---
            if prev['diff'] < 0 and self.check_divergence(df_sub, mode='buy'):
                signal_str += self.print_signal(symbol, "一买 (趋势背驰)", main_lvl, sub_lvl, curr['close'], prev['low'])

            # --- 二买 (2B): 不创新低 ---
            # 逻辑: 当前底分型 > 前一个显著低点, 且中间MACD上过零轴(代表有一笔上涨)
            if self.check_2nd_buy(df_main):
                 # 二买有时也需要次级别背驰辅助，或者是次级别双底
                if self.check_divergence(df_sub, mode='buy') or self.check_2nd_buy(df_sub): 
                    signal_str += self.print_signal(symbol, "二买 (回踩确认)", main_lvl, sub_lvl, curr['close'], prev['low'])

            # --- 三买 (3B): 零轴上方回踩/均线不破 ---
            # 逻辑: 价格在MA60上方，MACD回抽零轴附近
            if self.check_3rd_buy(df_main):
                signal_str +=  self.print_signal(symbol, "三买 (趋势中继)", main_lvl, sub_lvl, curr['close'], prev['low'])

        # ==========================================
        # 🔴 卖点扫描 (Sell Signals)
        # ==========================================
        if is_top_fractal:
            # --- 一卖 (1S): 顶背驰 ---
            if prev['diff'] > 0 and self.check_divergence(df_sub, mode='sell'):
                signal_str += self.print_signal(symbol, "一卖 (趋势力竭)", main_lvl, sub_lvl, curr['close'], prev['high'], is_buy=False)

            # --- 二卖 (2S): 不创新高 ---
            if self.check_2nd_sell(df_main):
                if self.check_divergence(df_sub, mode='sell') or self.check_2nd_sell(df_sub):
                    signal_str += self.print_signal(symbol, "二卖 (反抽确认)", main_lvl, sub_lvl, curr['close'], prev['high'], is_buy=False)

            # --- 三卖 (3S): 零轴下方反抽/均线压制 ---
            if self.check_3rd_sell(df_main):
                signal_str += self.print_signal(symbol, "三卖 (下跌中继)", main_lvl, sub_lvl, curr['close'], prev['high'], is_buy=False)

        return signal_str

    def print_signal(self, symbol, type_name, main, sub, price, stop_loss, is_buy=True):
        emoji = "🟢" if is_buy else "🔴"
        action = "买入" if is_buy else "卖出"
        ret = ""
        mess = f"{emoji} [{action}信号-{type_name}] {symbol} {emoji}"
        print(mess)
        ret += mess
        ret += "\n"
        
        mess = f"   - 级别: 主({main}) + 次({sub})"
        print(mess)
        ret += mess
        ret += "\n"

        mess = f"   - 现价: {price}"
        print(mess)
        ret += mess
        ret += "\n"

        mess = f"   - 🛑 理论止损: {stop_loss}"
        print(mess)
        ret += mess
        ret += "\n"        

        mess = "-" * 50
        print(mess)
        ret += mess
        ret += "\n"         

        return ret           

    # ----------------------------------------------------------------
    # 核心逻辑判断函数
    # ----------------------------------------------------------------

    def check_divergence(self, df, mode='buy'):
        """通用背驰检测 (一买/一卖)"""
        idx = len(df) - 1
        if mode == 'buy':
            # 寻找底背驰
            while idx > 0 and df['macd'].iloc[idx] > 0: idx -= 1 # 跳过红柱
            if idx <= 10: return False
            
            # 当前绿柱段
            curr_min_price = float('inf')
            curr_min_diff = float('inf')
            while idx > 0 and df['macd'].iloc[idx] <= 0:
                curr_min_price = min(curr_min_price, df['low'].iloc[idx])
                curr_min_diff = min(curr_min_diff, df['diff'].iloc[idx])
                idx -= 1
            
            # 中间红柱段 (必须有反弹)
            has_rebound = False
            while idx > 0 and df['macd'].iloc[idx] > 0:
                has_rebound = True
                idx -= 1
            if not has_rebound: return False
            
            # 前一绿柱段
            prev_min_price = float('inf')
            prev_min_diff = float('inf')
            while idx > 0 and df['macd'].iloc[idx] <= 0:
                prev_min_price = min(prev_min_price, df['low'].iloc[idx])
                prev_min_diff = min(prev_min_diff, df['diff'].iloc[idx])
                idx -= 1
                
            return curr_min_price < prev_min_price and curr_min_diff > prev_min_diff

        elif mode == 'sell':
            # 寻找顶背驰
            while idx > 0 and df['macd'].iloc[idx] <= 0: idx -= 1 # 跳过绿柱
            if idx <= 10: return False
            
            curr_max_price = float('-inf')
            curr_max_diff = float('-inf')
            while idx > 0 and df['macd'].iloc[idx] > 0:
                curr_max_price = max(curr_max_price, df['high'].iloc[idx])
                curr_max_diff = max(curr_max_diff, df['diff'].iloc[idx])
                idx -= 1
            
            has_pullback = False
            while idx > 0 and df['macd'].iloc[idx] <= 0:
                has_pullback = True
                idx -= 1
            if not has_pullback: return False
            
            prev_max_price = float('-inf')
            prev_max_diff = float('-inf')
            while idx > 0 and df['macd'].iloc[idx] > 0:
                prev_max_price = max(prev_max_price, df['high'].iloc[idx])
                prev_max_diff = max(prev_max_diff, df['diff'].iloc[idx])
                idx -= 1
                
            return curr_max_price > prev_max_price and curr_max_diff < prev_max_diff
        return False

    def check_2nd_buy(self, df):
        """
        二买逻辑：
        1. 当前是底分型 (外部已判断)
        2. 当前底 > 前一个显著底 (Higher Low)
        3. 两个底之间 MACD 曾经上穿过零轴 (说明有一波像样的反弹)
        """
        curr_low = df['low'].iloc[-2] # 分型底点
        
        # 向回找前一个底分型区域 (简化：找最近60根K线的最低点)
        lookback = 60
        if len(df) < lookback: return False
        
        recent_data = df.iloc[-lookback:-5] # 避开当前的底
        min_prev_low = recent_data['low'].min()
        min_index = recent_data['low'].idxmin()
        
        # 条件1: 必须是 Higher Low
        if curr_low <= min_prev_low: 
            return False
            
        # 条件2: 两个低点之间，Diff 必须上穿过 0 轴 (确保之前是一买后的反弹)
        # 从 min_index 到 当前
        interim_data = df.loc[min_index : df.index[-2]]
        if interim_data['diff'].max() > 0:
            return True
            
        return False

    def check_2nd_sell(self, df):
        """二卖逻辑：Lower High + 中间MACD下穿零轴"""
        curr_high = df['high'].iloc[-2]
        
        lookback = 60
        if len(df) < lookback: return False
        
        recent_data = df.iloc[-lookback:-5]
        max_prev_high = recent_data['high'].max()
        max_index = recent_data['high'].idxmax()
        
        if curr_high >= max_prev_high:
            return False
            
        interim_data = df.loc[max_index : df.index[-2]]
        if interim_data['diff'].min() < 0:
            return True
            
        return False

    def check_3rd_buy(self, df):
        """
        三买逻辑 (简化版)：
        1. 价格强势站在长期均线(MA60)之上
        2. MACD 回抽零轴附近 (Diff > 0 但接近 0，或微破)
        """
        curr = df.iloc[-2]
        
        # 1. 强趋势: 收盘价在 MA60 之上，且 MA60 向上 (这里只判断价格)
        if curr['low'] < curr['ma60']: 
            return False # 跌破均线太深，不是三买
            
        # 2. MACD 回抽: Diff 必须大于 0 (或非常接近)，且 DEA 向下
        # 所谓的"飞吻"或"湿吻"
        if curr['diff'] > 0 and curr['diff'] < (curr['std'] if 'std' in curr else 100): 
            # 简单判断：Diff 是正的，但是比之前的高点回落了
            # 检查最近MACD是不是在缩短
            if df['macd'].iloc[-2] < df['macd'].iloc[-3]: # 绿柱或红柱缩短
                return True
                
        return False

    def check_3rd_sell(self, df):
        """三卖逻辑"""
        curr = df.iloc[-2]
        
        # 1. 弱趋势: 价格被 MA60 压制
        if curr['high'] > curr['ma60']:
            return False
            
        # 2. MACD 反抽零轴: Diff < 0
        if curr['diff'] < 0:
            if df['macd'].iloc[-2] > df['macd'].iloc[-3]: # 红柱或绿柱缩短
                return True
        return False

async def main():
    scanner = ChanLunStrategy()
    coins = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE', 'BNB']
    
    # 级别设置：可以根据需要调整
    main_lv = ['30m', '1h', '4h', '1d']
    sub_lv = ['5m', '15m', '1h', '4h']

    print("启动缠论全买卖点扫描系统 (1/2/3 类买卖点)...")
    
    # for coin in coins:
    #     try:
    #         # 扫描前4个级别组合
    #         for i in range(len(main_lv)): 
    #             scanner.detect_signals(coin, main_lv[i], sub_lv[i])
    #             await asyncio.sleep(0.5) 
                
    #     except Exception as e:
    #         print(f"处理 {coin} 时出错: {e}")
    #         print(traceback.format_exc())    

    last_run_hour = -1
    last_run_half = -1  # 0 表示整点，1 表示半点

    while True:
        now = datetime.now()
        minute = now.minute
        
        # 判断当前是否是整点/半点
        current_half = 0 if minute < 30 else 1 if minute >= 30 else None

        if last_run_hour != now.hour or last_run_half != current_half:       
            
            #每一次检查时清空消息
            msgstr = ""
            for coin in coins:
                try:
                    # 扫描前4个级别组合
                    for i in range(len(main_lv)): 
                        msgstr += scanner.detect_signals(coin, main_lv[i], sub_lv[i])
                        await asyncio.sleep(0.5) 
                        
                except Exception as e:
                    print(f"处理 {coin} 时出错: {e}")
                    print(traceback.format_exc())  


            if msgstr != "":
                 await send_message_async(msgstr)

            # 更新上一次执行记录
            last_run_hour = now.hour
            last_run_half = current_half            

        # 每秒检查一次，保证不会漏
        await asyncio.sleep(1)             

if __name__ == "__main__":
    asyncio.run(main())