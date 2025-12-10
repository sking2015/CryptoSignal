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
            # 增加超时时间到 15s
            response = requests.post(self.base_url, json=payload, headers=headers, timeout=15)
            
            if response.status_code != 200:
                # print(f"🚨 API请求失败: {symbol} {interval} | 状态: {response.status_code}")
                return []
            
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
        except Exception as e:
            # print(f"Request Failed: {e}")
            return []

    def save_data(self, symbol, interval, data_list):
        """批量保存数据 (INSERT OR REPLACE 确保能更新最新K线)"""
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
    # 🚀 V40.0 核心修复：实时刷新最后一根K线 (Live Candle Refresh)
    # =========================================================
    def update_data(self, symbol, interval, force_backfill=False):
        """
        更新数据逻辑升级：
        1. 历史回溯：如果数据不足，抓取历史。
        2. 实时刷新：总是从数据库中【最后一条记录的时间】开始抓取，
           确保正在进行中的K线（未走完的）能实时更新其 Close/High/Low 价格。
        """
        max_ts = self.get_max_timestamp(symbol, interval)
        current_ts = int(time.time() * 1000)
        
        TARGET_BAR_COUNT = 1500 
        interval_ms = self.get_interval_ms(interval)
        
        is_initial_run = (max_ts is None)
        
        # 1. 历史补齐 (保持不变)
        if is_initial_run or force_backfill:
            # print(f"✨ 触发历史补齐 {symbol} {interval}...")
            start_time = current_ts - (TARGET_BAR_COUNT * interval_ms)
            new_data = self.fetch_from_api(symbol, interval, start_time)
            if new_data:
                self.save_data(symbol, interval, new_data)
            return # 补齐后直接结束，因为补齐的数据肯定包含了最新的

        # 2. 增量更新 + 实时刷新 (核心修改)
        # 重新获取最大时间戳
        max_ts_after_backfill = self.get_max_timestamp(symbol, interval)
        
        if max_ts_after_backfill is not None:
            # 🚨 关键修改点 🚨
            # 旧逻辑: start_time = max_ts + 1 (导致跳过已存在的最后一根)
            # 新逻辑: start_time = max_ts (重抓最后一根，覆盖更新它)
            
            start_time = max_ts_after_backfill
            
            # 移除所有时间间隔判断 (if current - max > interval)，
            # 只要被调用，就无条件去确认一下最新K线的状态。
            
            new_data = self.fetch_from_api(symbol, interval, start_time)
            
            if new_data:
                # save_data 使用的是 INSERT OR REPLACE
                # 所以数据库中旧的、未走完的 max_ts 记录会被新的数据覆盖
                self.save_data(symbol, interval, new_data)
                # print(f"✅ 刷新成功: {symbol} {interval} (Covering {pd.to_datetime(start_time, unit='ms')})")

    def load_data_for_analysis(self, symbol, interval, limit=1000):
        """读取数据，并在数据不足时自动触发历史补齐"""
        conn = sqlite3.connect(self.db_path)
        
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
            
            # 检查数据量
            if len(df) < limit and len(df) > 0 and limit > 100:
                # print(f"⚠️ 数据量不足，触发补齐...")
                self.update_data(symbol, interval, force_backfill=True)
                
                # 重试一次
                conn = sqlite3.connect(self.db_path)
                df = pd.read_sql_query(query, conn)
                conn.close()
                
                if len(df) < 100: return None
            
            if not df.empty:
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                cols = ['open', 'high', 'low', 'close', 'volume']
                df[cols] = df[cols].apply(pd.to_numeric)
                return df
            return None
        except Exception as e:
            conn.close()
            return None