import io
import os
import sys
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app

client = app.test_client()

# Smoke test for multi-metric aggregation payload.

# Create deterministic multi-metric data
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

treatment = pd.DataFrame({
    "latency": [11] * 10,
    "throughput": [95] * 10,
    "accuracy": [0.88] * 10,
    "energy": [16] * 10,
})

p_data = io.BytesIO(); placebo.to_csv(p_data, index=False)
b_data = io.BytesIO(); baseline.to_csv(b_data, index=False)
t_data = io.BytesIO(); treatment.to_csv(t_data, index=False)
p_data.seek(0); b_data.seek(0); t_data.seek(0)

resp = client.post('/api/ni-evaluate',
    content_type='multipart/form-data',
    data={
        'input_mode': 'separate_files',
        'metrics': 'latency,throughput,accuracy,energy',
        'decision_mode': 'strict',
        'preservation_fraction': '0.8',
        'placebo_file': (p_data, 'p.csv'),
        'baseline_file': (b_data, 'b.csv'),
        'treatment_file': (t_data, 't.csv'),
    }
)

assert resp.status_code == 200, resp.get_data(as_text=True)
result = resp.get_json()

assert 'metric_results' in result
assert 'portfolio' in result
assert result['portfolio']['status'] in {'green', 'amber'}
print('Multi-objective test passed.')
