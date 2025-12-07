import sqlite3
import requests
import time
import pandas as pd


class MarketDataManager:
    def __init__(self, db_path='hyperliquid_data.db'):
        self.db_path = db_path
        self.init_db()
        self.base_url = "https://api.hyperliquid.xyz/info"

    def init_db(self):
        """初始化数据库表结构"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        # 创建K线表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS klines (
                symbol TEXT,
                interval TEXT,
                timestamp INTEGER,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                PRIMARY KEY (symbol, interval, timestamp)
            )
        ''')
        conn.commit()
        conn.close()

    def get_db_status(self, symbol, interval):
        """
        获取数据库状态
        返回: (count, min_ts, max_ts)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM klines WHERE symbol = ? AND interval = ?", 
            (symbol, interval)
        )
        result = cursor.fetchone()
        conn.close()
        
        # result 格式: (count, min_ts, max_ts)
        # 如果没有数据: (0, None, None)
        if result[0] == 0:
            return 0, 0, 0
        return result

    def fetch_from_api(self, symbol, interval, start_time):
        """从 Hyperliquid API 拉取数据"""
        # print(f"   ☁️ [API] 请求 {symbol} {interval} (Start: {pd.to_datetime(start_time, unit='ms')})...")
        try:
            payload = {
                "type": "candleSnapshot",
                "req": {
                    "coin": symbol,
                    "interval": interval,
                    "startTime": int(start_time)
                }
            }
            # 增加重试机制
            for _ in range(3):
                try:
                    response = requests.post(self.base_url, json=payload, headers={"Content-Type": "application/json"}, timeout=15)
                    if response.status_code == 200:
                        data = response.json()
                        if not data: return []
                        
                        formatted_data = []
                        for k in data:
                            formatted_data.append((
                                symbol, interval, int(k['t']), 
                                float(k['o']), float(k['h']), float(k['l']), float(k['c']), float(k['v'])
                            ))
                        return formatted_data
                    elif response.status_code == 429:
                        time.sleep(1) # 限流等待
                        continue
                except requests.exceptions.RequestException:
                    time.sleep(0.5)
                    continue
            return []
            
        except Exception as e:
            print(f"API请求失败: {e}")
            return []

    def save_data(self, data):
        """批量保存数据 (自动去重)"""
        if not data: return
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.executemany(
            "INSERT OR IGNORE INTO klines VALUES (?,?,?,?,?,?,?,?)", 
            data
        )
        conn.commit()
        conn.close()

    def parse_interval_to_ms(self, interval):
        """解析周期为毫秒数"""
        unit = interval[-1]
        try:
            val = int(interval[:-1])
        except:
            val = 1
            
        if unit == 'm': return val * 60 * 1000
        elif unit == 'h': return val * 60 * 60 * 1000
        elif unit == 'd': return val * 24 * 60 * 60 * 1000
        elif unit == 'w': return val * 7 * 24 * 60 * 60 * 1000
        return 60000 # 默认 1m

    def update_data(self, symbol, interval, force_lookback_days=None):
        """
        智能更新数据:
        1. 检查库存，如果太少，自动拉取深层历史
        2. 增量更新最新数据
        """
        count, min_ts, max_ts = self.get_db_status(symbol, interval)
        now_ts = int(time.time() * 1000)
        
        # --- 策略 A: 历史回补 (Backfill) ---
        # 判定标准: 数据少于 400 条 (保证 MA60, MA120 等指标稳定) 且 以前没有拉取过足够老的数据
        # Hyperliquid 一次最多给 5000 条，我们尽可能多要
        
        need_backfill = False
        
        if count == 0:
            need_backfill = True
        elif count < 400:
            # 如果数据少于400条，检查一下 min_ts 是否足够老
            # 计算 1000 根K线对应的时间跨度
            interval_ms = self.parse_interval_to_ms(interval)
            target_span = 1000 * interval_ms
            
            # 如果最早的数据 比 (现在 - 1000根) 还要新，说明缺历史
            if (now_ts - min_ts) < target_span:
                need_backfill = True
                print(f"📉 {symbol} {interval} 数据量不足 ({count}条)，正在补充历史...")

        if need_backfill:
            # 策略: 直接请求 API 允许的最大范围 (例如请求 5000 根之前的时刻)
            # Hyperliquid max limit ~5000 candles
            interval_ms = self.parse_interval_to_ms(interval)
            # 向前推 5000 根 (或者用户指定的 lookback)
            days = force_lookback_days if force_lookback_days else 5000
            
            # 计算开始时间
            if interval.endswith('d'):
                start_time = now_ts - (5000 * 24 * 3600 * 1000) # 日线推 13 年
            elif interval.endswith('h'):
                start_time = now_ts - (5000 * 3600 * 1000)      # 小时线推 200 天
            else:
                start_time = now_ts - (5000 * interval_ms)      # 分钟线推 5000 根
                
            # 拉取历史
            history_data = self.fetch_from_api(symbol, interval, start_time)
            if history_data:
                self.save_data(history_data)
                # print(f"✅ 历史数据补充完成: {len(history_data)} 条")
                
                # 更新一下状态
                count, min_ts, max_ts = self.get_db_status(symbol, interval)

        # --- 策略 B: 增量更新 (Forward Fill) ---
        # 只要有数据，就检查最新时间是否落后于现在
        if max_ts > 0:
            # 如果最新的数据距离现在超过 1 个周期，才去更新 (避免每秒请求)
            interval_ms = self.parse_interval_to_ms(interval)
            
            # 简单的防抖: 如果最新数据就在刚才，跳过
            # 但对于日线，可能一天都不更新? 
            # 逻辑: 只要 (当前时间 - 数据库最新时间) > 1个周期，就尝试拉取
            if (now_ts - max_ts) > interval_ms * 0.8: 
                start_time = max_ts + 1
                new_data = self.fetch_from_api(symbol, interval, start_time)
                if new_data:
                    self.save_data(new_data)
                    print(f"🔄 更新 {symbol} {interval}: +{len(new_data)} 条 (Total: {count + len(new_data)})")

    def load_data_for_analysis(self, symbol, interval, limit=500):
        """从本地数据库读取数据用于计算"""
        conn = sqlite3.connect(self.db_path)
        
        # 简单优化：只取需要的列，且按时间倒序取 limit 个，然后再正序排回来
        # 这样比读取全部再 tail 快很多
        query = f"""
            SELECT * FROM (
                SELECT timestamp, open, high, low, close, volume 
                FROM klines 
                WHERE symbol = '{symbol}' AND interval = '{interval}'
                ORDER BY timestamp DESC
                LIMIT {limit}
            ) ORDER BY timestamp ASC
        """
        try:
            df = pd.read_sql_query(query, conn)
        except Exception as e:
            print(f"SQL Error: {e}")
            conn.close()
            return None
            
        conn.close()
        
        if df.empty: return None
        
        # 数据清洗
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df