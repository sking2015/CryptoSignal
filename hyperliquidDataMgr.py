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
        # 创建K线表，设置联合主键防止重复
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

    def get_latest_timestamp(self, symbol, interval):
        """查询本地数据库中最新的K线时间戳"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT MAX(timestamp) FROM klines WHERE symbol = ? AND interval = ?", 
            (symbol, interval)
        )
        result = cursor.fetchone()
        conn.close()

        maxtime = result[0]

        print("看一下 result",result)
        
        # 修正点：result 通常是 (None,) 或者 (16234324324,)
        # 我们需要提取元组中的第一个值
        if maxtime and maxtime is not None:
            return maxtime  # 返回整数时间戳
        else:
            return 0          # 如果没有数据，返回 0

    def fetch_from_api(self, symbol, interval, start_time):
        """从 Hyperliquid API 拉取数据"""
        print(f"正在从远程接口拉取 {symbol} {interval} 新增数据...")
        try:
            payload = {
                "type": "candleSnapshot",
                "req": {
                    "coin": symbol,
                    "interval": interval,
                    "startTime": start_time
                }
            }
            response = requests.post(self.base_url, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
            data = response.json()
            if not data: return []
            
            # 整理数据格式
            formatted_data = []
            for k in data:
                # Hyperliquid返回: t: timestamp, o: open, h: high, l: low, c: close, v: volume
                formatted_data.append((
                    symbol, interval, int(k['t']), 
                    float(k['o']), float(k['h']), float(k['l']), float(k['c']), float(k['v'])
                ))
            return formatted_data
        except Exception as e:
            print(f"API请求失败: {e}")
            return []

    def update_data(self, symbol, interval, lookback_days=30):
        """核心逻辑：增量更新数据"""
        # 1. 获取本地最新时间
        last_ts = self.get_latest_timestamp(symbol, interval)
        
        # 2. 如果本地没有数据，则设定一个默认的开始时间（例如过去30天）
        if last_ts == 0:
            start_time = int((time.time() - lookback_days * 24 * 60 * 60) * 1000)
        else:
            # 从最后一根K线的下一秒开始拉取
            start_time = last_ts + 1 

        # 3. 只有当start_time距离现在有一定间隔时才请求，避免频繁请求最新未完成的K线
        if time.time() * 1000 - start_time < 60000: # 如果差距小于1分钟，可能不需要更新
            return

        # 4. 拉取新数据
        new_data = self.fetch_from_api(symbol, interval, start_time)
        
        # 5. 存入数据库
        if new_data:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            # 使用 INSERT OR IGNORE 避免重复插入报错
            cursor.executemany(
                "INSERT OR IGNORE INTO klines VALUES (?,?,?,?,?,?,?,?)", 
                new_data
            )
            conn.commit()
            conn.close()
            print(f"成功入库 {len(new_data)} 条 {symbol} 数据")

    def load_data_for_analysis(self, symbol, interval, limit=500):
        """从本地数据库读取数据用于计算"""
        conn = sqlite3.connect(self.db_path)
        # 读取最近的 limit 条数据
        query = f"""
            SELECT timestamp, open, high, low, close, volume 
            FROM klines 
            WHERE symbol = '{symbol}' AND interval = '{interval}'
            ORDER BY timestamp ASC
        """
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        if df.empty: return None
        
        # 数据清洗与格式转换
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df.tail(limit).reset_index(drop=True)