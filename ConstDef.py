DB_FILE = "kline.db"
SYMBOLS_TALBE = "all_symbol"

API_GET_KLINE_URL = "https://api.huobi.pro/market/history/kline"
API_GET_SYMBOLS_RUL = "https://api.huobi.pro/v1/common/symbols"

HTX_PERIOD_INTERVAL = {
    "5min":300,
    "15min":900,
    "30min":1800,
    "60min":3600,
    "2hour":7200,
    "4hour":14400,
    "6hour":3600*6,
    "12hour":3600*12,
    "1day":3600*24,
    "3day":3600*24*3,
    "1week":3600*24*7
}


BINANCE_INTERVAL = {
    "5m":300,
    "15m":900,
    "30m":1800,
    "1h":3600,
    "2h":7200,
    "4h":14400,
    "6h":3600*6,
    "12h":3600*12,
    "1d":3600*24,
    "3d":3600*24*3,
    "1w":3600*24*7
}

ALL_CONST ={
    "HTX":{
        "DB":DB_FILE,
        "Table_symbols":SYMBOLS_TALBE,
        "api_kline":API_GET_KLINE_URL,
        "api_symbols":API_GET_SYMBOLS_RUL,
        "interval":HTX_PERIOD_INTERVAL,
        "indexname":"ts"
    },

    "BINANCE":{
        "DB":"dbbinance.db",
        "Table_symbols":"all_symbol",
        "api_kline":"https://api.binance.com/api/v3/klines",
        "api_symbols":"https://api.binance.com/api/v3/exchangeInfo",
        "interval":BINANCE_INTERVAL,
        "indexname":"open_time"
    }
}

class CAllConstDef:
    def __init__(self):
        self.strExchange = "BINANCE"        

    def setExchange(self,exchange):
        self.strExchange = exchange
        self.ContDef = ALL_CONST[self.strExchange]

    def getExchange(self):
        return self.strExchange        

    def getDB(self):
        return self.ContDef["DB"]
    
    def getTableSymbols(self):
        return self.ContDef["Table_symbols"]
    
    def getApiKline(self):
        return self.ContDef["api_kline"]
    
    def getApiSymbols(self):
        return self.ContDef["api_symbols"]
    
    def getInterval(self):
        return self.ContDef["interval"]
    
    def getIndexName(self):
        return self.ContDef["indexname"]




g_ACD = CAllConstDef()
    