import json
import os
import sys
import tempfile

import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app

client = app.test_client()

# Exercises /api/batch-run using temporary CSVs.

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

with tempfile.TemporaryDirectory() as tmp:
    def write_csv(df, name):
        path = os.path.join(tmp, name)
        df.to_csv(path, index=False)
        return path

    payload = {
        "decision_mode": "strict",
        "weighted_threshold": 0.7,
        "preservation_fractions": [0.8, 0.9],
        "metrics": ["latency", "throughput", "accuracy", "energy"],
        "scenarios": [
            {
                "name": "pass",
                "input_mode": "separate_files",
                "placebo_file": write_csv(placebo, "pass_placebo.csv"),
                "baseline_file": write_csv(baseline, "pass_baseline.csv"),
                "treatment_file": write_csv(pass_treatment, "pass_treatment.csv"),
            },
            {
                "name": "fail",
                "input_mode": "separate_files",
                "placebo_file": write_csv(placebo, "fail_placebo.csv"),
                "baseline_file": write_csv(baseline, "fail_baseline.csv"),
                "treatment_file": write_csv(fail_treatment, "fail_treatment.csv"),
            }
        ]
    }

    resp = client.post('/api/batch-run', data=json.dumps(payload), content_type='application/json')
    assert resp.status_code == 200, resp.get_data(as_text=True)
    result = resp.get_json()
    assert result['status'] == 'ok'
    assert len(result['scenario_results']) == 2

print('Batch runner test passed.')
