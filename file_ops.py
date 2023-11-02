from xAPIConnector import *
import time
import os
import numpy as np
import pandas as pd
import math
import csv
import datetime

def write_to_csv(row, filepath='C:\\Users\\Asus\\OneDrive\\Pulpit\\Rozne\\Python\\XTB\\_script\\excel\\trading_log.csv'):
    # Check if the file exists
    file_exists = os.path.isfile(filepath)

    with open(filepath, 'a', newline='') as f:
        writer = csv.writer(f)

        # If the file does not exist, write the header row first
        if not file_exists:
            writer.writerow(['Timestamp', '1min_Open', '1min_Close', '1min_MACD', '1min_Signal',
                             'VWAP', 'ATR', 'Position', 'Event', 'Direction', 'TP', 'Offset'])

        # Write the actual row
        writer.writerow(row)

