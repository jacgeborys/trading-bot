from xAPIConnector import *
import time
import os
import numpy as np
import pandas as pd
import math
import csv
import datetime

def get_last_period_prices(client, symbol, period = 1):
    period_in_seconds = 360 * period * 60 * 1000  # Adjusted for variable periods
    now = int(time.time() * 1000)
    from_timestamp = now - period_in_seconds

    response = client.execute({
        "command": "getChartLastRequest",
        "arguments": {
            "info": {
                "symbol": symbol,
                "period": period,  # Adjusted for variable periods
                "start": from_timestamp,
                "end": now
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