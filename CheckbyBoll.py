import sqlite3
import requests
import asyncio
import time
from datetime import datetime
import pandas as pd
from DatabaseUpdate import update_all_symbol
from RobotNotifier import send_message_async

def get_current_price(symbol):
    """
    从HTX获取最新成交价
    """
    url = f"https://api.huobi.pro/market/trade?symbol={symbol}"
    resp = requests.get(url).json()
    return float(resp["tick"]["data"][0]["price"])


import pandas as pd

def check_bollinger_convergence_debug(df: pd.DataFrame,
                                      n: int = 10,
                                      period: int = 20,
                                      k: float = 2.0,
                                      threshold: float = 0.02,
                                      mode: str = 'pct'):
    """
    debug 版布林带收敛检测

    参数:
      df        : 含 'close' 列，建议含 'open_time' 列 (毫秒时间戳或可解析时间字符串)
      n         : 要检查的最近 K 根数
      period    : 布林带均线周期
      k         : 标准差倍数
      threshold : 阈值 (如果 mode=='pct' 则表示带宽百分比，如 0.02=2%)
      mode      : 'pct' 使用 bandwidth/ma < threshold；'abs' 使用 bandwidth < close*threshold

    返回:
      dict 包含:
        'converging'    : bool (是否连续 n 根满足条件)
        'shrinking'     : bool (最近 n 根带宽是否全部在缩小)
        'recent'        : pd.DataFrame 最近 n 根的诊断列（已 dropna）
        'hist_threshold': 历史 10% 分位数（bandwidth_pct）
        'df'            : 计算后完整 DataFrame（含计算列）
    """

    df = df.copy()

    # 1. 强制数值化 close
    df['close'] = pd.to_numeric(df['close'], errors='coerce')

    # 2. 如果有 open_time，按时间升序排序（保证 tail() 是最新 n 根）
    if 'open_time' in df.columns:
        try:
            df = df.sort_values('open_time').reset_index(drop=True)
        except Exception:
            df = df.reset_index(drop=True)
    else:
        df = df.reset_index(drop=True)

    # 3. 计算布林带
    df['ma'] = df['close'].rolling(period).mean()
    df['std'] = df['close'].rolling(period).std()
    df['upper'] = df['ma'] + k * df['std']
    df['lower'] = df['ma'] - k * df['std']
    df['bandwidth'] = df['upper'] - df['lower']
    df['bandwidth_pct'] = df['bandwidth'] / df['ma']   # 相对带宽（比率）
    df['bandwidth_diff'] = df['bandwidth'].diff()
    df['is_converging_abs'] = df['bandwidth'] < (df['close'] * threshold)
    df['is_converging_pct'] = df['bandwidth_pct'] < threshold
    df['is_shrinking'] = df['bandwidth_diff'] < 0

    # 4. 丢掉还没计算出的行
    usable = df.dropna(subset=['ma', 'std', 'bandwidth', 'bandwidth_pct']).reset_index(drop=True)

    # 输出基础诊断信息
    print("== 布林带诊断 == ")
    print("总行数:", len(df), "可用(去掉rolling NaN) 行数:", len(usable))
    if len(usable) == 0:
        print("没有足够数据计算布林带（period 太大或 close 全是 NaN）")
        return {'converging': False, 'shrinking': False, 'recent': usable, 'hist_threshold': None, 'df': df}

    # 时间范围（尝试解析 open_time）
    if 'open_time' in df.columns:
        try:
            first_t = pd.to_datetime(df['open_time'].iloc[0], unit='ms')
            last_t  = pd.to_datetime(df['open_time'].iloc[-1], unit='ms')
        except Exception:
            try:
                first_t = pd.to_datetime(df['open_time'].iloc[0])
                last_t  = pd.to_datetime(df['open_time'].iloc[-1])
            except Exception:
                first_t = df['open_time'].iloc[0]
                last_t  = df['open_time'].iloc[-1]
        print("时间范围:", first_t, "->", last_t)

    # 如果可用行 < n 则提醒
    if len(usable) < n:
        print(f"注意：可用行 ({len(usable)}) < 需要检测的 n ({n})，将尽可能返回最近 {len(usable)} 根")
        n_check = len(usable)
    else:
        n_check = n

    recent = usable.tail(n_check).copy()

    # 格式化打印最近若干行（数值列四舍五入）
    disp_cols = ['open_time','close','ma','std','upper','lower','bandwidth','bandwidth_pct','bandwidth_diff','is_converging_pct','is_converging_abs','is_shrinking']
    disp = recent[disp_cols].copy()
    numcols = disp.select_dtypes(include='number').columns
    disp[numcols] = disp[numcols].round(8)
    print("\n最近 {} 根 诊断表:".format(n_check))
    print(disp.to_string(index=False))

    # 历史分位数（给出参考）
    qs = [0.01, 0.05, 0.1, 0.25, 0.5]
    qvals = df['bandwidth_pct'].quantile(qs).to_dict()
    print("\nbandwidth_pct 分位数 (1%,5%,10%,25%,50%):")
    for kq, v in qvals.items():
        print(f"  {int(kq*100)}% -> {v:.6f}")

    hist_thr = df['bandwidth_pct'].quantile(0.1)
    print("历史 10% 分位数 (bandwidth_pct):", hist_thr)

    # 判断结果
    if mode == 'pct':
        converging = recent['is_converging_pct'].all()
    else:
        converging = recent['is_converging_abs'].all()
    shrinking = (recent['bandwidth_diff'] < 0).all()

    print("\n结论: converging (mode=%s): %s   shrinking: %s" % (mode, converging, shrinking))

    return {'converging': converging, 'shrinking': shrinking, 'recent': recent, 'hist_threshold': hist_thr, 'df': df}


def check_bollinger_convergence(df: pd.DataFrame, n: int = 10, period: int = 20, k: float = 2.0, threshold: float = 0.02) -> bool:
    """
    检查最近 n 根 K 线是否满足严格布林带收敛:
      - 带宽不增大
      - 上轨下降
      - 下轨上升

    参数:
        df     : 必须包含 'close' 列
        n      : 连续检查的K线数量
        period : 布林带均线周期
        k      : 标准差倍数

    返回:
        True  -> 最近 n 根K线全部满足收敛条件
        False -> 否则
    """
    if len(df) < period + n:
        return False

    df = df.copy()
    df["ma"] = df["close"].rolling(period).mean()
    df["std"] = df["close"].rolling(period).std()
    df["upper"] = df["ma"] + k * df["std"]
    df["lower"] = df["ma"] - k * df["std"]
    df["bandwidth"] = df["upper"] - df["lower"]

    # 条件判断
    cond1 = df["bandwidth"] <= df["bandwidth"].shift(1)   # 带宽缩小或持平
    cond2 = df["upper"] <= df["upper"].shift(1)           # 上轨下降
    cond3 = df["lower"] >= df["lower"].shift(1)           # 下轨上升（向内收缩）

    df["is_converging"] = cond1 & cond2 & cond3

    # 取最近 n 根
    return df["is_converging"].tail(n).all()


# 计算布林带并检测突破
def check_bollinger_breakout(conn, table: str, price,limit: int = 20, num_std: float = 2.0):
    """
    从指定K线表取数据，计算布林带，检查最新价格是否触及上/下轨
    :param conn: sqlite3.Connection
    :param table: 表名 (例如 'kline_30min')
    :param period: 布林周期 (默认20)
    :param num_std: 标准差倍数 (默认2)
    """
    # 取最近 period+2 根数据，保证够算
    query = f"SELECT ts, close, high, low FROM {table} ORDER BY ts DESC LIMIT {limit+2}"
    df = pd.read_sql(query, conn).sort_values("ts")


    if len(df) < limit:
        print(f"⚠️ {table} 数据不足 {limit} 根，无法计算布林带")
        return

    # 计算布林带
    df["ma"] = df["close"].rolling(limit).mean()
    df["std"] = df["close"].rolling(limit).std()
    df["upper"] = df["ma"] + num_std * df["std"]
    df["lower"] = df["ma"] - num_std * df["std"]

    latest = df.iloc[-1]
    # price = latest["close"]
    khprice = latest["high"]
    klprice = latest["low"]


    cond = False
    
    # print("当前布林带数据",df)
    # print("当前价格",price)
    if price >= latest["upper"]:
        print(f"📈 {table} 最新价 {price} 触及布林上轨 {latest['upper']:.2f}")
        cond = True
    elif price <= latest["lower"]:
        print(f"📉 {table} 最新价 {price} 触及布林下轨 {latest['lower']:.2f}")
        cond = True

    if khprice >= latest["upper"]:
        print(f"📈 {table} k线最高价 {khprice} 触及布林上轨 {latest['upper']:.2f}")
        cond = True
    elif klprice <= latest["lower"]:
        print(f"📉 {table} k线最低价 {klprice} 触及布林下轨 {latest['lower']:.2f}")        
        cond = True

    return cond


def check_all_tables(db_path: str,symbol):
    """
    遍历数据库里所有kline表，检查布林突破
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 找出所有kline表
    cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '{symbol}_%'")
    tables = [row[0] for row in cursor.fetchall()]

    print(tables)

    curPrice = get_current_price(symbol)

    nTriggerCount = 0
    b1DayTrgger = False

    for table in tables:
        print(f"检查{table}的k线数据")
        
        para = table.split("_")
        period = para[1]
        print(f"检查{symbol}的{period}线")      
        
        if check_bollinger_breakout(conn, table,curPrice):
            nTriggerCount += 1   
            if period == "1day":
                b1DayTrgger = True
                print("===========================================")
                print(f"{symbol} 触及日线级别布林带上下轨")

    # 如果日线触及布林带上下轨或有五条线均触及布林带上下轨,则通知
    if b1DayTrgger and nTriggerCount > 2 or  nTriggerCount > 5:
        return True                        

    conn.close()

async def TimerTask():
    update_all_symbol()
    for symbol in HOT_SYMBOLS:
        sMess = ""
        if check_all_tables(DB_FILE,symbol):  # 这里换成你的数据库文件名            
            sMess += " "
            sMess += symbol

    if sMess != "":
        print("===========================================")  
        message = "📉以下币种触发量化信号，请关注：" + sMess    
        print(message)
        await send_message_async(message)   

def main():
    """
    每当分钟数能被5整除时执行一次 task()
    """
    last_minute = -1
    print("开始进入定时任务，每五分钟检查一次")
    while True:
        now = datetime.now()
        minute = now.minute
        if minute % 5 == 0 and minute != last_minute:
            print(f"⏰ 触发任务: {now.strftime('%Y-%m-%d %H:%M:%S')}")
            asyncio.run(TimerTask())
            last_minute = minute
        time.sleep(10) 
 


if __name__ == "__main__":
    # asyncio.run(main())
    main()
    


