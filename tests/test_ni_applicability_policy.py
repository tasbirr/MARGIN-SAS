import io
import os
import sys

import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app, REPORTLAB_AVAILABLE, INVALID_CONTROL_EFFECT_REASON, INVALID_CONTROL_EFFECT_WARNING


client = app.test_client()

# Covers assessable vs not-assessable policy and PDF output.


def df(metric, values):
    return pd.DataFrame({metric: values})


def post_eval(placebo, baseline, treatment, metric="latency", extra=None):
    streams = []
    for frame in (placebo, baseline, treatment):
        stream = io.BytesIO()
        frame.to_csv(stream, index=False)
        stream.seek(0)
        streams.append(stream)

    data = {
        "input_mode": "separate_files",
        "metric": metric,
        "preservation_fraction": "0.8",
        "bootstrap_resamples": "200",
        "placebo_file": (streams[0], "placebo.csv"),
        "baseline_file": (streams[1], "baseline.csv"),
        "treatment_file": (streams[2], "treatment.csv"),
    }
    if extra:
        data.update(extra)

    response = client.post("/api/ni-evaluate", content_type="multipart/form-data", data=data)
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


# Valid lower-is-better NI pass: active control beats placebo, treatment stays within margin.
valid_pass = post_eval(
    df("latency", [20.0] * 12),
    df("latency", [10.0] * 12),
    df("latency", [11.0] * 12),
)
assert valid_pass["ni_applicable"] is True
assert valid_pass["margin_status"] == "valid-control-effect"
assert valid_pass["methods"]["ci_based"]["ni_result"]["verdict"] == "non-inferior"
assert valid_pass["d_NI"] is not None


# Valid lower-is-better NI fail: assumptions valid, but treatment CI upper exceeds margin.
valid_fail = post_eval(
    df("latency", [20.0] * 12),
    df("latency", [10.0] * 12),
    df("latency", [13.0] * 12),
)
assert valid_fail["ni_applicable"] is True
assert valid_fail["methods"]["ci_based"]["ni_result"]["verdict"] == "inferior"
assert valid_fail["methods"]["ci_based"]["d_NI"] is not None


# Not assessable: lower-is-better active control does not beat placebo.
invalid_lower = post_eval(
    df("latency", [10.0] * 12),
    df("latency", [10.0] * 12),
    df("latency", [10.0] * 12),
)
assert invalid_lower["ni_applicable"] is False
assert invalid_lower["margin_status"] == "invalid-control-effect"
assert invalid_lower["d_NI"] is None
assert invalid_lower["ni_result"]["verdict"] == "not_assessable"
assert invalid_lower["reason"] == INVALID_CONTROL_EFFECT_REASON
assert invalid_lower["warning"] == INVALID_CONTROL_EFFECT_WARNING
assert invalid_lower["study_summary"]["placebo_mean"] == 10.0
assert invalid_lower["study_summary"]["baseline_mean"] == 10.0
assert invalid_lower["study_summary"]["M1"] == 0.0
assert invalid_lower["study_summary"]["M1_CI"]["lower"] == 0.0
assert "not assessable" in invalid_lower["study_summary"]["reasoning"]
assert "inferior under NI" not in invalid_lower["study_summary"]["reasoning"]


# Not assessable: higher-is-better active control does not beat placebo.
invalid_higher = post_eval(
    df("throughput", [100.0] * 12),
    df("throughput", [90.0] * 12),
    df("throughput", [89.0] * 12),
    metric="throughput",
)
assert invalid_higher["metric_orientation"] == "higher_is_better"
assert invalid_higher["M1"] == -10.0
assert invalid_higher["M1_CI"]["lower"] == -10.0
assert invalid_higher["d_NI"] is None
assert invalid_higher["ni_result"]["verdict"] == "not_assessable"


# Orientation consistency: higher-is-better M1 and worsening effect definitions.
valid_higher = post_eval(
    df("throughput", [80.0] * 12),
    df("throughput", [100.0] * 12),
    df("throughput", [97.0] * 12),
    metric="throughput",
)
assert valid_higher["M1"] == 20.0
assert valid_higher["ni_result"]["point_estimate_diff"] == 3.0
assert valid_higher["methods"]["ci_based"]["ni_result"]["verdict"] == "non-inferior"


# All formal NI-style methods must avoid formal pass/fail when the primary margin is invalid.
for method_key in ("ci_based", "bayesian", "synthesis", "mean_based"):
    method = invalid_lower["methods"][method_key]
    assert method["ni_applicable"] is False
    assert method["ni_result"]["verdict"] == "not_assessable"
    assert method["margin_status"] == "invalid-control-effect"
    assert method["d_NI"] is None
assert invalid_lower["methods"]["mean_based"]["exploratory_d_NI"] == 0.0
assert abs(invalid_higher["methods"]["mean_based"]["exploratory_d_NI"] + 2.0) < 1e-9


# Equivalence can be computed with an explicit equivalence margin, but remains a different claim.
invalid_with_equivalence = post_eval(
    df("latency", [10.0] * 12),
    df("latency", [10.0] * 12),
    df("latency", [10.1] * 12),
    extra={"equivalence_margin": "0.2"},
)
equivalence = invalid_with_equivalence["methods"]["equivalence"]["ni_result"]
assert equivalence["claim_type"] == "equivalence"
assert equivalence["verdict"] in {"equivalent", "not-equivalent"}
assert "different claim" in equivalence["note"]


# Multi-objective aggregation exposes not-assessable metrics instead of counting them as ordinary fails.
multi = post_eval(
    pd.DataFrame({"latency": [10.0] * 12, "throughput": [80.0] * 12}),
    pd.DataFrame({"latency": [10.0] * 12, "throughput": [100.0] * 12}),
    pd.DataFrame({"latency": [10.0] * 12, "throughput": [97.0] * 12}),
    metric="latency",
    extra={"metrics": "latency,throughput", "decision_mode": "strict"},
)
portfolio = multi["portfolio"]
assert portfolio["assessment_status"] == "not_assessable"
assert "latency" in portfolio["not_assessable_metrics"]
assert portfolio["metric_statuses"]["latency"]["ni_applicable"] is False
assert portfolio["metric_statuses"]["throughput"]["ni_applicable"] is True
assert "not silently counted" in portfolio["policy"]


# UI includes the warning mount point; PDF route accepts and renders not-assessable payloads.
html = client.get("/dashboard/evaluate").get_data(as_text=True)
assert 'id="niWarning"' in html
assert 'id="niWarningReason"' in html
if REPORTLAB_AVAILABLE:
    report = client.post("/api/study-report", json=invalid_lower)
    assert report.status_code == 200
    assert report.data.startswith(b"%PDF")
    assert b"Fixed-margin non-inferiority is not assessable" in report.data
    assert b"does not outperform placebo" in report.data


print("NI applicability policy tests passed.")
