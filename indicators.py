from xAPIConnector import *
import time
import os
import numpy as np
import pandas as pd
import math
import csv
import datetime

def calculate_atr(highs, lows, closes, period=14):
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

def calculate_rsi(df, window=15):
    """Calculate RSI for a given DataFrame and window period."""
    # Calculate the difference between consecutive prices
    delta = df['close'].diff().dropna()

    # Separate the up and down gains
    up, down = delta.copy(), delta.copy()
    up[up < 0] = 0
    down[down > 0] = 0

    # Calculate the EWMA (Exponential Weighted Moving Average) of up and down gains
    roll_up = up.ewm(span=window).mean()
    roll_down = down.abs().ewm(span=window).mean()

    # Calculate the RSI
    RS = roll_up / roll_down
    RSI = 100.0 - (100.0 / (1.0 + RS))

    return RSI
