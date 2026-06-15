#!/usr/bin/env python3
"""Simple test to debug Flask app"""
import io
import os
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app

# Create temp CSV files
import pandas as pd

data = {'latency': [10.5, 10.6, 10.7, 10.8, 10.9, 11.0, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9]}
df = pd.DataFrame(data)

# Test with Flask test client
client = app.test_client()

# Create BytesIO objects instead of files
# Use in-memory streams to avoid filesystem I/O.
p_data = io.BytesIO()
b_data = io.BytesIO()
t_data = io.BytesIO()

df.to_csv(p_data, index=False)
df.to_csv(b_data, index=False)
df.to_csv(t_data, index=False)

p_data.seek(0)
b_data.seek(0)
t_data.seek(0)

response = client.post('/api/ni-evaluate',
    content_type='multipart/form-data',
    data={
        'metric': 'latency',
        'preservation_fraction': '0.8',
        'placebo_file': (p_data, 'p.csv'),
        'baseline_file': (b_data, 'b.csv'),
        'treatment_file': (t_data, 't.csv')
    }
)

print('Status:', response.status_code)
print('Response:', response.get_json())
