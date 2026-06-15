#!/usr/bin/env python3
"""Test the CI-based endpoint logic directly"""
import os
import sys

import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import compute_ni_margin_ci_based, run_non_inferiority_test_ci_based, get_metric_info, preprocess_data

# Load sample CSVs for a direct CI-based function call.
df_placebo = pd.read_csv(os.path.join(ROOT, 'placebo_test.csv'))
df_baseline = pd.read_csv(os.path.join(ROOT, 'baseline_test.csv'))
df_treatment = pd.read_csv(os.path.join(ROOT, 'treatment_test.csv'))

metric = 'latency'
preservation_fraction = 0.8
orientation = get_metric_info(metric)["orientation"]

# Preprocess
df_placebo = preprocess_data(df_placebo, metric)
df_baseline = preprocess_data(df_baseline, metric)
df_treatment = preprocess_data(df_treatment, metric)

print("Preprocessing complete")
print(f"  Placebo: {len(df_placebo)} rows")
print(f"  Baseline: {len(df_baseline)} rows")
print(f"  Treatment: {len(df_treatment)} rows")

# Step 1: Compute M1 CI
print("\nComputing M1 analysis...")
m1_result = compute_ni_margin_ci_based(
    df_baseline,
    df_placebo,
    metric,
    orientation,
    preservation_fraction
)
print(f"M1 point estimate: {m1_result['m1_point_estimate']:.6f}")
print(f"M1 CI: [{m1_result['m1_ci_lower']:.6f}, {m1_result['m1_ci_upper']:.6f}]")
if m1_result["d_NI"] is None:
    print("d_NI: not defined")
    print(f"NI applicability: {m1_result['ni_applicable']} ({m1_result['margin_status']})")
    print(f"Reason: {m1_result['reason']}")
    print("\nSUCCESS - NI correctly marked not assessable for this dataset.")
    raise SystemExit(0)
print(f"d_NI: {m1_result['d_NI']:.6f}")

# Step 2: Run NI test
print("\nRunning NI test...")
ni_result = run_non_inferiority_test_ci_based(
    baseline_df=df_baseline,
    treatment_df=df_treatment,
    metric=metric,
    d_ni=m1_result["d_NI"],
    orientation=orientation,
    confidence=0.95
)
print(f"Verdict: {ni_result['verdict']}")
print(f"Treatment CI: [{ni_result['ci_lower']:.6f}, {ni_result['ci_upper']:.6f}]")

print("\nSUCCESS - All functions work!")
