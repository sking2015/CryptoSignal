import pandas as pd
import numpy as np
from hyperliquidDataMgr import MarketDataManager
import traceback


class ChanLunStrategy:
    def __init__(self):
        self.data_manager = MarketDataManager()
        
    def calculate_indicators(self, df):
        """计算缠论辅助指标：MACD"""
        if df is None or len(df) < 30: return None
        
        # 缠论标准配置：MACD参数(12,26,9)
        # 来源: MACD对背驰的辅助判断 [3]
        fast, slow, signal = 12, 26, 9
        df['ema_fast'] = df['close'].ewm(span=fast, adjust=False).mean()
        df['ema_slow'] = df['close'].ewm(span=slow, adjust=False).mean()
        df['diff'] = df['ema_fast'] - df['ema_slow']
        df['dea'] = df['diff'].ewm(span=signal, adjust=False).mean()
        df['macd'] = 2 * (df['diff'] - df['dea'])
        return df

    def detect_signals(self, symbol, main_lvl='30m', sub_lvl='5m'):
        """
        执行区间套逻辑：
        1. 更新主级别和次级别数据到数据库
        2. 读取本地数据
        3. 判断主级别底分型 + 次级别背驰
        """
        # --- 步骤1：增量更新数据 ---
        self.data_manager.update_data(symbol, main_lvl)
        self.data_manager.update_data(symbol, sub_lvl)
        
        # --- 步骤2：从本地读取数据 ---
        df_main = self.data_manager.load_data_for_analysis(symbol, main_lvl, limit=300)
        df_sub = self.data_manager.load_data_for_analysis(symbol, sub_lvl, limit=300)
        
        if df_main is None or df_sub is None: return

        df_main = self.calculate_indicators(df_main)
        df_sub = self.calculate_indicators(df_sub)

        # --- 步骤3：缠论逻辑判断 ---
        
        # A. 主级别 (30m) 寻找潜在转折 (底分型 + 空头趋势)
        # 缠论定义：底分型是中间低点最低 [4]
        curr_main = df_main.iloc[-1]
        prev_main = df_main.iloc[-2]
        prev2_main = df_main.iloc[-3]
        
        # 简单的底分型判断：中间K线的低点最低
        is_bottom_fractal = (prev_main['low'] < prev2_main['low']) and \
                            (prev_main['low'] < curr_main['low'])
        
        # 必须是在下跌趋势中 (MACD DIFF < 0) 才有抄底意义 [5]
        is_downtrend = prev_main['diff'] < 0
        
        if is_bottom_fractal and is_downtrend:
            # B. 次级别 (5m) 寻找背驰 (区间套定位) [2]
            # 逻辑：价格创新低，但MACD力度(绿柱或黄白线)不创新低
            # 来源: 第一类买点都是在0轴之下背驰形成的 [3]
            
            if self.check_divergence(df_sub):
                print(f"🔥🔥 发现缠论一买信号: {symbol} 🔥🔥")
                print(f"   - 主级别 ({main_lvl}): 底分型形成，空头趋势")
                print(f"   - 次级别 ({sub_lvl}): 确认底背驰 (MACD力度衰竭)")
                print(f"   - 时间: {curr_main['timestamp']}")
                print("-" * 50)

    def check_divergence(self, df):
        """
        在次级别数据中寻找背驰
        比较最近两段下跌的力度
        """
        # 简化算法：寻找最近两个死叉(绿柱区域)的最低点比较
        # 实际缠论需要画笔画线段，这里用MACD红绿柱模拟线段 [6]
        
        # 1. 找到当前绿柱堆的最低价和最低MACD值
        # 向回找，直到 macd > 0 (红柱)
        idx = len(df) - 1
        while idx > 0 and df['macd'].iloc[idx] > 0: # 跳过当前的红柱(如果有)
            idx -= 1
            
        if idx <= 10: return False # 数据不够
        
        # 当前下跌段
        curr_min_price = float('inf')
        curr_min_diff = float('inf')
        
        while idx > 0 and df['macd'].iloc[idx] <= 0:
            curr_min_price = min(curr_min_price, df['low'].iloc[idx])
            curr_min_diff = min(curr_min_diff, df['diff'].iloc[idx])
            idx -= 1
            
        # 中间间隔段 (必须有红柱回拉，才算两段趋势的连接) [7]
        has_rebound = False
        while idx > 0 and df['macd'].iloc[idx] > 0:
            has_rebound = True
            idx -= 1
            
        if not has_rebound: return False # 没有反弹，说明是一段下跌，无法比较
        
        # 前一下跌段
        prev_min_price = float('inf')
        prev_min_diff = float('inf')
        
        while idx > 0 and df['macd'].iloc[idx] <= 0:
            prev_min_price = min(prev_min_price, df['low'].iloc[idx])
            prev_min_diff = min(prev_min_diff, df['diff'].iloc[idx])
            idx -= 1
            
        # 背驰判断标准：
        # 1. 价格创新低 (趋势的延续) [1]
        # 2. MACD黄白线没有创新低 (力度的衰竭) [5]
        if curr_min_price < prev_min_price and curr_min_diff > prev_min_diff:
            return True
            
        return False

# ==========================================
# 执行脚本
# ==========================================
if __name__ == "__main__":
    scanner = ChanLunStrategy()
    coins = ['BTC', 'ETH', 'SOL', 'DOGE']
    
    print("启动缠论量化扫描系统 (SQLite增强版)...")
    # 循环扫描
    for coin in coins:
        try:
            scanner.detect_signals(coin, '30m', '5m')
        except Exception as e:
            print(f"处理 {coin} 时出错: {e}")
            print(traceback.format_exc()) 
            
    print("扫描结束。")