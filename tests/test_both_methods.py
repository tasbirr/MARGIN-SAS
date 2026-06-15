import io
import json
import os
import sys

import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app

client = app.test_client()

# Compares CI-based and mean-based outputs for the same inputs.

# Read test files
p_df = pd.read_csv(os.path.join(ROOT, 'placebo_test.csv'))
b_df = pd.read_csv(os.path.join(ROOT, 'baseline_test.csv'))
t_df = pd.read_csv(os.path.join(ROOT, 'treatment_test.csv'))

print('=== Test Data Loaded ===')
print(f'Placebo: {len(p_df)} rows')
print(f'Baseline: {len(b_df)} rows')
print(f'Treatment: {len(t_df)} rows')
print()

# Prepare file data
p_data = io.BytesIO()
b_data = io.BytesIO()
t_data = io.BytesIO()

p_df.to_csv(p_data, index=False)
b_df.to_csv(b_data, index=False)
t_df.to_csv(t_data, index=False)

p_data.seek(0)
b_data.seek(0)
t_data.seek(0)

# Test API
response = client.post('/api/ni-evaluate',
    content_type='multipart/form-data',
    data={
        'metric': 'latency',
        'preservation_fraction': '0.8',
        'placebo_file': (p_data, 'placebo_test.csv'),
        'baseline_file': (b_data, 'baseline_test.csv'),
        'treatment_file': (t_data, 'treatment_test.csv')
    }
)

print('=== API Response ===')
print(f'Status: {response.status_code}')
result = response.get_json()

if response.status_code != 200:
    print('ERROR:', result)
else:
    print()
    print('=== CI-based (95-95) Method ===')
    ci_method = result['methods']['ci_based']
    print(f'M1: {ci_method["M1"]:.6f}')
    print(f'M1 CI: [{ci_method["M1_CI"]["lower"]:.6f}, {ci_method["M1_CI"]["upper"]:.6f}]')
    if ci_method["d_NI"] is None:
        print('d_NI: not defined')
    else:
        print(f'd_NI: {ci_method["d_NI"]:.6f}')
    print(f'Verdict: {ci_method["ni_result"]["verdict"].upper()}')
    print(f'Treatment Mean: {ci_method["ni_result"]["treatment_mean"]:.6f}')
    print(f'Baseline Mean: {ci_method["ni_result"]["baseline_mean"]:.6f}')
    print(f'CI Upper: {ci_method["ni_result"]["ci_upper"]:.6f}')
    if ci_method["d_NI"] is None:
        print(f'Decision: not assessable ({ci_method["reason"]})')
    else:
        print(f'Decision: CI upper ({ci_method["ni_result"]["ci_upper"]:.6f}) <= d_NI ({ci_method["d_NI"]:.6f})? {ci_method["ni_result"]["ci_upper"] <= ci_method["d_NI"]}')

    print()
    print('=== Mean-based Method ===')
    mean_method = result['methods']['mean_based']
    print(f'M1: {mean_method["M1"]:.6f}')
    if mean_method["d_NI"] is None:
        print('d_NI: not defined for formal NI')
        if mean_method.get("exploratory_d_NI") is not None:
            print(f'exploratory d_NI: {mean_method["exploratory_d_NI"]:.6f}')
    else:
        print(f'd_NI: {mean_method["d_NI"]:.6f}')
    print(f'Verdict: {mean_method["ni_result"]["verdict"].upper()}')
    print(f'Treatment Mean: {mean_method["ni_result"]["treatment_mean"]:.6f}')
    print(f'Baseline Mean: {mean_method["ni_result"]["baseline_mean"]:.6f}')
    print(f'Diff: {mean_method["ni_result"]["difference_worse_than_baseline"]:.6f}')
    if mean_method["ni_result"]["verdict"] == "not_assessable":
        print(f'Decision: exploratory only ({mean_method["ni_result"].get("exploratory_verdict", "N/A")})')
    else:
        print(f'Decision: Diff ({mean_method["ni_result"]["difference_worse_than_baseline"]:.6f}) <= d_NI ({mean_method["d_NI"]:.6f})? {mean_method["ni_result"]["difference_worse_than_baseline"] <= mean_method["d_NI"]}')
