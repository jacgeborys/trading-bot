from xAPIConnector import *
import time
import os
import numpy as np
import pandas as pd
import math
import csv
import datetime

def login_to_xtb(userId, password):
    client = APIClient()
    response = client.execute(loginCommand(userId=userId, password=password))
    if not response['status']:
        print(f'Login failed. Error code: {response["errorCode"]}')
        return None, None
    ssid = response['streamSessionId']
    return client, ssid