import sqlite3
from ConstDef import ALL_CONST

def get_latest_ts(conn,table):
    cursor = conn.cursor()
    cursor.execute(f"SELECT MAX(ts) FROM {[table]}")
    result = cursor.fetchone()
    return result[0] if result and result[0] else None

conn = sqlite3.connect(ALL_CONST["DB"]) 
table = "scrtusdt_5min"
ret = get_latest_ts(conn,table)
print("拉取数据",ret)