import sqlite3
import requests
import time
import pandas as pd
# import traceback


class MarketDataManager:
    def __init__(self, db_path='hyperliquid_data.db'):
        self.db_path = db_path
        self.init_db()
        self.base_url = "https://api.hyperliquid.xyz/info"

    def init_db(self):
        """初始化数据库表结构"""
        print("init_db",self.db_path)
        # traceback.print_stack()

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



        # 🚨 [新增] 策略状态表：key 是 symbol_interval，value 是序列化后的状态
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS strategy_states (
                key TEXT PRIMARY KEY,
                state_data BLOB
            )
        ''')          
        conn.commit()
        conn.close()

    # core/hyperliquidDataMgr.py (在 MarketDataManager 类中添加)
    def save_strategy_state(self, key, state_data):
        """保存单个 key 的策略状态 (需要先序列化 state_data)"""
        import pickle
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        # 字典序列化为二进制数据
        serialized_data = sqlite3.Binary(pickle.dumps(state_data)) 
        
        cursor.execute('''
            INSERT OR REPLACE INTO strategy_states (key, state_data) 
            VALUES (?, ?)
        ''', (key, serialized_data))
        conn.commit()
        conn.close()

    def load_strategy_state(self, key):
        """加载单个 key 的策略状态 (需要反序列化)"""
        import pickle
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT state_data FROM strategy_states WHERE key = ?", (key,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            # 反序列化二进制数据
            return pickle.loads(result[0])
        return None        

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
        智能更新数据: V2.2 最终版
        1. 自动进行历史回补 (Backfill)。
        2. 鲁棒的增量更新 (Forward Fill)，确保更新到最新已收盘 K 线。
        """
        count, min_ts, max_ts = self.get_db_status(symbol, interval)
        now_ts = int(time.time() * 1000)

        print("max_ts",max_ts,pd.to_datetime(max_ts,unit='ms'))
        print("now_ts",now_ts,pd.to_datetime(now_ts,unit='ms'))


        
        # --- 策略 A: 历史回补 (Backfill) ---
        need_backfill = False
        if count == 0:
            need_backfill = True
        elif count < 400:
            interval_ms = self.parse_interval_to_ms(interval)
            target_span = 1000 * interval_ms
            if (now_ts - min_ts) > target_span:
                # 如果最早的数据比 1000 根K线前还要新，说明缺历史
                need_backfill = True
                print(f"📉 {symbol} {interval} 数据量不足 ({count}条)，正在补充历史...")

        if need_backfill:
            interval_ms = self.parse_interval_to_ms(interval)
            
            # 向前推 5000 根 K 线
            start_time = now_ts - (5000 * interval_ms)
                
            history_data = self.fetch_from_api(symbol, interval, start_time)
            if history_data:
                self.save_data(history_data)
                
                # 重新读取最新状态
                count, min_ts, max_ts = self.get_db_status(symbol, interval)
                print(f"✅ 历史数据补充完成: {len(history_data)} 条 (Total: {count})")
        
        # --- 策略 B: 增量更新 (Forward Fill) ---
        
        if max_ts > 0:
            # 1. 计算增量拉取起点 (最新已收盘 K 线的下一秒)
            start_time = max_ts + 1 
            
            # 2. 判断是否落后于当前时间（即是否有新数据可拉）
            # 如果数据库最新时间 max_ts 距离现在已经超过 1.5个周期，那肯定有已收盘K线了
            interval_ms = self.parse_interval_to_ms(interval)
            
            # 只有当数据库最新时间 距离 当前时间 超过 1.5 倍周期时，才拉取
            # 这样保证：如果当前K线正在走，且已收盘K线很新，它会等到 K 线走完才拉
            print("now_ts - max_ts",now_ts - max_ts)
            print("interval_ms * 1.5",interval_ms * 1.5)
            if (now_ts - max_ts) > interval_ms * 1.5:
                
                print(f"🔄 DEBUG 增量: 尝试拉取 {symbol} {interval}，从 {pd.to_datetime(start_time, unit='ms')} 开始...")
                
                new_data = self.fetch_from_api(symbol, interval, start_time)
                
                if new_data:
                    self.save_data(new_data)
                    print(f"🔄 增量成功: {symbol} {interval} +{len(new_data)} 条 (最新: {pd.to_datetime(new_data[-1][2], unit='ms')})")
                else:
                    print(f"DEBUG 增量: {symbol} {interval} API 返回空数据。") 
            else:
                print(f"DEBUG 增量: {symbol} {interval} K线未走完/数据已是最新 (Max TS: {pd.to_datetime(max_ts, unit='ms')})")

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