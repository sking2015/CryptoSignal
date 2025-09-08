

from htx_get import fetch_signals

def scanlist(list_hot,timedesc):
    signals_list = []
    BOLL_TREND_CONFIRM = 2  # 连续多少根K线才算趋势确认

    for symbol in list_hot:
        print(f"\n=== {symbol.upper()} 信号 ===")
        bHavesign = False

        # 调用已有函数获取 DataFrame
        df = fetch_signals(symbol=symbol, period=timedesc, size=288, return_df=True)

        for i in range(1, len(df)):
            prev, curr = df.iloc[i - 1], df.iloc[i]

            # 买入信号
            if (curr["rsi"] < 30 and
                ((prev["macd"] < prev["macd_signal"] and curr["macd"] > curr["macd_signal"]) or
                 (prev["kdj_k"] < prev["kdj_d"] and curr["kdj_k"] > curr["kdj_d"]))):
                print(f"{curr['time']} 买入信号 | 收盘价={curr['close']:.2f}, RSI={curr['rsi']:.2f}, "
                      f"KDJ_J={curr['kdj_j']:.2f}, TD_Count={curr['td_count']}")
                bHavesign = True

            # 卖出信号
            if (curr["rsi"] > 70 and
                ((prev["macd"] > prev["macd_signal"] and curr["macd"] < curr["macd_signal"]) or
                 (prev["kdj_k"] > prev["kdj_d"] and curr["kdj_k"] < curr["kdj_d"]))):
                print(f"{curr['time']} 卖出信号 | 收盘价={curr['close']:.2f}, RSI={curr['rsi']:.2f}, "
                      f"KDJ_J={curr['kdj_j']:.2f}, TD_Count={curr['td_count']}")
                bHavesign = True

            # TD Sequential 九连信号
            if curr["td_count"] == 9:
                print(f"{curr['time']} TD Sequential 九连上涨信号 | 收盘价={curr['close']:.2f}")
                bHavesign = True
            if curr["td_count"] == -9:
                print(f"{curr['time']} TD Sequential 九连下跌信号 | 收盘价={curr['close']:.2f}")
                bHavesign = True

            if i >= 1:
                # 布林反弹
                if df.loc[i-1, "close"] < df.loc[i-1, "boll_lower"] and df.loc[i, "close"] > df.loc[i, "boll_lower"]:
                    print(f"{curr['time']} 布林下轨反弹 | 收盘价={curr['close']:.2f}")
                    bHavesign = True
                if df.loc[i-1, "close"] > df.loc[i-1, "boll_upper"] and df.loc[i, "close"] < df.loc[i, "boll_upper"]:
                    print(f"{curr['time']} 布林上轨反弹 | 收盘价={curr['close']:.2f}")
                    bHavesign = True


            # BOLL 趋势保持确认
            if i >= BOLL_TREND_CONFIRM:
                if all(df.loc[i - j, "close"] > df.loc[i - j, "boll_upper"] for j in range(BOLL_TREND_CONFIRM)):
                    print(f"{curr['time']} 布林带上轨突破确认（连续{BOLL_TREND_CONFIRM}根） | 收盘价={curr['close']:.2f}")
                    bHavesign = True
                if all(df.loc[i - j, "close"] < df.loc[i - j, "boll_lower"] for j in range(BOLL_TREND_CONFIRM)):
                    print(f"{curr['time']} 布林带下轨突破确认（连续{BOLL_TREND_CONFIRM}根） | 收盘价={curr['close']:.2f}")
                    bHavesign = True

        if bHavesign:
            print("该币种有买卖信号，请详阅复盘")

        # 最新一条数据额外检查
        latest = df.iloc[-1]
        latest_prev = df.iloc[-2]

        print(f"\n最新数据: {latest['time']} 收盘价={latest['close']:.2f}, RSI={latest['rsi']:.2f}, "
              f"KDJ_J={latest['kdj_j']:.2f}, TD_Count={latest['td_count']}")

        # RSI 超买/超卖
        latest_rsi_signal = ""
        if latest["rsi"] > 70:
            latest_rsi_signal = "RSI 超买"
        elif latest["rsi"] < 30:
            latest_rsi_signal = "RSI 超卖"

        # MACD 金叉/死叉
        latest_macd_signal = ""
        if latest_prev["macd"] < latest_prev["macd_signal"] and latest["macd"] > latest["macd_signal"]:
            latest_macd_signal = "MACD 金叉"
        elif latest_prev["macd"] > latest_prev["macd_signal"] and latest["macd"] < latest["macd_signal"]:
            latest_macd_signal = "MACD 死叉"

        # KDJ 金叉/死叉
        latest_kdj_signal = ""
        if latest_prev["kdj_k"] < latest_prev["kdj_d"] and latest["kdj_k"] > latest["kdj_d"]:
            latest_kdj_signal = "KDJ 金叉"
        elif latest_prev["kdj_k"] > latest_prev["kdj_d"] and latest["kdj_k"] < latest["kdj_d"]:
            latest_kdj_signal = "KDJ 死叉"

        # TD Sequential
        latest_td_signal = ""
        if latest["td_count"] == 9:
            latest_td_signal = "TD Sequential 九连上涨"
        elif latest["td_count"] == -9:
            latest_td_signal = "TD Sequential 九连下跌"

        # BOLL 趋势保持确认
        latest_boll_signal = ""
        if all(df.loc[len(df) - 1 - j, "close"] > df.loc[len(df) - 1 - j, "boll_upper"] for j in range(BOLL_TREND_CONFIRM)):
            latest_boll_signal = f"布林带上轨突破确认（连续{BOLL_TREND_CONFIRM}根）"
        if all(df.loc[len(df) - 1 - j, "close"] < df.loc[len(df) - 1 - j, "boll_lower"] for j in range(BOLL_TREND_CONFIRM)):
            latest_boll_signal = f"布林带下轨突破确认（连续{BOLL_TREND_CONFIRM}根）"

        # BOLL 反弹信号
        latest_boll_rebound_signal = ""
        if len(df) >= 2:  # 保证有前一根K线
            latest_prev = df.iloc[-2]
            if latest_prev["close"] < latest_prev["boll_lower"] and latest["close"] > latest["boll_lower"]:
                latest_boll_rebound_signal = "布林下轨反弹"
            elif latest_prev["close"] > latest_prev["boll_upper"] and latest["close"] < latest["boll_upper"]:
                latest_boll_rebound_signal = "布林上轨反弹"            

        # 判断最新数据是否触发买卖信号
        if (latest_rsi_signal and latest_kdj_signal) or latest_macd_signal or latest_td_signal or latest_boll_signal or latest_boll_rebound_signal:
            signal = f" {symbol.upper()} 收盘价={latest['close']:.2f}, " \
                     f"RSI={latest['rsi']:.2f}, KDJ_J={latest['kdj_j']:.2f}, TD_Count={latest['td_count']} "
            if latest_rsi_signal:
                signal += latest_rsi_signal + " "
                signal += latest_kdj_signal + " "
            if latest_macd_signal:
                signal += latest_macd_signal + " "
            if latest_td_signal:
                signal += latest_td_signal + " "
            if latest_boll_signal:
                signal += latest_boll_signal + " "
            if latest_boll_rebound_signal:
                signal += latest_boll_rebound_signal

            print(f"\n>>> " + signal)
            signals_list.append(signal)

    return signals_list