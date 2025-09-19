import sqlite3
from ConstDef import ALL_CONST

def maintain_db(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # 1. 获取所有表名
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cur.fetchall()]

    for table in tables:
        # 2. 检查是否为空表
        cur.execute(f'SELECT COUNT(*) FROM "{table}"')
        count = cur.fetchone()[0]

        if count == 0:
            print(f"删除空表: {table}")
            cur.execute(f'DROP TABLE IF EXISTS "{table}"')


    conn.commit()
    conn.close()

# 使用
maintain_db(ALL_CONST["DB"])
