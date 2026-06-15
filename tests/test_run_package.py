import io
import os
import sys
import zipfile
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app, REPORTLAB_AVAILABLE

client = app.test_client()

# Verifies run package ZIP contains expected artifacts.

placebo = pd.DataFrame({"latency": [10] * 10})
baseline = pd.DataFrame({"latency": [9] * 10})
treatment = pd.DataFrame({"latency": [9.5] * 10})

p = io.BytesIO(); placebo.to_csv(p, index=False)
b = io.BytesIO(); baseline.to_csv(b, index=False)
t = io.BytesIO(); treatment.to_csv(t, index=False)
p.seek(0); b.seek(0); t.seek(0)

resp = client.post('/api/ni-evaluate',
    content_type='multipart/form-data',
    data={
        'input_mode': 'separate_files',
        'metric': 'latency',
        'preservation_fraction': '0.8',
        'placebo_file': (p, 'p.csv'),
        'baseline_file': (b, 'b.csv'),
        'treatment_file': (t, 't.csv')
    }
)
assert resp.status_code == 200, resp.get_data(as_text=True)
result = resp.get_json()
run_id = result.get('run_id')
assert run_id

pkg_resp = client.get(f"/api/run-package/{run_id}")
assert pkg_resp.status_code == 200, pkg_resp.get_data(as_text=True)

z = zipfile.ZipFile(io.BytesIO(pkg_resp.data))
namelist = set(z.namelist())
assert 'metadata.json' in namelist
assert 'result.json' in namelist
if REPORTLAB_AVAILABLE:
    assert 'report.pdf' in namelist

with z.open('metadata.json') as f:
    meta = f.read().decode('utf-8')
    assert 'run_id' in meta
    assert 'settings_used' in meta
    assert 'preprocess_summary' in meta

print('Run package test passed.')
