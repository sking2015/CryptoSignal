import sqlite3
import requests
import time
import pandas as pd
import datetime

class MarketDataManager:
    def __init__(self, db_path='hyperliquid_data.db'):
        self.db_path = db_path
        self.init_db()
        # Hyperliquid API Endpoint
        self.base_url = "https://api.hyperliquid.xyz/info"

    def init_db(self):
        """初始化数据库表结构"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
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
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS strategy_states (
                key TEXT PRIMARY KEY,
                state_data BLOB
            )
        ''')          
        conn.commit()
        conn.close()

    def save_strategy_state(self, key, state_data):
        """保存策略状态"""
        import pickle
        try:
            blob_data = pickle.dumps(state_data)
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('INSERT OR REPLACE INTO strategy_states (key, state_data) VALUES (?, ?)', (key, blob_data))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"保存状态失败: {e}")

    def load_strategy_state(self, key):
        """读取策略状态"""
        import pickle
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT state_data FROM strategy_states WHERE key = ?', (key,))
        row = cursor.fetchone()
        conn.close()
        if row:
            try:
                return pickle.loads(row[0])
            except:
                return None
        return None

    # =========================================================
    # 🛠️ 时间与请求管理
    # =========================================================

    def get_interval_ms(self, interval):
        """将时间周期转换为毫秒数"""
        unit = interval[-1]
        try:
            value = int(interval[:-1])
        except:
            value = 1
            
        if unit == 'm': return value * 60 * 1000
        elif unit == 'h': return value * 60 * 60 * 1000
        elif unit == 'd': return value * 24 * 60 * 60 * 1000
        elif unit == 'w': return value * 7 * 24 * 60 * 60 * 1000
        elif unit == 'M': return value * 30 * 24 * 60 * 60 * 1000
        else: return 60 * 1000

    def fetch_from_api(self, symbol, interval, start_time, end_time=None):
        """从 Hyperliquid 获取K线数据"""
        headers = {'Content-Type': 'application/json'}
        start_time = int(start_time)
        
        payload = {
            "type": "candleSnapshot",
            "req": {
                "coin": symbol,
                "interval": interval,
                "startTime": start_time
            }
        }
        
        if end_time:
            payload["req"]["endTime"] = int(end_time)

        try:
            response = requests.post(self.base_url, json=payload, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                formatted_data = []
                for k in data:
                    formatted_data.append((
                        k['t'], 
                        float(k['o']), 
                        float(k['h']), 
                        float(k['l']), 
                        float(k['c']), 
                        float(k['v'])
                    ))
                return formatted_data
            else:
                print(f"API Error {response.status_code}: {response.text}")
                return []
        except Exception as e:
            print(f"Request Failed: {e}")
            return []

    def save_data(self, symbol, interval, data_list):
        """批量保存数据"""
        if not data_list: return
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.executemany(f'''
                INSERT OR REPLACE INTO klines (symbol, interval, timestamp, open, high, low, close, volume)
                VALUES ('{symbol}', '{interval}', ?, ?, ?, ?, ?, ?)
            ''', data_list)
            conn.commit()
        except Exception as e:
            print(f"DB Error: {e}")
        finally:
            conn.close()

    def get_max_timestamp(self, symbol, interval):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(f"SELECT MAX(timestamp) FROM klines WHERE symbol='{symbol}' AND interval='{interval}'")
        row = cursor.fetchone()
        conn.close()
        return row[0] if row and row[0] else None

    # =========================================================
    # 🚀 V6.0 修复版 Update Data - 支持强制回溯
    # =========================================================
    def update_data(self, symbol, interval, force_backfill=False):
        """
        更新数据：
        1. force_backfill=True 或首次运行：触发历史数据回溯补齐 (TARGET_BAR_COUNT 根)
        2. 始终进行增量更新 (保持最新)
        """
        max_ts = self.get_max_timestamp(symbol, interval)
        current_ts = int(time.time() * 1000)
        
        TARGET_BAR_COUNT = 1500 # 目标抓取历史K线数量
        interval_ms = self.get_interval_ms(interval)
        
        is_initial_run = (max_ts is None)
        
        # 1. 历史数据回溯补齐逻辑 (解决数据不足问题)
        if is_initial_run or force_backfill:
            print(f"✨ 触发历史数据回溯补齐/刷新 {symbol} {interval}...")
            
            # 计算需要回溯的起始时间点（1500根K线前）
            start_time = current_ts - (TARGET_BAR_COUNT * interval_ms)
            
            new_data = self.fetch_from_api(symbol, interval, start_time)
            if new_data:
                self.save_data(symbol, interval, new_data)
                print(f"✅ 历史数据补齐完成: {symbol} {interval} | 抓取 {len(new_data)} 条")
            else:
                print(f"⚠️ 历史数据补齐失败: {symbol} {interval} API未返回数据")
                
        # 2. 增量更新 (保持最新)
        # 重新获取最大时间戳，确保包含了刚刚的回溯数据
        max_ts_after_backfill = self.get_max_timestamp(symbol, interval) 
        
        if max_ts_after_backfill is not None:
            # 检查最新数据是否过期 (允许 0.5 个周期的延迟，因为K线可能未走完)
            if current_ts - max_ts_after_backfill > interval_ms * 0.5: 
                start_time = max_ts_after_backfill + 1 # 从下一毫秒开始抓
                
                print(f"🔄 增量更新 {symbol} {interval}...")
                new_data = self.fetch_from_api(symbol, interval, start_time)
                
                if new_data:
                    self.save_data(symbol, interval, new_data)
                    print(f"✅ 更新成功: {symbol} {interval} +{len(new_data)} 条")
                else:
                    pass # 没有新数据是正常情况

    # =========================================================
    # 🔎 V6.0 修复版 Load Data - 自动触发补齐
    # =========================================================
    def load_data_for_analysis(self, symbol, interval, limit=1000):
        """读取数据，并在数据不足时自动触发历史补齐"""
        conn = sqlite3.connect(self.db_path)
        
        # 1. 尝试查询数据
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
            conn.close()
            
            # 2. 检查数据量是否满足需求
            if len(df) < limit:
                 # 只有当数据量不足，且请求的 K 线数较多时才触发补齐
                if len(df) > 0 and limit > 100: 
                    print(f"⚠️ 数据量 ({len(df)}/{limit}) 不足，触发历史补齐...")
                    # 🚨 关键：自动调用 update_data 强制回溯
                    self.update_data(symbol, interval, force_backfill=True)
                    
                    # 重新加载数据，只重试一次
                    conn = sqlite3.connect(self.db_path)
                    df = pd.read_sql_query(query, conn)
                    conn.close()
                    
                    # 如果补齐后还是不够 100 根，则认为数据源有问题
                    if len(df) < 100: 
                         return None
            
            # 3. 数据整理与返回
            if not df.empty:
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                cols = ['open', 'high', 'low', 'close', 'volume']
                df[cols] = df[cols].apply(pd.to_numeric)
                return df
            return None
        except Exception as e:
            print(f"Load Data Error: {e}")
            conn.close()
            return None