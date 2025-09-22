import sys

from ConstDef import g_ACD

def InitEnvironment():
    strExchange = "BINANCE"
    if len(sys.argv) > 1:
        if sys.argv[1] == "HTX":
            strExchange = "HTX"

    g_ACD.setExchange(strExchange)    