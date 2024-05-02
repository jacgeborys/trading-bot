from xAPIConnector import *
import time
import os
import numpy as np
import pandas as pd
import math
import csv
import datetime

def calculate_atr(highs, lows, closes, period=5):
    """
    Calculate Average True Range (ATR) based on highs, lows, and closes.
    """
    df = pd.DataFrame({'High': highs, 'Low': lows, 'Close': closes})
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    atr = true_range.rolling(period).mean()
    return atr.iloc[-1]

def calculate_ema(prices, period):
    """Calculate Exponential Moving Average using pandas."""
    prices_series = pd.Series(prices)
    ema = prices_series.ewm(span=period, adjust=False).mean()
    return ema

def calculate_macd(prices):
    """Calculate MACD and Signal line using pandas."""
    if not prices:
        return None, None

    # Short-term EMA
    ema_12 = calculate_ema(prices, 12)
    # Long-term EMA
    ema_26 = calculate_ema(prices, 26)
    # MACD Line
    macd_line = ema_12 - ema_26
    # Signal Line
    signal_line = macd_line.ewm(span=9, adjust=False).mean()

    histogram = macd_line.iloc[-1] - signal_line.iloc[-1]

    # Return the last values
    return macd_line.iloc[-1], signal_line.iloc[-1], histogram

def calculate_vwap(prices, volume_data):
    if len(prices) != len(volume_data):
        return None

    # Assuming prices and volume_data are aligned by index (i.e., same time period)
    vwap = np.sum(np.array(prices) * np.array(volume_data)) / np.sum(volume_data)
    return vwap

def calculate_sma(prices, period=20):
    if len(prices) < period:
        return None  # Not enough data
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
    return rsi.iloc[-1]  # Return only the last item, which is the most recent RSI value


def calculate_adl(highs, lows, closes, volumes):
    """
    Calculate the Accumulation/Distribution Line using high, low, close prices and volume.
    """
    df = pd.DataFrame({'High': highs, 'Low': lows, 'Close': closes, 'Volume': volumes})
    mfm = ((df['Close'] - df['Low']) - (df['High'] - df['Close'])) / (df['High'] - df['Low'])
    mfv = mfm * df['Volume']
    adl = mfv.cumsum()
    return adl.iloc[-1]

def calculate_obv(closes, volumes):
    obv = [0]  # Starting the OBV from zero for the first day
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv.append(obv[-1] + volumes[i])
        elif closes[i] < closes[i - 1]:
            obv.append(obv[-1] - volumes[i])
        else:
            obv.append(obv[-1])
    return obv


