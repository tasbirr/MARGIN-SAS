import io
import os
import sys

import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app

client = app.test_client()

# Checks demo-like scenarios produce expected portfolio status.

def post_demo(placebo, baseline, treatment, expect_status):

    p = io.BytesIO(); placebo.to_csv(p, index=False)
    b = io.BytesIO(); baseline.to_csv(b, index=False)
    t = io.BytesIO(); treatment.to_csv(t, index=False)
    p.seek(0); b.seek(0); t.seek(0)

    resp = client.post('/api/ni-evaluate',
        content_type='multipart/form-data',
        data={
            'input_mode': 'separate_files',
            'metrics': 'latency,throughput,accuracy,energy',
            'decision_mode': 'strict',
            'preservation_fraction': '0.8',
            'placebo_file': (p, 'p.csv'),
            'baseline_file': (b, 'b.csv'),
            'treatment_file': (t, 't.csv')
        }
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    result = resp.get_json()
    assert result['portfolio']['status'] == expect_status

placebo = pd.DataFrame({
    "latency": [20] * 10,
    "throughput": [50] * 10,
    "accuracy": [0.5] * 10,
    "energy": [30] * 10,
})

baseline = pd.DataFrame({
    "latency": [10] * 10,
    "throughput": [100] * 10,
    "accuracy": [0.9] * 10,
    "energy": [15] * 10,
})

pass_treatment = pd.DataFrame({
    "latency": [11] * 10,
    "throughput": [95] * 10,
    "accuracy": [0.88] * 10,
    "energy": [16] * 10,
})

fail_treatment = pd.DataFrame({
    "latency": [14] * 10,
    "throughput": [70] * 10,
    "accuracy": [0.7] * 10,
    "energy": [25] * 10,
})

post_demo(placebo, baseline, pass_treatment, 'green')
post_demo(placebo, baseline, fail_treatment, 'red')

print('Demo datasets test passed.')
