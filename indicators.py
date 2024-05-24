import pandas as pd
import numpy as np

def calculate_atr(highs, lows, closes, period=14):
    df = pd.DataFrame({'High': highs, 'Low': lows, 'Close': closes})
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    atr = true_range.rolling(period).mean()
    return atr

def calculate_supertrend(highs, lows, closes, atr, multiplier=3):
    highs = np.array(highs)
    lows = np.array(lows)
    closes = np.array(closes)

    hl2 = (highs + lows) / 2
    upper_band = hl2 + (multiplier * atr)
    lower_band = hl2 - (multiplier * atr)

    supertrend = np.zeros(len(closes))
    supertrend_direction = np.zeros(len(closes))

    for i in range(1, len(closes)):
        if closes[i] > upper_band[i - 1]:
            supertrend[i] = lower_band[i]
            supertrend_direction[i] = 1
        elif closes[i] < lower_band[i - 1]:
            supertrend[i] = upper_band[i]
            supertrend_direction[i] = -1
        else:
            supertrend[i] = supertrend[i - 1]
            supertrend_direction[i] = supertrend_direction[i - 1]

            if supertrend_direction[i] == 1 and closes[i] < lower_band[i]:
                supertrend_direction[i] = -1
            elif supertrend_direction[i] == -1 and closes[i] > upper_band[i]:
                supertrend_direction[i] = 1

    return supertrend, supertrend_direction

def calculate_ema(prices, period):
    prices_series = pd.Series(prices)
    ema = prices_series.ewm(span=period, adjust=False).mean()
    return ema

def calculate_macd(prices):
    if not prices:
        return None, None, None

    ema_12 = calculate_ema(prices, 12)
    ema_26 = calculate_ema(prices, 26)
    macd_line = ema_12 - ema_26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal_line

    return macd_line.iloc[-1], signal_line.iloc[-1], histogram.iloc[-1]

def calculate_vwap(prices, volume_data):
    if len(prices) != len(volume_data):
        return None

    vwap = np.sum(np.array(prices) * np.array(volume_data)) / np.sum(volume_data)
    return vwap

def calculate_sma(prices, period=20):
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period

def calculate_bollinger_bands(prices, period=20):
    sma = sum(prices[-period:]) / period
    standard_deviation = (sum([(price - sma) ** 2 for price in prices[-period:]]) / period) ** 0.5
    upper_band = sma + (standard_deviation * 2)
    lower_band = sma - (standard_deviation * 2)
    return upper_band, sma, lower_band

def calculate_rsi(prices, window=14):
    df = pd.DataFrame(prices, columns=['close'])
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).fillna(0)
    loss = (-delta.where(delta < 0, 0)).fillna(0)

    avg_gain = gain.rolling(window=window, min_periods=1).mean()
    avg_loss = loss.rolling(window=window, min_periods=1).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]
