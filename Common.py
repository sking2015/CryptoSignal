import sys

from ConstDef import g_ACD

def InitEnvironment():
    strExchange = "BINANCE"
    if len(sys.argv) > 1:
        if sys.argv[1] == "HTX":
            strExchange = "HTX"

    g_ACD.setExchange(strExchange)    


def save_simple(number, file='num.txt'):
    """一行保存"""
    with open(file, 'w') as f:
        f.write(str(number))    

def load_number_default(file='number.txt', default=0):
    """读取数字，失败时返回默认值"""
    try:
        with open(file, 'r') as f:
            return int(f.read().strip())
    except:
        return default    