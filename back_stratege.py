import pandas as pd
from htx_get import fetch_signals
def backtest_strategy(df, entry_func):
    trades = []
    in_position = False
    entry_price = 0
    entry_time = None
    TP = 0.05
    SL = 0.01

    for i in range(len(df)):
        row = df.iloc[i]
        if not in_position:
            if entry_func(df, i):
                in_position = True
                entry_price = row['close']
                entry_time = row['time']
        else:
            price = row['close']
            change = (price - entry_price) / entry_price
            if change >= TP or change <= -SL:
                trades.append({
                    "entry_time": entry_time,
                    "entry_price": entry_price,
                    "exit_time": row['time'],
                    "exit_price": price,
                    "return": change
                })
                in_position = False

    # 如果最后仍持仓
    if in_position:
        last_row = df.iloc[-1]
        change = (last_row['close'] - entry_price) / entry_price
        trades.append({
            "entry_time": entry_time,
            "entry_price": entry_price,
            "exit_time": last_row['time'],
            "exit_price": last_row['close'],
            "return": change
        })


    return pd.DataFrame(trades)




def backtest_strategy_dual(df, entry_func, tp=0.05, sl=0.01):
    """
    双向回测函数：支持多头/空头开仓
    参数:
        df: 包含收盘价、指标等列的 DataFrame
        entry_func: 自定义开仓函数，返回 "long" / "short" / None
        tp: 止盈比例 (默认 5%)
        sl: 止损比例 (默认 1%)
    返回:
        trades_df: DataFrame，每笔交易的详细信息
        summary: dict, 多头/空头/总收益
    """
    trades = []
    
    for i in range(1, len(df)):
        signal = entry_func(df, i)
        if signal is None:
            continue
        
        entry_price = df.loc[i, "close"]
        entry_time = df.loc[i, "time"]
        
        # 多头
        if signal == "long":
            for j in range(i+1, len(df)):
                close_price = df.loc[j, "close"]
                # 止盈
                if close_price >= entry_price * (1 + tp):
                    trades.append({
                        "position": "long",
                        "entry_time": entry_time,
                        "entry_price": entry_price,
                        "exit_time": df.loc[j, "time"],
                        "exit_price": close_price,
                        "return": tp
                    })
                    break
                # 止损
                elif close_price <= entry_price * (1 - sl):
                    trades.append({
                        "position": "long",
                        "entry_time": entry_time,
                        "entry_price": entry_price,
                        "exit_time": df.loc[j, "time"],
                        "exit_price": close_price,
                        "return": -sl
                    })
                    break
        
        # 空头
        elif signal == "short":
            for j in range(i+1, len(df)):
                close_price = df.loc[j, "close"]
                # 空头止盈（价格下跌）
                if close_price <= entry_price * (1 - tp):
                    trades.append({
                        "position": "short",
                        "entry_time": entry_time,
                        "entry_price": entry_price,
                        "exit_time": df.loc[j, "time"],
                        "exit_price": close_price,
                        "return": tp
                    })
                    break
                # 空头止损（价格上涨）
                elif close_price >= entry_price * (1 + sl):
                    trades.append({
                        "position": "short",
                        "entry_time": entry_time,
                        "entry_price": entry_price,
                        "exit_time": df.loc[j, "time"],
                        "exit_price": close_price,
                        "return": -sl
                    })
                    break
    
    # 转 DataFrame
    trades_df = pd.DataFrame(trades)

    return trades_df
    

def entry_boll_macd_dual(df, i):
    if i < 1:  # 保证有前一根K线
        return None  # 没有信号
    
    # 布林下轨反弹 + MACD 金叉 → 多头
    long_signal = (df.loc[i-1, "close"] < df.loc[i-1, "boll_lower"] and
                   df.loc[i, "close"] > df.loc[i, "boll_lower"] and
                   df.loc[i-1, "macd"] < df.loc[i-1, "macd_signal"] and
                   df.loc[i, "macd"] > df.loc[i, "macd_signal"])
    
    # 布林上轨反弹 + MACD 死叉 → 空头
    short_signal = (df.loc[i-1, "close"] > df.loc[i-1, "boll_upper"] and
                    df.loc[i, "close"] < df.loc[i, "boll_upper"] and
                    df.loc[i-1, "macd"] > df.loc[i-1, "macd_signal"] and
                    df.loc[i, "macd"] < df.loc[i, "macd_signal"])
    
    if long_signal:
        return "long"
    elif short_signal:
        return "short"
    else:
        return None
    

def entry_rsi_kdj(df, i):
    if i == 0:
        return False
    return (
        df.loc[i, "rsi"] < 30 and
        df.loc[i-1, "kdj_k"] < df.loc[i-1, "kdj_d"] and
        df.loc[i, "kdj_k"] > df.loc[i, "kdj_d"]
    )

def entry_macd(df, i):
    if i == 0:
        return False
    return (
        df.loc[i-1, "macd"] < df.loc[i-1, "macd_signal"] and
        df.loc[i, "macd"] > df.loc[i, "macd_signal"]
    )


def entry_boll(df, i):
    if i < 1:
        return False
    return (
        df.loc[i-1, "close"] < df.loc[i-1, "boll_lower"] and
        df.loc[i, "close"] > df.loc[i, "boll_lower"]
    )

def entry_boll_rebound_dual(df, i):
    """
    布林反弹双向开仓
    返回：
        "long" -> 下轨反弹开多
        "short" -> 上轨反弹开空
        None -> 没有信号
    """
    if i < 1:
        return None

    # 多头：下轨反弹
    long_signal = df.loc[i-1, "close"] < df.loc[i-1, "boll_lower"] and df.loc[i, "close"] > df.loc[i, "boll_lower"]

    # 空头：上轨反弹
    short_signal = df.loc[i-1, "close"] > df.loc[i-1, "boll_upper"] and df.loc[i, "close"] < df.loc[i, "boll_upper"]

    if long_signal:
        return "long"
    elif short_signal:
        return "short"
    else:
        return None


def entry_boll_trend(df, i, trend_len=2):
    if i < trend_len:
        return False
    # 上轨趋势
    if all(df.loc[i-j, "close"] > df.loc[i-j, "boll_upper"] for j in range(trend_len)):
        return True
    # 下轨趋势
    if all(df.loc[i-j, "close"] < df.loc[i-j, "boll_lower"] for j in range(trend_len)):
        return True
    return False

def entry_td9(df, i):
    return df.loc[i, "td_count"] <= -9

def entry_boll_macd(df, i):
    if i < 1:  # 保证有前一根K线
        return False
    
    # 布林反弹
    boll_rebound = (df.loc[i-1, "close"] < df.loc[i-1, "boll_lower"] and
                    df.loc[i, "close"] > df.loc[i, "boll_lower"])
    
    # MACD 金叉
    macd_gold_cross = (df.loc[i-1, "macd"] < df.loc[i-1, "macd_signal"] and
                       df.loc[i, "macd"] > df.loc[i, "macd_signal"])
    
    # 双确认
    return boll_rebound and macd_gold_cross


def print_backtest_report(trades: pd.DataFrame, strategy_name: str = "策略"):
    if trades.empty:
        print(f"\n=== {strategy_name} ===")
        print("没有产生任何交易信号。")
        return

    # 胜率（止盈次数 / 总交易次数）
    win_rate = (trades["return"] > 0).mean()

    # 平均每笔收益
    avg_return = trades["return"].mean()

    # 总收益（简单加和）
    total_return = trades["return"].sum()

    # 累计收益（复利）
    cumulative_return = (trades["return"] + 1).prod() - 1

    print(f"\n=== {strategy_name} 回测报告 ===")
    print(f"交易次数      : {len(trades)}")
    print(f"胜率          : {win_rate:.2%}")
    print(f"平均每笔收益  : {avg_return:.2%}")
    print(f"总收益(加和)  : {total_return:.2%}")
    print(f"累计收益(复利): {cumulative_return:.2%}")


STRATEGE_RSIKDJ = "RSI+KDJ"
STRATEGE_MACD = "MACD 金叉"
STRATEGE_BOLL = "布林反弹"
STRATEGE_BOLL_T = "布林趋势"
STRATEGE_TD = "TD九连下跌"
STRATEGE_BOLL_MACD = "布林MACD双确认"
STRATEGE_BOLL_MACD_D = "布林MACD双向双确认"
STRATEGE_BOLL_D = "布林反弹双向交易"

def summarize_backtests(results: dict) -> pd.DataFrame:
    """
    results: dict[strategy_name -> trades_dataframe]
    """
    summary = []

    for name, trades in results.items():
        if trades.empty:
            summary.append({
                "策略": name,
                "交易次数": 0,
                "胜率": None,
                "平均每笔收益": None,
                "总收益(加和)": None,
                "累计收益(复利)": None,
            })
            continue

        win_rate = (trades["return"] > 0).mean()
        avg_return = trades["return"].mean()
        total_return = trades["return"].sum()
        cumulative_return = (trades["return"] + 1).prod() - 1

        summary.append({
            "策略": name,
            "交易次数": len(trades),
            "胜率": f"{win_rate:.2%}",
            "平均每笔收益": f"{avg_return:.2%}",
            "总收益(加和)": f"{total_return:.2%}",
            "累计收益(复利)": f"{cumulative_return:.2%}",
        })

    return pd.DataFrame(summary)



def BackTestOne(symbol="ethusdt", period="30min", size=288, return_df=False):


    print(f"\n====回测币种 {symbol.upper()}====")
    df = fetch_signals(symbol, period, size=500, return_df=True)

    # 2. 跑不同策略
    # print(f"\n=== 策略1: {STRATEGE_RSIKDJ} ===")
    trades_rsi_kdj = backtest_strategy(df, entry_rsi_kdj)
    # print(trades_rsi_kdj.head(10))   

    # total_return = trades_rsi_kdj["return"].sum()
    # print_backtest_report(trades_rsi_kdj,STRATEGE_RSIKDJ)
    # print(f"策略总收益: {total_return:.2%}")  


    # print(f"\n=== 策略2: {STRATEGE_MACD} ===")
    trades_macd = backtest_strategy(df, entry_macd)
    # print(trades_macd.head(10))    
    # total_return = trades_macd["return"].sum()
    # print_backtest_report(trades_macd,STRATEGE_MACD)
    # print(f"策略总收益: {total_return:.2%}")         

    # print(f"\n=== 策略3: {STRATEGE_BOLL} ===")
    trades_boll = backtest_strategy(df, entry_boll)
    # print_backtest_report(trades_boll,STRATEGE_BOLL)
    # print(trades_boll.head(10))          
    # total_return = trades_boll["return"].sum()
    # print(f"策略总收益: {total_return:.2%}")      

    # print(f"\n=== 策略4: {STRATEGE_TD} ===")
    trades_boll_t = backtest_strategy(df, entry_boll_trend)

    trades_td9 = backtest_strategy(df, entry_td9)

    trades_boll_macd = backtest_strategy(df, entry_boll_macd)


    trades_boll_macd_dual = backtest_strategy_dual(df,entry_boll_macd_dual)
    trades_boll_dual = backtest_strategy_dual(df,entry_boll_rebound_dual)


    
    # print_backtest_report(trades_td9,STRATEGE_TD)
    # print(trades_td9.head(10))  
    # total_return = trades_td9["return"].sum()
    # print(f"策略总收益: {total_return:.2%}")    
    # 
    results = {
        STRATEGE_RSIKDJ: trades_rsi_kdj,
        STRATEGE_MACD: trades_macd,
        STRATEGE_BOLL: trades_boll,
        STRATEGE_BOLL_T:trades_boll_t,
        STRATEGE_TD:trades_td9,
        STRATEGE_BOLL_MACD:trades_boll_macd,
        STRATEGE_BOLL_MACD_D:trades_boll_macd_dual,
        STRATEGE_BOLL_D:trades_boll_dual
    }

    summary_df = summarize_backtests(results)
    print(summary_df)       


import pandas as pd

def compute_boll(df, n=20, k=2):
    """
    计算布林带
    """
    df['boll_mid'] = df['close'].rolling(n).mean()
    df['boll_std'] = df['close'].rolling(n).std()
    df['boll_upper'] = df['boll_mid'] + k * df['boll_std']
    df['boll_lower'] = df['boll_mid'] - k * df['boll_std']
    return df

def compute_macd(df, fast=12, slow=26, signal=9):
    """
    使用pandas计算MACD
    """
    df['ema_fast'] = df['close'].ewm(span=fast, adjust=False).mean()
    df['ema_slow'] = df['close'].ewm(span=slow, adjust=False).mean()
    df['macd'] = df['ema_fast'] - df['ema_slow']
    df['macd_signal'] = df['macd'].ewm(span=signal, adjust=False).mean()
    return df

def trend_strength(df, period=14):
    """
    用ADX近似趋势强弱
    ADX = smoothed average of directional movement
    这里用简单方法：连续N根K线收盘价涨/跌幅平均
    """
    df['diff'] = df['close'].diff()
    df['up'] = df['diff'].apply(lambda x: max(x,0))
    df['down'] = df['diff'].apply(lambda x: -min(x,0))
    df['up_avg'] = df['up'].rolling(period).mean()
    df['down_avg'] = df['down'].rolling(period).mean()
    df['trend_strength'] = (df['up_avg'] - df['down_avg']).abs() / (df['up_avg'] + df['down_avg'] + 1e-6)
    # 越大表示趋势越明显，经验阈值 0.25
    return df['trend_strength'].iloc[-1] >= 0.25

# 回测函数 entry_func 例子（双向）
def entry_boll_macd_dual(df, i):
    if i < 1:
        return None
    # 多头：下轨反弹 + MACD金叉
    long_signal = df.loc[i-1,'close'] < df.loc[i-1,'boll_lower'] and df.loc[i,'close'] > df.loc[i,'boll_lower'] \
                  and df.loc[i-1,'macd'] < df.loc[i-1,'macd_signal'] and df.loc[i,'macd'] > df.loc[i,'macd_signal']
    # 空头：上轨反弹 + MACD死叉
    short_signal = df.loc[i-1,'close'] > df.loc[i-1,'boll_upper'] and df.loc[i,'close'] < df.loc[i,'boll_upper'] \
                   and df.loc[i-1,'macd'] > df.loc[i-1,'macd_signal'] and df.loc[i,'macd'] < df.loc[i,'macd_signal']
    if long_signal:
        return "long"
    elif short_signal:
        return "short"
    else:
        return None


# BASE = 30

# CHECK_INTERVAL = BASE * 60  # 秒，检查条件的间隔

TIME = "60min"

hot_symbols = [
    "btcusdt", "ethusdt", "xrpusdt", "trxusdt", "bnbusdt",
    "solusdt", "adausdt", "dotusdt", "dogeusdt", "ltcusdt",
    "linkusdt", "pepeusdt", "shibusdt", "avaxusdt", "atomusdt",
    "bchusdt", "vetusdt", "xlmusdt", "algousdt", "nearusdt"
]

for symbol in hot_symbols:
    BackTestOne(symbol,TIME,500)


