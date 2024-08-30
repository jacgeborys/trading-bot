from xAPIConnector import *
import time
import os
import numpy as np
import pandas as pd
import math
import csv
import datetime

def get_last_period_prices(client, symbol, period):
    period_in_seconds = 60 * period * 60 * 1000  # Adjusted for variable periods
    now = int(time.time() * 1000)
    from_timestamp = now - period_in_seconds

    response = client.execute({
        "command": "getChartLastRequest",
        "arguments": {
            "info": {
                "symbol": symbol,
                "period": period,  # Adjusted for variable periods
                "start": from_timestamp,
            }
        }
    })

    if response['status']:
        digits = response['returnData']['digits']
        rate_infos = response['returnData']['rateInfos']

        open_prices = [bar['open'] / (10 ** digits) for bar in rate_infos]
        close_prices = [(bar['open'] + bar['close']) / (10 ** digits) for bar in rate_infos]
        latest_open = rate_infos[-1]['open'] / (10 ** digits)
        latest_close = (rate_infos[-1]['open'] + rate_infos[-1]['close']) / (10 ** digits)
        high_prices = [open_price + (bar['high'] / (10 ** digits)) for open_price, bar in zip(open_prices, rate_infos)]
        low_prices = [open_price + (bar['low'] / (10 ** digits)) for open_price, bar in zip(open_prices, rate_infos)]
        volume = [bar['vol'] for bar in rate_infos]

        return close_prices, latest_open, latest_close, high_prices, low_prices, volume
    else:
        print(f"Failed to retrieve price data. Error: {response.get('errorCode')} - {response.get('errorDescr')}")
        return [], None, None, [], []

# Function to get current open positions and their counts
def get_current_positions(client):
    trades_response = client.execute({"command": "getTrades", "arguments": {"openedOnly": True}})
    trades = trades_response.get("returnData", [])

    positions = {'long': False, 'short': False, 'long_count': 0, 'short_count': 0, 'long_profits': [], 'short_profits': []}
    for trade in trades:
        trade_info = {'order': trade["order2"], 'profit': trade["profit"]}
        if trade["cmd"] == 0:  # 0 for long position
            positions['long'] = True
            positions['long_count'] += 1
            positions['long_profits'].append(trade_info)
        elif trade["cmd"] == 1:  # 1 for short position
            positions['short'] = True
            positions['short_count'] += 1
            positions['short_profits'].append(trade_info)

    return positions


def seconds_until_next_minute():
    current_time = time.time()  # current time in seconds
    next_minute = math.ceil(current_time / 60) * 60  # next full minute in seconds
    return next_minute - current_time







############################################ Historical Data ############################################
def get_historical_data(client, symbol, period, start, end):
    response = client.execute({
        "command": "getChartRangeRequest",
        "arguments": {
            "info": {
                "symbol": symbol,
                "period": period,
                "start": start,
                "end": end
            }
        }
    })

    if response['status']:
        digits = response['returnData']['digits']
        rate_infos = response['returnData']['rateInfos']

        open_prices = [bar['open'] / (10 ** digits) for bar in rate_infos]
        close_prices = [(bar['open'] + bar['close']) / (10 ** digits) for bar in rate_infos]
        high_prices = [open_price + (bar['high'] / (10 ** digits)) for open_price, bar in zip(open_prices, rate_infos)]
        low_prices = [open_price + (bar['low'] / (10 ** digits)) for open_price, bar in zip(open_prices, rate_infos)]
        volume = [bar['vol'] for bar in rate_infos]

        return close_prices, open_prices, high_prices, low_prices, volume
    else:
        print(f"Failed to retrieve historical data. Error: {response.get('errorCode')} - {response.get('errorDescr')}")
        return [], [], [], [], []
