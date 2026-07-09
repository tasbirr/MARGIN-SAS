# MARGIN-SAS

MARGIN-SAS is a Flask REST API and dashboard for evaluating Self-Adaptive Systems (SAS) decision-making techniques using Non-Inferiority (NI) trial logic.

# Code Download

To download the code, Please use the Code option above and then select Download Zip option

## Demonstration Video

A short demonstration video of the artefact is available here:

https://youtu.be/ZmMSxkEUH8U

The video demonstrates the main workflow of MARGIN-SAS, including selecting the analysis method, configuring input data, choosing the QoS metric and preservation settings, running the evaluation, interpreting the non-inferiority outputs, and downloading the generated report.

## Quick start (Windows, macOS, Linux)

Recommended Python: 3.10-3.13 (3.11 or 3.13 recommended). Python 3.14 is not supported by the pinned dependencies.

If you want a one-command setup, use the bootstrap scripts:
- Windows (PowerShell): `powershell -ExecutionPolicy Bypass -File scripts\\bootstrap.ps1`
- macOS/Linux: `bash scripts/bootstrap.sh`

Add `-Run` (PowerShell) or `--run` (bash) to start the server after setup.
If your Python version is not auto-detected, pass it explicitly:
- Windows: `-PythonPath C:\\path\\to\\python.exe`
- macOS/Linux: `--python /path/to/python3.13`

### 1) Create and activate a virtual environment

Replace `3.13` below with whichever 3.10-3.13 version you have installed.

Windows (PowerShell):
```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Windows (cmd):
```bat
py -3.13 -m venv .venv
.\.venv\Scripts\activate.bat
```

macOS/Linux:
```bash
python3.13 -m venv .venv
source .venv/bin/activate
```

### 2) Install dependencies

Windows:
```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\doctor.py
```

macOS/Linux:
```bash
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python scripts/doctor.py
```

### 3) Run the server

Windows:
```powershell
.\.venv\Scripts\python.exe run_server.py
```

macOS/Linux:
```bash
./.venv/bin/python run_server.py
```

Open the dashboard at: http://127.0.0.1:5000/dashboard

Note: The API enforces a 20 MB upload limit per request.
Tip: If you have multiple Python versions installed, prefer `py -3.13` (Windows) or `python3.13` (macOS/Linux), or substitute whichever 3.10-3.13 version you have.

## Using the datasets (submission layout)

In the submission zip, the real datasets live in the sibling `Data/` folder at the top level:

DataCodeLogbook/
- MARGIN-SAS/
- Data/

From the `MARGIN-SAS/` folder, the dataset paths are:
- ../Data/IoT data used
- ../Data/NI_DatSet_IoT
- ../Data/NI_Trial_DataSet_RDMSim
- ../Data/RDMSim data used

IoT PriAwaRE (treatment) run using separate files:
1) In the UI choose `input_mode=separate_files`.
2) Upload these three files from `../Data/IoT data used`:
  - IoTMECsattimestep_Placebo.txt
  - MECSattimestep_Baseline.txt
  - IoTMECsattimestep_Treatment.txt
3) Select the metric used in the report for this dataset (the numeric column is auto-detected).

RDMSim MinC Scenario0 (energy):
1) Use `input_mode=single_file_columns`.
2) Choose the combined file (for example: RDM_MinC_Scenario0.csv) from `../Data/RDMSim data used`.
3) Map placebo/baseline/treatment columns.
4) Select the `energy` metric and keep the rest of the settings as in the report.

The remaining folders under `../Data/` contain the full datasets provided for experimentation.

If you want a quick demo without the large datasets, you can use the included sample CSVs (these are demo/test-only, not part of the real datasets):
- Use `input_mode=separate_files`.
- Upload `placebo_test.csv`, `baseline_test.csv`, and `treatment_test.csv`.
- Select the `accuracy` metric.

## Visual walkthrough (web interface)

1) Start the server (see Quick start above).
2) Open http://127.0.0.1:5000/dashboard in a browser.
3) Go to http://127.0.0.1:5000/dashboard/evaluate.
4) Upload either the IoT PriAwaRE files or the RDMSim MinC Scenario0 file (see above).
5) Run the evaluation and review the charts, verdict, and summary values.

## Compatibility

- Windows, macOS, or Linux with Python 3.10-3.13 (3.11 or 3.13 recommended)
- Python 3.14 is not supported by the pinned dependencies
- pip and internet access for installing dependencies from PyPI
- Node.js only if you run `tests/test_frontend_plot_policy.py`
- Any modern browser (Chrome, Edge, Firefox, Safari)
- Runs locally; no external services or internet access required at runtime

## What it does

**Core functionality:**
- Accepts placebo, baseline (control), and treatment QoS data
- Supports three input modes: separate files, single combined file with column mapping, or manual entry
- Supports multi-objective evaluation across multiple metrics with strict, weighted, or gatekeeper decisions
- Validates file type, metric choice, numeric conversion, sample size (N>=10), and parameter ranges
- Computes:
  - **M1**: Baseline benefit vs placebo (direction-aware)
  - **d_NI**: NI margin = M1_lower * (1 - preservation_fraction)
  - **NI decision**: CI-based fixed-margin test (95-95 method)
  - **Bootstrap CI** for robustness
  - **Block bootstrap** for dependence-aware robustness (optional)
  - **Bayesian NI**, **synthesis**, **equivalence**, and **mean-based** comparisons
- Returns comprehensive JSON with study summary and plot-ready data
- Exports a PDF study report
- Generates a run package (metadata + JSON + PDF) for reproducibility

**Supported metrics:**
- `latency` (lower-better)
- `throughput` (higher-better)
- `accuracy` (higher-better)
- `energy` (lower-better)
- `cost` (lower-better)
- `response_time` (lower-better)

## Dashboard

- `/dashboard` for overview
- `/dashboard/evaluate` to run analyses
- `/dashboard/methods` for method definitions



## API endpoints

**GET /**
Health check endpoint.

**POST /api/ni-evaluate**
Main evaluation endpoint (multipart/form-data). Parameters:

Common parameters:
- `metric`: latency | throughput | accuracy | energy | cost | response_time
- `preservation_fraction`: float in [0, 1], default 0.8
- `bootstrap_resamples`: int in [200, 20000], default 1000
- `bootstrap_seed`: optional int >= 0 (default 42)
- `bootstrap_mode`: iid | block
- `bootstrap_block_size`: int > 0 (required for block)
- `equivalence_margin`: optional float > 0
- `bayes_prior_mean`, `bayes_prior_sd`, `bayes_threshold`
- `synthesis_effects`, `synthesis_ses` (comma-separated lists)

Input modes:
- `input_mode=separate_files`
  - `placebo_file`, `baseline_file`, `treatment_file`
- `input_mode=single_file_columns`
  - `combined_file`
  - `placebo_column`, `baseline_column`, `treatment_column`
  - `combined_has_header`: true/false (default true)
- `input_mode=manual_entry`
  - `placebo_values`, `baseline_values`, `treatment_values`

**POST /api/batch-run**
Batch scenario runner (application/json). Runs multiple scenarios, metrics, and preservation fractions.

**GET /api/run-package/<run_id>**
Downloads a ZIP containing metadata.json, result.json, and report.pdf (if available).

**POST /api/study-report**
Accepts the JSON returned from `/api/ni-evaluate` and returns a PDF summary report.

Example payload:
```json
{
  "decision_mode": "strict",
  "preservation_fractions": [0.8, 0.9],
  "metrics": ["latency", "throughput", "accuracy", "energy"],
  "scenarios": [
    {
      "name": "demo_pass",
      "input_mode": "separate_files",
      "placebo_file": "C:\\path\\to\\placebo.csv",
      "baseline_file": "C:\\path\\to\\baseline.csv",
      "treatment_file": "C:\\path\\to\\treatment.csv"
    }
  ]
}
```

## Multi-objective aggregation (definition)

Per metric, the platform uses the CI-based verdict from the fixed-margin method. A metric is a pass if the verdict is `non-inferior`. Equivalence is reported separately and does not change portfolio aggregation unless you handle it in your client.

Weights are normalized to sum to 1. The weighted score is:

S = sum(w_m * I(pass_m))

The decision rules are:
- **Strict**: pass if all metrics pass.
- **Weighted**: pass if S >= weighted_threshold.
- **Gatekeeper**: pass only if every gatekeeper metric passes and S >= weighted_threshold.

Portfolio status uses a traffic-light summary: green (acceptable), amber (borderline or method disagreement), red (not acceptable).

## Example usage

```python
import requests

files = {
  'placebo_file': open(r'C:\\path\\to\\IoTMECsattimestep_Placebo.txt', 'rb'),
  'baseline_file': open(r'C:\\path\\to\\MECSattimestep_Baseline.txt', 'rb'),
  'treatment_file': open(r'C:\\path\\to\\IoTMECsattimestep_Treatment.txt', 'rb'),
}
data = {
    'metric': 'accuracy',
    'preservation_fraction': '0.8',
    'bootstrap_seed': '42'
}

response = requests.post('http://127.0.0.1:5000/api/ni-evaluate', files=files, data=data)
result = response.json()

print(f"M1: {result['M1']}")
print(f"d_NI: {result['d_NI']}")
print(f"Verdict: {result['ni_result']['verdict']}")
```

## Tests

Run the full local suite:

```bash
python scripts/run_tests.py
```

Or run individual checks:

```bash
python tests/test_ci_endpoint.py
python tests/test_both_methods.py
python tests/test_flask_client.py
```

These tests use the sample CSVs shipped in the repo root: placebo_test.csv, baseline_test.csv, treatment_test.csv.

Additional tests (no server required; use Flask test client):

```bash
python tests/test_multi_objective.py
python tests/test_multi_objective_modes.py
python tests/test_bootstrap_modes.py
python tests/test_run_package.py
python tests/test_demo_datasets.py
python tests/test_batch_runner.py
python tests/test_block_bootstrap.py
python tests/test_metric_orientation.py
python tests/test_ni_applicability_policy.py
python tests/test_frontend_plot_policy.py
```

Note: tests/test_frontend_plot_policy.py requires Node.js.

For live API test (requires the server running):

```bash
python run_server.py
python tests/test_api_ci.py
```

Tip: On Windows without activation, use `.\.venv\Scripts\python.exe` instead of `python`.

## Production deployment (optional)

Linux/macOS:
```bash
pip install gunicorn
gunicorn -b 0.0.0.0:5000 app:app
```

Windows: gunicorn does not support Windows. Use a Windows-compatible WSGI server (for example, waitress) or run `run_server.py` for local testing.

## Data storage

Uploaded files are saved to the `data/` folder for reproducibility.

Run artifacts (metadata, JSON, PDF) are stored in `runs/`.

## Submission contents

The submitted zip is organised as:

DataCodeLogbook/
- MARGIN-SAS/          Source code, dashboard, API, tests, README, requirements
- Data/                Full provided datasets and selected report datasets
- Logbook/             ECM3401 activity logbook

The folders `Data/RDMSim data used` and `Data/IoT data used` contain the exact files used for the report results.

## Planned enhancements

- Richer Bayesian inference models
- Persistent experiment tracking
- Additional export formats and dashboard analytics
