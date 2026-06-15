import io
import os
import sys
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app

client = app.test_client()

# Confirms bootstrap mode flag is reported in the response.

placebo = pd.DataFrame({"latency": [10] * 10})
baseline = pd.DataFrame({"latency": [9] * 10})
treatment = pd.DataFrame({"latency": [9] * 10})

p = io.BytesIO(); placebo.to_csv(p, index=False)
b = io.BytesIO(); baseline.to_csv(b, index=False)
t = io.BytesIO(); treatment.to_csv(t, index=False)
p.seek(0); b.seek(0); t.seek(0)

resp = client.post('/api/ni-evaluate',
    content_type='multipart/form-data',
    data={
        'input_mode': 'separate_files',
        'metric': 'latency',
        'bootstrap_mode': 'iid',
        'preservation_fraction': '0.8',
        'placebo_file': (p, 'p.csv'),
        'baseline_file': (b, 'b.csv'),
        'treatment_file': (t, 't.csv')
    }
)

assert resp.status_code == 200, resp.get_data(as_text=True)
result = resp.get_json()
assert result['ni_result']['bootstrap_ci']['mode'] == 'iid'
print('IID bootstrap mode test passed.')
