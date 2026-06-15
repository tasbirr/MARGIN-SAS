#!/usr/bin/env python3
"""Tests for metric orientation, labeling, and margin sign conventions."""
import io
import os
import sys

import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import (
    app,
    compute_ni_margin_ci_based,
    compute_worsening_effect,
    get_metric_info,
    run_non_inferiority_test_ci_based,
)

# Focuses on orientation, aliasing, and label propagation rules.


def make_values(base: float, n: int = 30, jitter: float = 0.1) -> list[float]:
    return [base + ((i % 5) - 2) * jitter for i in range(n)]


def make_df(metric: str, base: float, n: int = 30, jitter: float = 0.1) -> pd.DataFrame:
    return pd.DataFrame({metric: make_values(base, n=n, jitter=jitter)})


# Alias and label mapping
info = get_metric_info("operational_cost")
assert info["key"] == "cost"
assert info["label"] == "Operational cost"
assert info["orientation"] == "lower_is_better"

# Lower-is-better: worsening effect is treatment - baseline
cost_info = get_metric_info("cost")
baseline_cost = make_df("cost", 10.0)
treatment_cost = make_df("cost", 12.0)
expected_cost_effect = float(treatment_cost["cost"].mean() - baseline_cost["cost"].mean())
calc_cost_effect = compute_worsening_effect(
    baseline_cost["cost"].mean(),
    treatment_cost["cost"].mean(),
    cost_info["orientation"],
)
assert abs(calc_cost_effect - expected_cost_effect) < 1e-9

cost_result = run_non_inferiority_test_ci_based(
    baseline_df=baseline_cost,
    treatment_df=treatment_cost,
    metric="cost",
    d_ni=999.0,
    orientation=cost_info["orientation"],
    confidence=0.95,
)
assert abs(cost_result["point_estimate_diff"] - expected_cost_effect) < 1e-6

# Higher-is-better: worsening effect is baseline - treatment
throughput_info = get_metric_info("throughput")
baseline_tp = make_df("throughput", 100.0)
treatment_tp = make_df("throughput", 90.0)
expected_tp_effect = float(baseline_tp["throughput"].mean() - treatment_tp["throughput"].mean())
calc_tp_effect = compute_worsening_effect(
    baseline_tp["throughput"].mean(),
    treatment_tp["throughput"].mean(),
    throughput_info["orientation"],
)
assert abs(calc_tp_effect - expected_tp_effect) < 1e-9

throughput_result = run_non_inferiority_test_ci_based(
    baseline_df=baseline_tp,
    treatment_df=treatment_tp,
    metric="throughput",
    d_ni=999.0,
    orientation=throughput_info["orientation"],
    confidence=0.95,
)
assert abs(throughput_result["point_estimate_diff"] - expected_tp_effect) < 1e-6

# d_NI is not defined when M1 lower bound is not positive
placebo_cost = make_df("cost", 8.0)
baseline_cost_worse = make_df("cost", 10.0)
m1_result = compute_ni_margin_ci_based(
    baseline_cost_worse,
    placebo_cost,
    "cost",
    cost_info["orientation"],
    0.8,
)
assert m1_result["ni_applicable"] is False
assert m1_result["d_NI"] is None
assert m1_result["m1_conservative_lower"] is None
assert m1_result["margin_status"] == "invalid-control-effect"

# API label override propagates to raw_data and top-level
client = app.test_client()
label_override = "Operational cost (USD)"

p_df = make_df("cost", 9.0, n=15)
b_df = make_df("cost", 10.0, n=15)
t_df = make_df("cost", 11.0, n=15)

p_data = io.BytesIO()
b_data = io.BytesIO()
t_data = io.BytesIO()

p_df.to_csv(p_data, index=False)
b_df.to_csv(b_data, index=False)
t_df.to_csv(t_data, index=False)

p_data.seek(0)
b_data.seek(0)
t_data.seek(0)

response = client.post(
    "/api/ni-evaluate",
    content_type="multipart/form-data",
    data={
        "metric": "operational_cost",
        "metric_label": label_override,
        "preservation_fraction": "0.8",
        "bootstrap_resamples": "200",
        "placebo_file": (p_data, "placebo_cost.csv"),
        "baseline_file": (b_data, "baseline_cost.csv"),
        "treatment_file": (t_data, "treatment_cost.csv"),
    },
)

assert response.status_code == 200
payload = response.get_json()
assert payload["metric"] == "cost"
assert payload["metric_label"] == label_override
assert payload["raw_data"]["metric_label"] == label_override
assert payload["metric_orientation"] == "lower_is_better"

print("All metric orientation and label checks passed.")
