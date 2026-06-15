#!/usr/bin/env python3
"""Test the upgraded CI-based NI API"""
import os
import requests
import json
import time
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Assumes the API server is already running on localhost.
# Wait briefly so the server can finish startup.
time.sleep(2)

files = {
    'placebo_file': open(os.path.join(ROOT, 'placebo_test.csv'), 'rb'),
    'baseline_file': open(os.path.join(ROOT, 'baseline_test.csv'), 'rb'),
    'treatment_file': open(os.path.join(ROOT, 'treatment_test.csv'), 'rb'),
}
data = {
    'metric': 'latency',
    'preservation_fraction': '0.8'
}

try:
    resp = requests.post('http://127.0.0.1:5000/api/ni-evaluate', files=files, data=data, timeout=10)
    print('Status Code:', resp.status_code)
    print('\nAPI Response:')
    print(json.dumps(resp.json(), indent=2))
except Exception as e:
    print(f'Error: {e}')
    sys.exit(1)

if resp.status_code != 200:
    sys.exit(1)
