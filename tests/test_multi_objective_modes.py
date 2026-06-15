import io
import os
import sys
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app

client = app.test_client()

METRICS = 'latency,throughput,accuracy,energy'

# Covers strict/weighted/gatekeeper portfolio decisions.

def make_files(placebo_df, baseline_df, treatment_df):
    p = io.BytesIO(); placebo_df.to_csv(p, index=False)
    b = io.BytesIO(); baseline_df.to_csv(b, index=False)
    t = io.BytesIO(); treatment_df.to_csv(t, index=False)
    p.seek(0); b.seek(0); t.seek(0)
    return p, b, t

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

# All metrics pass
pass_treatment = pd.DataFrame({
    "latency": [11] * 10,
    "throughput": [95] * 10,
    "accuracy": [0.88] * 10,
    "energy": [16] * 10,
})

# Mixed: throughput + energy fail, latency + accuracy pass
mixed_treatment = pd.DataFrame({
    "latency": [11] * 10,
    "throughput": [80] * 10,
    "accuracy": [0.88] * 10,
    "energy": [25] * 10,
})

# 1) Strict pass
p, b, t = make_files(placebo, baseline, pass_treatment)
resp = client.post('/api/ni-evaluate',
    content_type='multipart/form-data',
    data={
        'input_mode': 'separate_files',
        'metrics': METRICS,
        'decision_mode': 'strict',
        'preservation_fraction': '0.8',
        'placebo_file': (p, 'p.csv'),
        'baseline_file': (b, 'b.csv'),
        'treatment_file': (t, 't.csv')
    }
)
assert resp.status_code == 200, resp.get_data(as_text=True)
result = resp.get_json()
assert result['portfolio']['status'] == 'green'

# 2) Strict fail (one metric fails)
p, b, t = make_files(placebo, baseline, mixed_treatment)
resp = client.post('/api/ni-evaluate',
    content_type='multipart/form-data',
    data={
        'input_mode': 'separate_files',
        'metrics': METRICS,
        'decision_mode': 'strict',
        'preservation_fraction': '0.8',
        'placebo_file': (p, 'p.csv'),
        'baseline_file': (b, 'b.csv'),
        'treatment_file': (t, 't.csv')
    }
)
assert resp.status_code == 200, resp.get_data(as_text=True)
result = resp.get_json()
assert result['portfolio']['status'] == 'red'

# 3) Weighted passes while strict fails
weights = 'latency:0.4,throughput:0.1,accuracy:0.4,energy:0.1'
p, b, t = make_files(placebo, baseline, mixed_treatment)
resp = client.post('/api/ni-evaluate',
    content_type='multipart/form-data',
    data={
        'input_mode': 'separate_files',
        'metrics': METRICS,
        'decision_mode': 'weighted',
        'metric_weights': weights,
        'weighted_threshold': '0.7',
        'preservation_fraction': '0.8',
        'placebo_file': (p, 'p.csv'),
        'baseline_file': (b, 'b.csv'),
        'treatment_file': (t, 't.csv')
    }
)
assert resp.status_code == 200, resp.get_data(as_text=True)
result = resp.get_json()
assert result['portfolio']['status'] in {'green', 'amber'}

# 4) Gatekeeper fails even when weighted would pass
p, b, t = make_files(placebo, baseline, mixed_treatment)
resp = client.post('/api/ni-evaluate',
    content_type='multipart/form-data',
    data={
        'input_mode': 'separate_files',
        'metrics': METRICS,
        'decision_mode': 'gatekeeper',
        'metric_weights': weights,
        'gatekeeper_metrics': 'energy',
        'weighted_threshold': '0.7',
        'preservation_fraction': '0.8',
        'placebo_file': (p, 'p.csv'),
        'baseline_file': (b, 'b.csv'),
        'treatment_file': (t, 't.csv')
    }
)
assert resp.status_code == 200, resp.get_data(as_text=True)
result = resp.get_json()
assert result['portfolio']['status'] == 'red'

print('Multi-objective modes test passed.')
