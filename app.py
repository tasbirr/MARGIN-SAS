"""
MARGIN-SAS Backend (Prototype)

This Flask backend is a prototype for evaluating Self-Adaptive System (SAS)
decision-making techniques using Non-Inferiority (NI) trial logic.

Current capabilities:
- Accepts 3 datasets: placebo, baseline (control), treatment
- Validates QoS metric column exists and is numeric
- Preprocesses data (drops empty/NaN metric rows)
- Computes M1 and d_NI (basic mean-based placeholder)
- Runs a placeholder NI decision (direction-aware)
- Returns structured JSON output

Planned extensions:
- Proper fixed-margin (95–95) CI-based NI test
- Synthesis method for margin derivation
- Bayesian NI (posterior probability)
- Multi-metric NI evaluation
- Front-end dashboard and report export
"""

from flask import Flask, request, jsonify, send_from_directory, abort, make_response
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge
import hashlib
import uuid
import zipfile
import os
import io
import json
import re
from datetime import datetime
import pandas as pd
import numpy as np
from scipy import stats

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False

app = Flask(__name__)

MAX_UPLOAD_MB = 20
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

# Where uploads are stored (useful for reproducibility/debugging)
UPLOAD_FOLDER = "data"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

RUNS_FOLDER = "runs"
os.makedirs(RUNS_FOLDER, exist_ok=True)

# CSV and TXT files are supported (TXT is auto-parsed as tabular data)
ALLOWED_EXTENSIONS = {"csv", "txt"}

# QoS metrics supported for now
METRIC_CLASSIFICATION = {
    "latency": "lower_is_better",
    "energy": "lower_is_better",
    "throughput": "higher_is_better",
    "accuracy": "higher_is_better",
    "cost": "lower_is_better",
    "response_time": "lower_is_better",
}

METRIC_LABELS = {
    "latency": "Latency",
    "energy": "Energy",
    "throughput": "Throughput",
    "accuracy": "Accuracy",
    "cost": "Operational cost",
    "response_time": "Response time",
}

METRIC_ALIASES = {
    "operational_cost": "cost",
    "op_cost": "cost",
    "minc": "cost",
    "response-time": "response_time",
    "responsetime": "response_time",
}

VALID_QOS_METRICS = set(METRIC_CLASSIFICATION.keys())

# Minimum number of rows required after preprocessing
MIN_N = 10

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

INVALID_CONTROL_EFFECT_STATUS = "invalid-control-effect"
NOT_ASSESSABLE_VERDICT = "not_assessable"
INVALID_CONTROL_EFFECT_REASON = (
    "Active control does not demonstrate benefit over placebo on the selected metric, "
    "so fixed-margin non-inferiority is not defensible."
)
INVALID_CONTROL_EFFECT_WARNING = (
    "Fixed-margin non-inferiority is not assessable in this scenario because the active control "
    "does not outperform placebo on the selected metric."
)


@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(_):
    return jsonify({"error": f"Uploaded file too large. Max size is {MAX_UPLOAD_MB} MB."}), 413


# Check if a file is an allowed type
def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# Load CSV from Flask FileStorage into DataFrame
def load_csv_from_file(file_storage) -> pd.DataFrame:
    try:
        content = file_storage.read()
        df = pd.read_csv(io.BytesIO(content))
        return df
    except Exception as e:
        raise ValueError(f"Failed to parse CSV: {e}")


def load_tabular_file(file_path: str, has_header: bool | None = None) -> pd.DataFrame:
    """
    Robust tabular loader for real-world dataset files.
    Tries common delimiters for CSV/TXT outputs from tools/simulators.
    Set has_header to False to treat the first row as data and auto-name columns.
    """
    last_error = None
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".txt":
        # Typical simulator outputs are whitespace/tab separated without headers.
        read_attempts = [
            {"sep": r"\s+", "engine": "python", "header": None},
            {"sep": "\t", "header": None},
            {"sep": ",", "header": None},
            {"sep": ";", "header": None},
        ]
    else:
        read_attempts = [
            {"sep": ","},
            {"sep": "\t"},
            {"sep": ";"},
            {"sep": None, "engine": "python"},  # auto-detect delimiter
        ]

    for kwargs in read_attempts:
        try:
            if has_header is True:
                kwargs = {**kwargs, "header": 0}
            elif has_header is False:
                kwargs = {**kwargs, "header": None}

            df = pd.read_csv(file_path, **kwargs)
            if df is not None and not df.empty and len(df.columns) >= 1:
                # Normalize columns for downstream processing.
                if has_header is False:
                    df.columns = [f"col{i+1}" for i in range(len(df.columns))]
                else:
                    df.columns = [str(c) for c in df.columns]
                return df
        except Exception as e:
            last_error = e

    raise ValueError(f"Failed to parse tabular file '{os.path.basename(file_path)}': {last_error}")


def harmonize_metric_column(df: pd.DataFrame, metric: str) -> pd.DataFrame:
    """
    If required metric column is missing (common in TXT logs), infer a usable
    numeric column and map it to the requested metric name.
    """
    if metric in df.columns:
        return df

    if df is None or df.empty:
        return df

    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    if not numeric_cols:
        # attempt coercion for object columns
        for c in df.columns:
            converted = pd.to_numeric(df[c], errors="coerce")
            if converted.notna().sum() > 0:
                df[c] = converted
        numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]

    if not numeric_cols:
        return df

    # Prefer non-index-like numeric column when data has two columns (time, value).
    chosen = None
    if len(numeric_cols) >= 2:
        for c in numeric_cols:
            series = df[c].dropna().astype(float)
            if len(series) >= 2:
                diffs = np.diff(series.values[: min(len(series), 30)])
                # very simple index-like heuristic: mostly +1 increments
                if not (np.isclose(diffs, 1.0).mean() > 0.8):
                    chosen = c
                    break
    if chosen is None:
        chosen = numeric_cols[-1]

    df[metric] = pd.to_numeric(df[chosen], errors="coerce")
    return df


# Validate that the dataset contains a required QoS column and it is numeric
def validate_qos_dataset(df: pd.DataFrame, required_metrics: set[str]) -> dict:
    errors = []

    if df is None or df.empty:
        errors.append("Dataset is empty.")
        return {"ok": False, "errors": errors}

    # Ensure required QoS columns exist
    missing = [m for m in required_metrics if m not in df.columns]
    if missing:
        errors.append(f"Missing required QoS columns: {', '.join(missing)}")

    # Ensure those columns are numeric or convertible
    for m in required_metrics:
        if m in df.columns:
            numeric = pd.to_numeric(df[m], errors="coerce")
            if numeric.notna().sum() == 0:
                errors.append(f"QoS column '{m}' must be numeric.")

    return {"ok": len(errors) == 0, "errors": errors}


# Basic preprocessing
# - Drop rows that are fully empty
# - Drop rows where the chosen metric is NaN
def preprocess_data(df: pd.DataFrame, metric: str) -> pd.DataFrame:
    if df is None:
        return df
    df = df.dropna(how="all")
    if metric in df.columns:
        # Coerce metric to numeric for robustness with real-world CSVs
        # (e.g., values parsed as strings). Non-numeric values become NaN
        # and are dropped below.
        df[metric] = pd.to_numeric(df[metric], errors="coerce")
        df = df.dropna(subset=[metric], how="any")
    return df


def build_series_payload(df: pd.DataFrame, metric: str, max_points: int = 1200) -> dict:
    """
    Build compact timeseries payload for frontend plotting.
    Downsamples uniformly when data is large.
    """
    values = pd.to_numeric(df[metric], errors="coerce").dropna().astype(float).tolist()
    n = len(values)
    if n == 0:
        return {"x": [], "y": [], "n_total": 0, "n_plotted": 0}

    if n <= max_points:
        xs = list(range(n))
        ys = values
    else:
        idx = np.linspace(0, n - 1, max_points, dtype=int)
        xs = idx.tolist()
        ys = [values[i] for i in idx]

    return {
        "x": [int(i) for i in xs],
        "y": [float(v) for v in ys],
        "n_total": int(n),
        "n_plotted": int(len(ys)),
    }


def parse_manual_numeric_values(raw: str) -> list[float]:
    """
    Parse manual numeric input supporting comma, semicolon, whitespace, and newline separators.
    """
    if raw is None:
        return []
    raw = str(raw).strip()
    if raw == "":
        return []
    tokens = [t for t in re.split(r"[\s,;]+", raw) if t != ""]
    out = []
    for tok in tokens:
        try:
            out.append(float(tok))
        except ValueError:
            raise ValueError(f"Invalid numeric value in manual input: '{tok}'")
    return out


def normalize_metric_key(metric: str) -> str:
    key = str(metric or "").strip().lower().replace(" ", "_")
    return METRIC_ALIASES.get(key, key)


def get_metric_info(metric: str, label_override: str | None = None) -> dict:
    key = normalize_metric_key(metric)
    if key not in METRIC_CLASSIFICATION:
        raise ValueError(f"Invalid metric '{metric}'. Must be one of {sorted(VALID_QOS_METRICS)}.")
    orientation = METRIC_CLASSIFICATION[key]
    label = label_override.strip() if label_override else METRIC_LABELS.get(key, key)
    return {
        "key": key,
        "label": label,
        "orientation": orientation,
    }


def is_lower_better(orientation: str) -> bool:
    return orientation == "lower_is_better"


def compute_worsening_effect(baseline_mean: float, treatment_mean: float, orientation: str) -> float:
    if is_lower_better(orientation):
        return float(treatment_mean - baseline_mean)
    return float(baseline_mean - treatment_mean)


def compute_worsening_ci(
    baseline_vals: pd.Series,
    treatment_vals: pd.Series,
    orientation: str,
    confidence: float = 0.95,
) -> tuple:
    if is_lower_better(orientation):
        return compute_mean_diff_ci(treatment_vals, baseline_vals, confidence=confidence)
    return compute_mean_diff_ci(baseline_vals, treatment_vals, confidence=confidence)


def compute_m1_ci(
    control_vals: pd.Series,
    placebo_vals: pd.Series,
    orientation: str,
    confidence: float = 0.95,
) -> tuple:
    if is_lower_better(orientation):
        return compute_mean_diff_ci(placebo_vals, control_vals, confidence=confidence)
    return compute_mean_diff_ci(control_vals, placebo_vals, confidence=confidence)


def nullable_float(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return float(value)


def build_applicability_fields(ni_applicable: bool, margin_status: str | None = None) -> dict:
    if ni_applicable:
        return {
            "ni_applicable": True,
            "margin_status": margin_status or "valid-control-effect",
            "reason": "The active control demonstrates a positive lower confidence bound over placebo on the selected metric.",
            "warning": None,
        }
    return {
        "ni_applicable": False,
        "margin_status": margin_status or INVALID_CONTROL_EFFECT_STATUS,
        "reason": INVALID_CONTROL_EFFECT_REASON,
        "warning": INVALID_CONTROL_EFFECT_WARNING,
    }


def is_not_assessable_verdict(verdict: str) -> bool:
    return str(verdict).lower() == NOT_ASSESSABLE_VERDICT


def parse_metric_list(raw: str | None, fallback: str) -> list[str]:
    if raw is None:
        raw = ""
    raw = str(raw).strip()
    if raw == "":
        return [normalize_metric_key(fallback)]
    items = [normalize_metric_key(m) for m in raw.split(",") if m.strip() != ""]
    return items if items else [normalize_metric_key(fallback)]


def parse_metric_weights(raw: str | None, metrics: list[str]) -> dict[str, float]:
    if not raw:
        # Equal weights
        if not metrics:
            return {}
        w = 1.0 / len(metrics)
        return {m: w for m in metrics}

    weights = {}
    for part in str(raw).split(","):
        if part.strip() == "":
            continue
        if ":" not in part:
            raise ValueError("metric_weights must be formatted as metric:weight,metric:weight")
        name, value = part.split(":", 1)
        name = normalize_metric_key(name)
        value = value.strip()
        if name == "":
            raise ValueError("metric_weights contains an empty metric name")
        try:
            weights[name] = float(value)
        except ValueError:
            raise ValueError(f"Invalid weight '{value}' for metric '{name}'")

    # Normalize weights and fill missing metrics with 0
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("metric_weights must sum to a positive value")
    for m in metrics:
        weights.setdefault(m, 0.0)
    return {m: float(weights[m] / total) for m in metrics}


def compute_file_hash(file_path: str) -> str:
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def build_preprocess_summary(df_before: pd.DataFrame, df_after: pd.DataFrame, metric: str) -> dict:
    before_rows = len(df_before)
    after_rows = len(df_after)
    empty_rows = int(df_before.isna().all(axis=1).sum()) if df_before is not None else 0
    # Count rows dropped after numeric coercion
    metric_rows_before = len(df_before.dropna(how="all")) if df_before is not None else 0
    metric_rows_after = len(df_after) if df_after is not None else 0
    dropped_metric = max(metric_rows_before - metric_rows_after, 0)
    return {
        "metric": metric,
        "rows_before": int(before_rows),
        "rows_after": int(after_rows),
        "dropped_empty_rows": int(empty_rows),
        "dropped_metric_rows": int(dropped_metric),
    }


def _safe_write_json(file_path: str, payload: dict) -> None:
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def save_run_artifacts(run_id: str, metadata: dict, result: dict) -> str:
    run_dir = os.path.join(RUNS_FOLDER, run_id)
    os.makedirs(run_dir, exist_ok=True)
    _safe_write_json(os.path.join(run_dir, "metadata.json"), metadata)
    _safe_write_json(os.path.join(run_dir, "result.json"), result)

    if REPORTLAB_AVAILABLE:
        try:
            pdf_bytes = render_study_report_pdf(result)
            with open(os.path.join(run_dir, "report.pdf"), "wb") as f:
                f.write(pdf_bytes)
        except Exception:
            pass

    return run_dir


def create_run_package_bytes(run_id: str) -> bytes:
    run_dir = os.path.join(RUNS_FOLDER, run_id)
    if not os.path.isdir(run_dir):
        raise FileNotFoundError("run_id not found")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in ["metadata.json", "result.json", "report.pdf"]:
            path = os.path.join(run_dir, name)
            if os.path.isfile(path):
                zf.write(path, arcname=name)
    buffer.seek(0)
    return buffer.getvalue()


# Compute M1 effect size (benefit of baseline vs placebo)
# For lower-better metrics (latency, energy): M1 = mean(placebo) - mean(baseline)
#   → positive M1 means baseline is better (lower values)
# For higher-better metrics (throughput, accuracy): M1 = mean(baseline) - mean(placebo)
#   → positive M1 means baseline is better (higher values)
# This ensures M1 is ALWAYS positive when baseline truly outperforms placebo
def compute_m1(control_df: pd.DataFrame, placebo_df: pd.DataFrame, metric: str, orientation: str) -> float:
    mean_c = control_df[metric].mean()
    mean_p = placebo_df[metric].mean()

    if is_lower_better(orientation):
        # Lower is better → benefit = placebo mean - control mean
        return float(mean_p - mean_c)
    # Higher is better → benefit = control mean - placebo mean
    return float(mean_c - mean_p)


# Compute 95% confidence interval for mean difference using t-distribution
# Returns (lower_bound, upper_bound, se)
def compute_mean_diff_ci(group1: pd.Series, group2: pd.Series, confidence: float = 0.95) -> tuple:
    """
    Computes two-sided 95% CI for (mean(group1) - mean(group2)) using Welch's t-test approach.
    Assumes unequal variances and independent samples.
    
    Args:
        group1, group2: Series of numeric values
        confidence: CI level (default 0.95 for 95%)
    
    Returns:
        (ci_lower, ci_upper, se): Lower bound, upper bound, standard error
    """
    n1, n2 = len(group1), len(group2)
    if n1 < 2 or n2 < 2:
        raise ValueError("Each group must contain at least 2 observations for CI computation.")

    mean_diff = group1.mean() - group2.mean()

    var1, var2 = group1.var(ddof=1), group2.var(ddof=1)
    se = np.sqrt(var1 / n1 + var2 / n2)

    # Degenerate case: both groups have (near) zero variance -> exact difference.
    if np.isclose(se, 0.0):
        return (float(mean_diff), float(mean_diff), float(se))

    # Welch-Satterthwaite degrees of freedom
    numerator = (var1 / n1 + var2 / n2) ** 2
    denominator = ((var1 / n1) ** 2 / (n1 - 1)) + ((var2 / n2) ** 2 / (n2 - 1))

    if np.isclose(denominator, 0.0):
        # Fallback: large-sample normal approximation
        z_crit = stats.norm.ppf(1 - (1 - confidence) / 2)
        ci_lower = mean_diff - z_crit * se
        ci_upper = mean_diff + z_crit * se
        return (float(ci_lower), float(ci_upper), float(se))

    df = numerator / denominator

    # Critical value from t-distribution
    alpha = 1 - confidence
    t_crit = stats.t.ppf(1 - alpha / 2, df)

    ci_lower = mean_diff - t_crit * se
    ci_upper = mean_diff + t_crit * se
    
    return (ci_lower, ci_upper, se)


def _block_resample(values: np.ndarray, block_size: int, rng: np.random.Generator) -> np.ndarray:
    n = len(values)
    if block_size <= 0:
        raise ValueError("block_size must be > 0.")
    if block_size >= n:
        idx = rng.integers(0, n, size=n)
        return values[idx]

    blocks_needed = int(np.ceil(n / block_size))
    max_start = n - block_size
    samples = []
    for _ in range(blocks_needed):
        start = int(rng.integers(0, max_start + 1))
        samples.append(values[start:start + block_size])
    return np.concatenate(samples)[:n]


def bootstrap_mean_diff_ci(
    group1: pd.Series,
    group2: pd.Series,
    confidence: float = 0.95,
    n_resamples: int = 1000,
    random_seed: int = 42,
    mode: str = "iid",
    block_size: int | None = None,
) -> tuple:
    """
    Percentile bootstrap CI for mean(group1) - mean(group2).
    Returns (ci_lower, ci_upper, point_estimate).
    """
    x = pd.to_numeric(pd.Series(group1), errors="coerce").dropna().astype(float).values
    y = pd.to_numeric(pd.Series(group2), errors="coerce").dropna().astype(float).values
    if len(x) < 2 or len(y) < 2:
        raise ValueError("Each group must contain at least 2 observations for bootstrap CI.")

    rng = np.random.default_rng(random_seed)
    n1, n2 = len(x), len(y)

    diffs = np.empty(n_resamples, dtype=float)
    block_size = int(block_size) if block_size is not None else None
    for i in range(n_resamples):
        if mode == "block":
            # Block bootstrap preserves local dependence by resampling contiguous chunks.
            if block_size is None:
                raise ValueError("block_size must be provided for block bootstrap.")
            xs = _block_resample(x, block_size, rng)
            ys = _block_resample(y, block_size, rng)
        else:
            xs = rng.choice(x, size=n1, replace=True)
            ys = rng.choice(y, size=n2, replace=True)
        diffs[i] = xs.mean() - ys.mean()

    alpha = 1.0 - confidence
    lower = np.quantile(diffs, alpha / 2.0)
    upper = np.quantile(diffs, 1.0 - alpha / 2.0)
    point_est = float(np.mean(x) - np.mean(y))
    return float(lower), float(upper), point_est


def _safe_line(text: str, max_len: int = 110) -> list[str]:
    text = str(text or "")
    if len(text) <= max_len:
        return [text]
    out = []
    chunk = []
    current = 0
    for token in text.split(" "):
        add_len = len(token) + (1 if chunk else 0)
        if current + add_len > max_len:
            out.append(" ".join(chunk))
            chunk = [token]
            current = len(token)
        else:
            chunk.append(token)
            current += add_len
    if chunk:
        out.append(" ".join(chunk))
    return out


def render_study_report_pdf(payload: dict) -> bytes:
    metric = payload.get("metric_label", payload.get("metric", "N/A"))
    metric_orientation = payload.get("metric_orientation", "N/A")
    p_frac = payload.get("preservation_fraction", "N/A")
    summary = payload.get("study_summary", {})
    methods = payload.get("methods", {})
    ni_applicable = payload.get("ni_applicable")
    warning = payload.get("warning")
    reason = payload.get("reason")
    m1_ci = payload.get("M1_CI", {})

    # Multi-metric payloads include metric_results; anchor the PDF to the first metric.
    if metric == "N/A" and payload.get("metric_results"):
        first_metric = next(iter(payload["metric_results"].keys()))
        metric_payload = payload["metric_results"][first_metric]
        metric = metric_payload.get("metric_label", first_metric)
        metric_orientation = metric_payload.get("metric_orientation", metric_orientation)
        p_frac = metric_payload.get("preservation_fraction", p_frac)
        summary = metric_payload.get("study_summary", summary)
        methods = metric_payload.get("methods", methods)
        ni_applicable = metric_payload.get("ni_applicable", ni_applicable)
        warning = metric_payload.get("warning", warning)
        reason = metric_payload.get("reason", reason)
        m1_ci = metric_payload.get("M1_CI", m1_ci)
    method_rows = []
    for _, m in methods.items():
        label = m.get("label", "method")
        r = (m.get("ni_result", {}) or {})
        verdict = str(r.get("verdict", "unknown")).upper()
        margin = m.get("d_NI", "N/A")
        ci_upper = r.get("ci_upper", r.get("posterior", {}).get("ci95_upper", "N/A"))
        method_rows.append((label, verdict, margin, ci_upper))

    def _fmt(v):
        if v is None:
            return "N/A"
        if isinstance(v, (int, float, np.floating)):
            return f"{float(v):.6f}"
        return str(v)

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter, pageCompression=0)
    width, height = letter
    left = 40
    right = width - 40
    y = height - 44

    def ensure_space(min_y=70):
        nonlocal y
        if y < min_y:
            pdf.showPage()
            y = height - 44

    def draw_title(text):
        nonlocal y
        ensure_space(90)
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(left, y, text)
        y -= 18

    def draw_subtitle(text):
        nonlocal y
        ensure_space(80)
        pdf.setFont("Helvetica", 10)
        pdf.setFillColorRGB(0.25, 0.30, 0.38)
        pdf.drawString(left, y, text)
        pdf.setFillColorRGB(0, 0, 0)
        y -= 16

    def draw_section(text):
        nonlocal y
        ensure_space(90)
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(left, y, text)
        y -= 14
        pdf.line(left, y, right, y)
        y -= 10

    def draw_paragraph(text, font="Helvetica", size=10, spacing=13):
        nonlocal y
        pdf.setFont(font, size)
        for line in _safe_line(text, max_len=105):
            ensure_space(70)
            pdf.drawString(left, y, line)
            y -= spacing

    def draw_kv(label, value):
        nonlocal y
        ensure_space(70)
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(left, y, f"{label}:")
        pdf.setFont("Helvetica", 10)
        pdf.drawString(left + 130, y, str(value))
        y -= 13

    draw_title("MARGIN-SAS Evaluation Report")
    draw_subtitle(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    draw_subtitle("Prepared for stakeholder review")

    draw_section("Executive Summary")
    draw_kv("Metric", metric)
    draw_kv("Preservation fraction", _fmt(p_frac))
    draw_kv("Primary verdict", str(summary.get("verdict", "N/A")).upper())
    draw_kv("NI applicable", str(summary.get("ni_applicable", ni_applicable)).upper())
    draw_kv("Observed effect", _fmt(summary.get("observed_effect", "N/A")))
    draw_kv("NI margin", _fmt(summary.get("ni_margin", "N/A")))
    draw_kv("95% CI", f"[{_fmt(summary.get('ci_lower', 'N/A'))}, {_fmt(summary.get('ci_upper', 'N/A'))}]")
    y -= 4
    if summary.get("ni_applicable", ni_applicable) is False:
        draw_paragraph(INVALID_CONTROL_EFFECT_WARNING, font="Helvetica-Bold")
        draw_paragraph(
            "This assessment uses the selected metric orientation, baseline mean, placebo mean, "
            "M1, and M1 confidence interval shown below."
        )
        draw_paragraph(f"Reason: {summary.get('reason') or reason or INVALID_CONTROL_EFFECT_REASON}")
    draw_paragraph(f"Interpretation: {summary.get('reasoning', 'No reasoning provided.').replace('≤', '<=' )}")

    draw_section("Inputs and Configuration")
    orientation_display = str(metric_orientation).replace("_", " ").replace("-", " ")
    draw_kv("Metric orientation", orientation_display)
    draw_kv("Bayesian prior mean", _fmt(methods.get("bayesian", {}).get("ni_result", {}).get("prior", {}).get("mean", "N/A")))
    draw_kv("Bayesian prior SD", _fmt(methods.get("bayesian", {}).get("ni_result", {}).get("prior", {}).get("sd", "N/A")))
    draw_kv("Bayesian threshold", _fmt(methods.get("bayesian", {}).get("ni_result", {}).get("threshold", "N/A")))
    draw_kv("Bootstrap resamples", payload.get("bootstrap_resamples", "N/A"))

    draw_section("Core Outcome Statistics")
    draw_kv("Placebo mean", _fmt(summary.get("placebo_mean", payload.get("placebo_mean", "N/A"))))
    draw_kv("Baseline mean", _fmt(summary.get("baseline_mean", "N/A")))
    draw_kv("Treatment mean", _fmt(summary.get("treatment_mean", "N/A")))
    draw_kv("M1 control-placebo effect", _fmt(summary.get("M1", payload.get("M1", "N/A"))))
    draw_kv("M1 95% CI", f"[{_fmt((summary.get('M1_CI') or m1_ci).get('lower', 'N/A'))}, {_fmt((summary.get('M1_CI') or m1_ci).get('upper', 'N/A'))}]")
    draw_kv("Observed worsening effect", _fmt(summary.get("observed_effect", "N/A")))
    draw_kv("NI margin d", _fmt(summary.get("ni_margin", "N/A")))
    draw_kv("95% CI lower", _fmt(summary.get("ci_lower", "N/A")))
    draw_kv("95% CI upper", _fmt(summary.get("ci_upper", "N/A")))

    draw_section("Method Agreement")
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(left, y, "Method")
    pdf.drawString(left + 250, y, "Verdict")
    pdf.drawString(left + 360, y, "d")
    y -= 12
    pdf.line(left, y, right, y)
    y -= 10
    pass_count = 0
    not_assessable_count = 0
    for label, verdict, margin, _ in method_rows:
        ensure_space(70)
        pdf.setFont("Helvetica", 10)
        pdf.drawString(left, y, str(label)[:44])
        pdf.drawString(left + 250, y, verdict)
        pdf.drawString(left + 360, y, _fmt(margin))
        if verdict in {"NON-INFERIOR", "EQUIVALENT"}:
            pass_count += 1
        if verdict == NOT_ASSESSABLE_VERDICT.upper():
            not_assessable_count += 1
        y -= 13
    y -= 4
    draw_paragraph(f"Consensus: {pass_count}/{max(len(method_rows), 1)} methods support acceptance; {not_assessable_count} methods are not assessable.")

    draw_section("Assumptions")
    draw_paragraph("Lower-is-better metrics use positive worsening effects when treatment is worse than baseline.")
    draw_paragraph("When NI is assessable, d_NI is reported as a positive allowable worsening threshold.")

    draw_section("Appendix")
    draw_paragraph("This report summarizes statistical outputs generated by the NI evaluation service.")
    draw_paragraph("Detailed machine-readable JSON can be downloaded from the dashboard if needed.")

    pdf.save()
    buffer.seek(0)
    return buffer.getvalue()


@app.route("/api/study-report", methods=["POST"])
def study_report_pdf():
    if not REPORTLAB_AVAILABLE:
        return jsonify({"error": "PDF export dependency is not installed. Install reportlab."}), 500

    payload = request.get_json(silent=True) or {}
    if not payload:
        return jsonify({"error": "Request body must contain NI evaluation JSON result."}), 400

    pdf_bytes = render_study_report_pdf(payload)
    resp = make_response(pdf_bytes)
    resp.headers["Content-Type"] = "application/pdf"
    resp.headers["Content-Disposition"] = "attachment; filename=margin_sas_study_report.pdf"
    return resp


@app.route("/api/run-package/<run_id>", methods=["GET"])
def download_run_package(run_id: str):
    try:
        package = create_run_package_bytes(run_id)
    except FileNotFoundError:
        return jsonify({"error": "run_id not found"}), 404
    except Exception as e:
        return jsonify({"error": f"Failed to build run package: {e}"}), 500

    resp = make_response(package)
    resp.headers["Content-Type"] = "application/zip"
    resp.headers["Content-Disposition"] = f"attachment; filename=run_{run_id}.zip"
    return resp


# Compute NI margin from 95% CI of M1 (conservative lower bound)
# Fixed-margin (95-95) method: use lower bound of M1 CI
def compute_ni_margin_ci_based(
    control_df: pd.DataFrame,
    placebo_df: pd.DataFrame,
    metric: str,
    orientation: str,
    preservation_fraction: float
) -> dict:
    """
    Computes d_NI using 95% CI-based fixed-margin method.
    
    Step 1: Compute 95% CI for M1 (control benefit over placebo)
    Step 2: Use LOWER bound as conservative M1 estimate
    Step 3: d_NI = M1_lower * (1 - p)
    
    Returns dict with m1_point, m1_lower, m1_upper, d_ni, method
    """
    control_vals = control_df[metric].astype(float).values
    placebo_vals = placebo_df[metric].astype(float).values
    
    ci_lower, ci_upper, se = compute_m1_ci(
        pd.Series(control_vals),
        pd.Series(placebo_vals),
        orientation,
        confidence=0.95,
    )
    
    m1_point = (ci_lower + ci_upper) / 2.0
    
    ni_applicable = bool(ci_lower > 0.0)
    applicability = build_applicability_fields(ni_applicable)

    # Conservative fixed-margin NI is only defensible when the active control
    # has a positive lower confidence bound over placebo.
    m1_conservative = float(ci_lower) if ni_applicable else None
    d_ni = (m1_conservative * (1.0 - preservation_fraction)) if ni_applicable else None
    
    return {
        "m1_point_estimate": float(m1_point),
        "m1_ci_lower": float(ci_lower),
        "m1_ci_upper": float(ci_upper),
        "m1_se": float(se),
        "m1_conservative_lower": nullable_float(m1_conservative),
        "d_NI": nullable_float(d_ni),
        "preservation_fraction": preservation_fraction,
        "method": "fixed-margin-95-95-ci-based",
        **applicability,
    }


def parse_float_list(raw: str) -> list[float]:
    if raw is None:
        return []
    raw = raw.strip()
    if raw == "":
        return []
    return [float(x.strip()) for x in raw.split(",") if x.strip() != ""]


def compute_ni_margin_synthesis(
    current_m1_effect: float,
    current_m1_se: float,
    preservation_fraction: float,
    historical_effects: list[float] | None = None,
    historical_ses: list[float] | None = None,
    confidence: float = 0.95,
) -> dict:
    """
    Simplified synthesis / putative-placebo NI margin.

    Pools multiple M1 estimates using inverse-variance weighting and derives
    a conservative lower confidence bound for pooled M1.
    Then: d_NI = pooled_M1_lower * (1 - p)
    """
    historical_effects = historical_effects or []
    historical_ses = historical_ses or []

    if len(historical_effects) != len(historical_ses):
        raise ValueError("historical_effects and historical_ses must have the same length.")

    effects = [float(current_m1_effect)] + [float(x) for x in historical_effects]
    ses = [float(current_m1_se)] + [float(x) for x in historical_ses]

    eps = 1e-12
    variances = [max(se * se, eps) for se in ses]
    weights = [1.0 / v for v in variances]

    pooled_effect = float(np.sum(np.array(weights) * np.array(effects)) / np.sum(weights))
    pooled_se = float(np.sqrt(1.0 / np.sum(weights)))

    z_crit = float(stats.norm.ppf(1 - (1 - confidence) / 2))
    pooled_lower = pooled_effect - z_crit * pooled_se
    pooled_upper = pooled_effect + z_crit * pooled_se

    d_ni = pooled_lower * (1.0 - preservation_fraction)

    return {
        "method": "synthesis-putative-placebo",
        "study_count": len(effects),
        "pooled_m1": pooled_effect,
        "pooled_m1_se": pooled_se,
        "pooled_m1_ci_lower": float(pooled_lower),
        "pooled_m1_ci_upper": float(pooled_upper),
        "d_NI": float(d_ni),
        "preservation_fraction": float(preservation_fraction),
    }


# Legacy: Compute NI margin from point estimate (for backwards compatibility)
def compute_ni_margin(m1: float, preservation_fraction: float) -> float:
    return float(m1 * (1.0 - preservation_fraction))


# CI-based Non-Inferiority Test (Fixed-Margin 95-95 Method)
# Tests if upper bound of treatment CI ≤ d_NI
def run_non_inferiority_test_ci_based(
    baseline_df: pd.DataFrame,
    treatment_df: pd.DataFrame,
    metric: str,
    d_ni: float,
    orientation: str,
    confidence: float = 0.95
) -> dict:
    """
    Proper CI-based NI decision:
    
    1. Compute 95% CI for (treatment - baseline) difference
    2. If upper_bound ≤ d_NI, declare NON-INFERIOR
    3. Else INFERIOR
    
    Direction mapping:
    - For lower-better: diff = treatment - baseline (higher is worse)
    - For higher-better: diff = baseline - treatment (higher is worse)
    """
    baseline_vals = baseline_df[metric].astype(float).values
    treatment_vals = treatment_df[metric].astype(float).values
    
    baseline_mean = float(baseline_df[metric].mean())
    treatment_mean = float(treatment_df[metric].mean())
    
    # Compute CI for "worsening" in both orientations
    ci_lower, ci_upper, se = compute_worsening_ci(
        pd.Series(baseline_vals),
        pd.Series(treatment_vals),
        orientation,
        confidence=confidence,
    )
    point_diff = compute_worsening_effect(baseline_mean, treatment_mean, orientation)
    
    # NI decision: is upper bound ≤ d_NI?
    is_non_inferior = (ci_upper <= d_ni)
    verdict = "non-inferior" if is_non_inferior else "inferior"
    
    return {
        "method": "fixed-margin-95-95-ci-based",
        "metric": metric,
        "direction": orientation,
        "baseline_mean": baseline_mean,
        "treatment_mean": treatment_mean,
        "point_estimate_diff": point_diff,
        "ci_lower": float(ci_lower),
        "ci_upper": float(ci_upper),
        "ci_level": f"{int(confidence*100)}%",
        "d_NI": d_ni,
        "decision_rule": f"Is CI upper bound ({ci_upper:.6f}) ≤ d_NI ({d_ni:.6f})?",
        "verdict": verdict,
        "note": "Proper CI-based fixed-margin NI test (95-95 method). Treatment is non-inferior if upper CI bound <= d_NI.",
        **build_applicability_fields(True),
    }


def run_not_assessable_ci_based(
    baseline_df: pd.DataFrame,
    treatment_df: pd.DataFrame,
    metric: str,
    orientation: str,
    confidence: float = 0.95,
    method: str = "fixed-margin-95-95-ci-based",
    note: str | None = None,
) -> dict:
    baseline_vals = baseline_df[metric].astype(float).values
    treatment_vals = treatment_df[metric].astype(float).values
    baseline_mean = float(baseline_df[metric].mean())
    treatment_mean = float(treatment_df[metric].mean())
    ci_lower, ci_upper, _ = compute_worsening_ci(
        pd.Series(baseline_vals),
        pd.Series(treatment_vals),
        orientation,
        confidence=confidence,
    )
    point_diff = compute_worsening_effect(baseline_mean, treatment_mean, orientation)

    return {
        "method": method,
        "metric": metric,
        "direction": orientation,
        "baseline_mean": baseline_mean,
        "treatment_mean": treatment_mean,
        "point_estimate_diff": float(point_diff),
        "ci_lower": float(ci_lower),
        "ci_upper": float(ci_upper),
        "ci_level": f"{int(confidence*100)}%",
        "d_NI": None,
        "decision_rule": "Fixed-margin NI decision not run because M1_CI.lower is not greater than 0.",
        "verdict": NOT_ASSESSABLE_VERDICT,
        "note": note or "Fixed-margin NI is not assessable when the active control does not outperform placebo.",
        **build_applicability_fields(False),
    }


def run_not_assessable_bayesian(
    baseline_df: pd.DataFrame,
    treatment_df: pd.DataFrame,
    metric: str,
    orientation: str,
    prior_mean: float,
    prior_sd: float,
    threshold: float,
) -> dict:
    baseline_vals = baseline_df[metric].astype(float)
    treatment_vals = treatment_df[metric].astype(float)
    baseline_mean = float(baseline_vals.mean())
    treatment_mean = float(treatment_vals.mean())
    point_diff = compute_worsening_effect(baseline_mean, treatment_mean, orientation)
    _, _, se = compute_worsening_ci(baseline_vals, treatment_vals, orientation, confidence=0.95)

    if prior_sd <= 0:
        raise ValueError("prior_sd must be > 0 for Bayesian NI.")
    if not (0.0 < threshold < 1.0):
        raise ValueError("posterior_threshold must be between 0 and 1 (exclusive).")

    if np.isclose(se, 0.0):
        posterior_mean = float(point_diff)
        posterior_sd = 0.0
        ci95_lower = float(point_diff)
        ci95_upper = float(point_diff)
    else:
        prior_var = float(prior_sd) ** 2
        like_var = float(se) ** 2
        prior_precision = 1.0 / prior_var
        like_precision = 1.0 / like_var
        post_var = 1.0 / (prior_precision + like_precision)
        posterior_sd = float(np.sqrt(post_var))
        posterior_mean = float(post_var * (prior_precision * float(prior_mean) + like_precision * float(point_diff)))
        z_crit = stats.norm.ppf(0.975)
        ci95_lower = float(posterior_mean - z_crit * posterior_sd)
        ci95_upper = float(posterior_mean + z_crit * posterior_sd)

    return {
        "method": "bayesian-ni-normal",
        "metric": metric,
        "direction": orientation,
        "baseline_mean": baseline_mean,
        "treatment_mean": treatment_mean,
        "point_estimate_diff": float(point_diff),
        "d_NI": None,
        "prior": {"mean": float(prior_mean), "sd": float(prior_sd)},
        "posterior": {
            "mean": posterior_mean,
            "sd": posterior_sd,
            "ci95_lower": ci95_lower,
            "ci95_upper": ci95_upper,
        },
        "probability_non_inferior": None,
        "threshold": float(threshold),
        "decision_rule": "Bayesian NI decision not run because the primary fixed-margin NI margin is invalid.",
        "verdict": NOT_ASSESSABLE_VERDICT,
        "note": "Posterior distribution is descriptive only; no formal Bayesian NI verdict is reported against an invalid margin.",
        **build_applicability_fields(False),
    }


def run_non_inferiority_test_bayesian(
    baseline_df: pd.DataFrame,
    treatment_df: pd.DataFrame,
    metric: str,
    d_ni: float,
    orientation: str,
    prior_mean: float = 0.0,
    prior_sd: float = 10.0,
    threshold: float = 0.95,
) -> dict:
    """
    Bayesian NI using Normal-Normal conjugate approximation on the "worsening" effect.

    Effect definition (higher is worse):
    - lower-better metrics: effect = mean(treatment) - mean(baseline)
    - higher-better metrics: effect = mean(baseline) - mean(treatment)

    Decision rule:
    - Compute posterior probability P(effect <= d_NI)
    - Declare non-inferior if probability >= threshold
    """
    baseline_vals = baseline_df[metric].astype(float)
    treatment_vals = treatment_df[metric].astype(float)

    baseline_mean = float(baseline_vals.mean())
    treatment_mean = float(treatment_vals.mean())

    point_diff = compute_worsening_effect(baseline_mean, treatment_mean, orientation)
    _, _, se = compute_worsening_ci(baseline_vals, treatment_vals, orientation, confidence=0.95)

    if prior_sd <= 0:
        raise ValueError("prior_sd must be > 0 for Bayesian NI.")
    if not (0.0 < threshold < 1.0):
        raise ValueError("posterior_threshold must be between 0 and 1 (exclusive).")

    # Degenerate likelihood: observed effect known exactly
    if np.isclose(se, 0.0):
        posterior_mean = float(point_diff)
        posterior_sd = 0.0
        probability_non_inferior = 1.0 if point_diff <= d_ni else 0.0
        ci95_lower = float(point_diff)
        ci95_upper = float(point_diff)
    else:
        prior_var = float(prior_sd) ** 2
        like_var = float(se) ** 2

        prior_precision = 1.0 / prior_var
        like_precision = 1.0 / like_var
        post_var = 1.0 / (prior_precision + like_precision)
        post_sd = np.sqrt(post_var)
        post_mean = post_var * (prior_precision * float(prior_mean) + like_precision * float(point_diff))

        probability_non_inferior = float(stats.norm.cdf((d_ni - post_mean) / post_sd))
        z_crit = stats.norm.ppf(0.975)
        ci95_lower = float(post_mean - z_crit * post_sd)
        ci95_upper = float(post_mean + z_crit * post_sd)

        posterior_mean = float(post_mean)
        posterior_sd = float(post_sd)

    verdict = "non-inferior" if probability_non_inferior >= threshold else "inferior"

    return {
        "method": "bayesian-ni-normal",
        "metric": metric,
        "direction": orientation,
        "baseline_mean": baseline_mean,
        "treatment_mean": treatment_mean,
        "point_estimate_diff": float(point_diff),
        "d_NI": float(d_ni),
        "prior": {
            "mean": float(prior_mean),
            "sd": float(prior_sd)
        },
        "posterior": {
            "mean": posterior_mean,
            "sd": posterior_sd,
            "ci95_lower": ci95_lower,
            "ci95_upper": ci95_upper
        },
        "probability_non_inferior": float(probability_non_inferior),
        "threshold": float(threshold),
        "decision_rule": f"Is P(effect <= d_NI) ({probability_non_inferior:.6f}) >= threshold ({threshold:.2f})?",
        "verdict": verdict,
        "note": "Bayesian NI (Normal prior + Normal likelihood approximation).",
        **build_applicability_fields(True),
    }


def run_equivalence_test_ci_based(
    baseline_df: pd.DataFrame,
    treatment_df: pd.DataFrame,
    metric: str,
    orientation: str,
    equivalence_margin: float,
    confidence: float = 0.95,
) -> dict:
    """
    Two-sided equivalence test via confidence interval inclusion.
    Equivalent iff CI for worsening effect is fully within [-margin, +margin].
    """
    if equivalence_margin < 0:
        raise ValueError("equivalence_margin must be >= 0.")

    baseline_vals = baseline_df[metric].astype(float).values
    treatment_vals = treatment_df[metric].astype(float).values

    baseline_mean = float(baseline_df[metric].mean())
    treatment_mean = float(treatment_df[metric].mean())

    ci_lower, ci_upper, se = compute_worsening_ci(
        pd.Series(baseline_vals),
        pd.Series(treatment_vals),
        orientation,
        confidence=confidence,
    )
    point_diff = compute_worsening_effect(baseline_mean, treatment_mean, orientation)

    is_equivalent = (ci_lower >= -equivalence_margin) and (ci_upper <= equivalence_margin)
    verdict = "equivalent" if is_equivalent else "not-equivalent"

    return {
        "method": "equivalence-ci-two-sided",
        "metric": metric,
        "direction": orientation,
        "baseline_mean": baseline_mean,
        "treatment_mean": treatment_mean,
        "point_estimate_diff": float(point_diff),
        "ci_lower": float(ci_lower),
        "ci_upper": float(ci_upper),
        "ci_level": f"{int(confidence*100)}%",
        "equivalence_margin": float(equivalence_margin),
        "decision_rule": f"Is CI [{ci_lower:.6f}, {ci_upper:.6f}] within [-{equivalence_margin:.6f}, +{equivalence_margin:.6f}]?",
        "verdict": verdict,
        "note": "Two-sided equivalence test using CI inclusion. This is a different claim from fixed-margin non-inferiority.",
        "claim_type": "equivalence",
        "ni_applicable": None,
        "margin_status": "equivalence-claim",
        "reason": "Equivalence is computed as a two-sided CI inclusion claim and is not a fixed-margin NI conclusion.",
        "warning": None,
    }


def _is_pass_verdict(verdict: str) -> bool:
    return str(verdict).lower() in {"non-inferior", "equivalent"}


def _is_primary_ni_pass_verdict(verdict: str) -> bool:
    return str(verdict).lower() == "non-inferior"


def evaluate_metric_core(
    df_placebo_raw: pd.DataFrame,
    df_baseline_raw: pd.DataFrame,
    df_treatment_raw: pd.DataFrame,
    metric: str,
    config: dict,
    allow_harmonize: bool = True,
) -> tuple[dict, dict]:
    metric_info = get_metric_info(metric)
    metric_key = metric_info["key"]
    metric_label = metric_info["label"]
    metric_orientation = metric_info["orientation"]

    df_placebo = df_placebo_raw.copy()
    df_baseline = df_baseline_raw.copy()
    df_treatment = df_treatment_raw.copy()

    # Harmonize only when running a single metric to avoid clobbering other columns.
    if allow_harmonize:
        df_placebo = harmonize_metric_column(df_placebo, metric_key)
        df_baseline = harmonize_metric_column(df_baseline, metric_key)
        df_treatment = harmonize_metric_column(df_treatment, metric_key)

    required = {metric_key}
    val_placebo = validate_qos_dataset(df_placebo, required_metrics=required)
    val_baseline = validate_qos_dataset(df_baseline, required_metrics=required)
    val_treatment = validate_qos_dataset(df_treatment, required_metrics=required)

    if not (val_placebo["ok"] and val_baseline["ok"] and val_treatment["ok"]):
        raise ValueError(
            "Dataset validation failed: "
            + f"placebo={val_placebo['errors']}, "
            + f"baseline={val_baseline['errors']}, "
            + f"treatment={val_treatment['errors']}"
        )

    before_placebo = df_placebo.copy()
    before_baseline = df_baseline.copy()
    before_treatment = df_treatment.copy()

    df_placebo = preprocess_data(df_placebo, metric_key)
    df_baseline = preprocess_data(df_baseline, metric_key)
    df_treatment = preprocess_data(df_treatment, metric_key)

    if len(df_placebo) < MIN_N or len(df_baseline) < MIN_N or len(df_treatment) < MIN_N:
        raise ValueError(
            f"Each dataset must have at least {MIN_N} rows after preprocessing. "
            + f"rows: placebo={len(df_placebo)}, baseline={len(df_baseline)}, treatment={len(df_treatment)}"
        )

    preprocess_summary = {
        "placebo": build_preprocess_summary(before_placebo, df_placebo, metric_key),
        "baseline": build_preprocess_summary(before_baseline, df_baseline, metric_key),
        "treatment": build_preprocess_summary(before_treatment, df_treatment, metric_key),
    }

    preservation_fraction = float(config["preservation_fraction"])
    bootstrap_resamples = int(config["bootstrap_resamples"])
    bootstrap_seed = int(config["bootstrap_seed"])
    bootstrap_mode = config.get("bootstrap_mode", "iid")
    bootstrap_block_size = config.get("bootstrap_block_size")

    orientation = metric_orientation

    m1_result = compute_ni_margin_ci_based(
        df_baseline, df_placebo, metric_key, orientation, preservation_fraction
    )
    m1 = m1_result["m1_point_estimate"]
    d_ni = m1_result["d_NI"]
    ni_applicable = bool(m1_result.get("ni_applicable", True))
    applicability_fields = build_applicability_fields(
        ni_applicable,
        m1_result.get("margin_status"),
    )
    placebo_mean = float(df_placebo[metric_key].mean())
    baseline_mean = float(df_baseline[metric_key].mean())

    m1_point = compute_m1(df_baseline, df_placebo, metric_key, orientation)
    d_ni_mean = compute_ni_margin(m1_point, preservation_fraction)

    if ni_applicable:
        # Fixed-margin NI is only valid when the control effect is positive (M1 CI lower > 0).
        ni_result = run_non_inferiority_test_ci_based(
            baseline_df=df_baseline,
            treatment_df=df_treatment,
            metric=metric_key,
            d_ni=float(d_ni),
            orientation=orientation,
            confidence=0.95,
        )
    else:
        ni_result = run_not_assessable_ci_based(
            baseline_df=df_baseline,
            treatment_df=df_treatment,
            metric=metric_key,
            orientation=orientation,
            confidence=0.95,
        )

    if is_lower_better(orientation):
        b_ci_lower, b_ci_upper, _ = bootstrap_mean_diff_ci(
            df_treatment[metric_key],
            df_baseline[metric_key],
            confidence=0.95,
            n_resamples=bootstrap_resamples,
            random_seed=bootstrap_seed,
            mode=bootstrap_mode,
            block_size=bootstrap_block_size,
        )
    else:
        b_ci_lower, b_ci_upper, _ = bootstrap_mean_diff_ci(
            df_baseline[metric_key],
            df_treatment[metric_key],
            confidence=0.95,
            n_resamples=bootstrap_resamples,
            random_seed=bootstrap_seed,
            mode=bootstrap_mode,
            block_size=bootstrap_block_size,
        )

    ni_result["bootstrap_ci"] = {
        "lower": float(b_ci_lower),
        "upper": float(b_ci_upper),
        "level": "95%",
        "n_resamples": int(bootstrap_resamples),
        "seed": int(bootstrap_seed),
        "mode": bootstrap_mode,
        "block_size": bootstrap_block_size,
    }

    ni_result_mean = run_non_inferiority_test(
        baseline_df=df_baseline,
        treatment_df=df_treatment,
        metric=metric_key,
        d_ni=d_ni_mean,
        method="fixed-margin-mean-based",
    )
    ni_result_mean["claim_type"] = "exploratory_mean_based"
    ni_result_mean["formal_ni_conclusion"] = bool(ni_applicable)
    if ni_applicable:
        ni_result_mean.update(build_applicability_fields(True))
    else:
        exploratory_verdict = ni_result_mean["verdict"]
        exploratory_margin = ni_result_mean["d_NI"]
        ni_result_mean.update({
            "verdict": NOT_ASSESSABLE_VERDICT,
            "exploratory_verdict": exploratory_verdict,
            "exploratory_d_NI": nullable_float(exploratory_margin),
            "d_NI": None,
            "formal_ni_conclusion": False,
            "note": "Mean-based output is exploratory/legacy only and is not a primary NI conclusion when the fixed-margin setup is invalid.",
            **build_applicability_fields(False),
        })

    if ni_applicable:
        ni_result_bayes = run_non_inferiority_test_bayesian(
            baseline_df=df_baseline,
            treatment_df=df_treatment,
            metric=metric_key,
            d_ni=float(d_ni),
            orientation=orientation,
            prior_mean=float(config["bayes_prior_mean"]),
            prior_sd=float(config["bayes_prior_sd"]),
            threshold=float(config["bayes_threshold"]),
        )
    else:
        ni_result_bayes = run_not_assessable_bayesian(
            baseline_df=df_baseline,
            treatment_df=df_treatment,
            metric=metric_key,
            orientation=orientation,
            prior_mean=float(config["bayes_prior_mean"]),
            prior_sd=float(config["bayes_prior_sd"]),
            threshold=float(config["bayes_threshold"]),
        )

    synthesis_result = compute_ni_margin_synthesis(
        current_m1_effect=m1_result["m1_point_estimate"],
        current_m1_se=m1_result["m1_se"],
        preservation_fraction=preservation_fraction,
        historical_effects=config.get("historical_effects", []),
        historical_ses=config.get("historical_ses", []),
        confidence=0.95,
    )
    historical_basis_valid = bool(config.get("historical_effects")) and bool(config.get("historical_ses")) and bool(config.get("synthesis_justification"))
    synthesis_applicable = bool(synthesis_result["pooled_m1_ci_lower"] > 0 and (ni_applicable or historical_basis_valid))
    if synthesis_applicable:
        ni_result_synthesis = run_non_inferiority_test_ci_based(
            baseline_df=df_baseline,
            treatment_df=df_treatment,
            metric=metric_key,
            d_ni=float(synthesis_result["d_NI"]),
            orientation=orientation,
            confidence=0.95,
        )
        ni_result_synthesis["margin_status"] = "valid-historical-control-effect" if not ni_applicable else ni_result_synthesis["margin_status"]
        if not ni_applicable:
            ni_result_synthesis["reason"] = "Synthesis NI used an explicitly justified historical-control basis because the current active control effect was not assessable."
            ni_result_synthesis["warning"] = "Primary fixed-margin NI is not assessable for the current control-placebo data; synthesis relies on the supplied historical justification."
    else:
        ni_result_synthesis = run_not_assessable_ci_based(
            baseline_df=df_baseline,
            treatment_df=df_treatment,
            metric=metric_key,
            orientation=orientation,
            confidence=0.95,
            method="synthesis-putative-placebo",
            note="Synthesis NI is not assessable without a valid current control effect or an explicitly justified historical-control basis.",
        )
        synthesis_result = {
            **synthesis_result,
            "d_NI": None,
            "ni_applicable": False,
            "margin_status": INVALID_CONTROL_EFFECT_STATUS,
            "reason": INVALID_CONTROL_EFFECT_REASON,
            "warning": INVALID_CONTROL_EFFECT_WARNING,
        }

    equivalence_margin = config.get("equivalence_margin")
    if equivalence_margin is not None:
        equivalence_margin_used = float(equivalence_margin)
        equivalence_result = run_equivalence_test_ci_based(
            baseline_df=df_baseline,
            treatment_df=df_treatment,
            metric=metric_key,
            orientation=orientation,
            equivalence_margin=equivalence_margin_used,
            confidence=0.95,
        )
    elif ni_applicable:
        equivalence_margin_used = float(abs(d_ni))
        equivalence_result = run_equivalence_test_ci_based(
            baseline_df=df_baseline,
            treatment_df=df_treatment,
            metric=metric_key,
            orientation=orientation,
            equivalence_margin=equivalence_margin_used,
            confidence=0.95,
        )
    else:
        equivalence_margin_used = None
        equivalence_result = run_not_assessable_ci_based(
            baseline_df=df_baseline,
            treatment_df=df_treatment,
            metric=metric_key,
            orientation=orientation,
            confidence=0.95,
            method="equivalence-ci-two-sided",
            note="Equivalence is a different claim from NI, but no explicit equivalence margin was provided.",
        )
        equivalence_result.update({
            "claim_type": "equivalence",
            "margin_status": "missing-equivalence-margin",
            "reason": "Equivalence requires an explicit equivalence margin when the NI margin is invalid.",
            "warning": "Equivalence was not computed because fixed-margin NI is not assessable and no explicit equivalence margin was provided.",
        })

    if ni_applicable:
        verdict_reasoning = (
            f"CI-based NI decision compares CI upper ({ni_result['ci_upper']:.6f}) "
            f"to d_NI ({ni_result['d_NI']:.6f}). "
            + ("Since CI upper <= d_NI, treatment is non-inferior."
               if ni_result["verdict"] == "non-inferior"
               else "Since CI upper > d_NI, treatment is inferior under NI.")
        )
    else:
        verdict_reasoning = (
            f"{INVALID_CONTROL_EFFECT_WARNING} "
            f"M1 95% CI is [{m1_result['m1_ci_lower']:.6f}, {m1_result['m1_ci_upper']:.6f}], "
            f"so M1_CI.lower is not greater than 0. No fixed-margin d_NI is defined and the "
            f"standard CI-upper-vs-d_NI rule was not run."
        )

    result = {
        "metric": metric_key,
        "metric_label": metric_label,
        "metric_orientation": metric_orientation,
        "preservation_fraction": float(preservation_fraction),
        "bootstrap_resamples": int(bootstrap_resamples),
        "bootstrap_seed": int(bootstrap_seed),
        "placebo_mean": placebo_mean,
        "baseline_mean": baseline_mean,
        "M1": float(m1_result["m1_point_estimate"]),
        "M1_CI": {
            "lower": float(m1_result["m1_ci_lower"]),
            "upper": float(m1_result["m1_ci_upper"]),
            "level": "95%",
        },
        "d_NI": nullable_float(d_ni),
        **applicability_fields,
        "ni_result": {
            "method": ni_result["method"],
            "metric": ni_result["metric"],
            "direction": ni_result["direction"],
            "baseline_mean": float(ni_result["baseline_mean"]),
            "treatment_mean": float(ni_result["treatment_mean"]),
            "point_estimate_diff": float(ni_result["point_estimate_diff"]),
            "ci_lower": float(ni_result["ci_lower"]),
            "ci_upper": float(ni_result["ci_upper"]),
            "ci_level": ni_result["ci_level"],
            "bootstrap_ci": ni_result.get("bootstrap_ci"),
            "d_NI": nullable_float(ni_result["d_NI"]),
            "decision_rule": ni_result["decision_rule"],
            "verdict": ni_result["verdict"],
            "note": ni_result["note"],
            "ni_applicable": ni_result.get("ni_applicable"),
            "margin_status": ni_result.get("margin_status"),
            "reason": ni_result.get("reason"),
            "warning": ni_result.get("warning"),
        },
        "methods": {
            "ci_based": {
                "label": "Fixed-margin 95-95 (CI-based)",
                "preferred": True,
                "M1": float(m1_result["m1_point_estimate"]),
                "M1_CI": {
                    "lower": float(m1_result["m1_ci_lower"]),
                    "upper": float(m1_result["m1_ci_upper"]),
                    "level": "95%",
                },
                "d_NI": nullable_float(d_ni),
                **applicability_fields,
                "ni_result": ni_result,
            },
            "mean_based": {
                "label": "Mean-based (legacy)",
                "preferred": False,
                "M1": float(m1_point),
                "d_NI": nullable_float(d_ni_mean if ni_applicable else None),
                "exploratory_d_NI": nullable_float(d_ni_mean),
                "ni_applicable": ni_result_mean.get("ni_applicable"),
                "margin_status": ni_result_mean.get("margin_status"),
                "reason": ni_result_mean.get("reason"),
                "warning": ni_result_mean.get("warning"),
                "ni_result": ni_result_mean,
            },
            "bayesian": {
                "label": "Bayesian NI (posterior probability)",
                "preferred": False,
                "M1": float(m1_result["m1_point_estimate"]),
                "M1_CI": {
                    "lower": float(m1_result["m1_ci_lower"]),
                    "upper": float(m1_result["m1_ci_upper"]),
                    "level": "95%",
                },
                "d_NI": nullable_float(d_ni),
                "ni_applicable": ni_result_bayes.get("ni_applicable"),
                "margin_status": ni_result_bayes.get("margin_status"),
                "reason": ni_result_bayes.get("reason"),
                "warning": ni_result_bayes.get("warning"),
                "ni_result": ni_result_bayes,
            },
            "synthesis": {
                "label": "Synthesis / Putative-Placebo",
                "preferred": False,
                "M1": float(synthesis_result["pooled_m1"]),
                "M1_CI": {
                    "lower": float(synthesis_result["pooled_m1_ci_lower"]),
                    "upper": float(synthesis_result["pooled_m1_ci_upper"]),
                    "level": "95%",
                },
                "d_NI": nullable_float(synthesis_result["d_NI"]),
                "ni_applicable": ni_result_synthesis.get("ni_applicable"),
                "margin_status": ni_result_synthesis.get("margin_status"),
                "reason": ni_result_synthesis.get("reason"),
                "warning": ni_result_synthesis.get("warning"),
                "ni_result": ni_result_synthesis,
                "details": synthesis_result,
            },
            "equivalence": {
                "label": "Equivalence (two-sided CI)",
                "preferred": False,
                "M1": float(m1_result["m1_point_estimate"]),
                "M1_CI": {
                    "lower": float(m1_result["m1_ci_lower"]),
                    "upper": float(m1_result["m1_ci_upper"]),
                    "level": "95%",
                },
                "d_NI": nullable_float(equivalence_margin_used),
                "ni_applicable": equivalence_result.get("ni_applicable"),
                "margin_status": equivalence_result.get("margin_status"),
                "reason": equivalence_result.get("reason"),
                "warning": equivalence_result.get("warning"),
                "ni_result": equivalence_result,
            },
        },
        "study_summary": {
            "placebo_mean": placebo_mean,
            "baseline_mean": float(ni_result["baseline_mean"]),
            "treatment_mean": float(ni_result["treatment_mean"]),
            "observed_effect": float(ni_result["point_estimate_diff"]),
            "ci_lower": float(ni_result["ci_lower"]),
            "ci_upper": float(ni_result["ci_upper"]),
            "M1": float(m1_result["m1_point_estimate"]),
            "M1_CI": {
                "lower": float(m1_result["m1_ci_lower"]),
                "upper": float(m1_result["m1_ci_upper"]),
                "level": "95%",
            },
            "ni_margin": nullable_float(ni_result["d_NI"]),
            "verdict": ni_result["verdict"],
            "ni_applicable": ni_applicable,
            "margin_status": applicability_fields["margin_status"],
            "reason": applicability_fields["reason"],
            "warning": applicability_fields["warning"],
            "reasoning": verdict_reasoning,
        },
        "raw_data": {
            "metric": metric_key,
            "metric_label": metric_label,
            "metric_orientation": metric_orientation,
            "placebo": build_series_payload(df_placebo, metric_key),
            "baseline": build_series_payload(df_baseline, metric_key),
            "treatment": build_series_payload(df_treatment, metric_key),
        },
    }

    return result, preprocess_summary


def aggregate_multi_objective(
    metric_results: dict,
    decision_mode: str,
    weights: dict[str, float],
    gatekeepers: list[str],
    weighted_threshold: float,
) -> dict:
    metric_statuses = {}
    method_agreement = {}
    pass_flags = []
    score = 0.0
    assessable_score = 0.0
    assessable_weight = 0.0
    not_assessable_weight = 0.0
    not_assessable_metrics = []
    fragile_any = False
    disagree_any = False

    for metric, result in metric_results.items():
        primary_verdict = result["methods"]["ci_based"]["ni_result"]["verdict"]
        assessable = bool(result.get("ni_applicable", True)) and not is_not_assessable_verdict(primary_verdict)
        metric_weight = float(weights.get(metric, 0.0))
        passes = _is_primary_ni_pass_verdict(primary_verdict) if assessable else None
        if assessable:
            pass_flags.append(bool(passes))
            score += metric_weight * (1.0 if passes else 0.0)
            assessable_score += metric_weight * (1.0 if passes else 0.0)
            assessable_weight += metric_weight
        else:
            not_assessable_metrics.append(metric)
            not_assessable_weight += metric_weight

        method_pass = {}
        for key, method in result["methods"].items():
            verdict = method.get("ni_result", {}).get("verdict", "unknown")
            if is_not_assessable_verdict(verdict):
                method_pass[key] = "not_assessable"
            else:
                method_pass[key] = _is_pass_verdict(verdict)
        method_agreement[metric] = method_pass

        assessable_method_values = [v for v in method_pass.values() if v != "not_assessable"]
        pass_rate = sum(1 for v in assessable_method_values if v) / max(len(assessable_method_values), 1)
        ci_upper = nullable_float(result["methods"]["ci_based"]["ni_result"].get("ci_upper"))
        d_ni = nullable_float(result["methods"]["ci_based"].get("d_NI"))
        eps = 1e-9
        fragility = bool(assessable and ci_upper is not None and d_ni is not None and abs(ci_upper - d_ni) / max(abs(d_ni), eps) < 0.05)
        fragile_any = fragile_any or fragility
        disagree_any = disagree_any or pass_rate < 1.0

        metric_statuses[metric] = {
            "primary_verdict": primary_verdict,
            "ni_applicable": bool(assessable),
            "margin_status": result.get("margin_status"),
            "reason": result.get("reason"),
            "warning": result.get("warning"),
            "pass_rate": float(pass_rate),
            "fragile": bool(fragility),
        }

    has_not_assessable = bool(not_assessable_metrics)

    if has_not_assessable:
        # Any non-assessable metric makes the portfolio not assessable.
        decision_pass = False
        gatekeeper_ok = False
        assessment_status = NOT_ASSESSABLE_VERDICT
        status = "amber"
        policy = (
            "Portfolio aggregation is not assessable because one or more selected metrics have an invalid "
            "fixed-margin NI setup. These metrics are reported separately and are not silently counted as pass or fail."
        )
    elif decision_mode == "strict":
        decision_pass = all(pass_flags)
        gatekeeper_ok = None
        assessment_status = "assessable"
        policy = "Strict mode passes only if every selected metric is non-inferior under the primary CI-based method."
    elif decision_mode == "weighted":
        decision_pass = score >= weighted_threshold
        gatekeeper_ok = None
        assessment_status = "assessable"
        policy = "Weighted mode sums normalized metric weights for primary CI-based passes and compares the score with the threshold."
    elif decision_mode == "gatekeeper":
        gatekeeper_ok = all(_is_primary_ni_pass_verdict(metric_results[m]["methods"]["ci_based"]["ni_result"]["verdict"]) for m in gatekeepers if m in metric_results)
        decision_pass = gatekeeper_ok and score >= weighted_threshold
        assessment_status = "assessable"
        policy = "Gatekeeper mode requires all gatekeeper metrics to pass primary CI-based NI before applying the weighted threshold."
    else:
        decision_pass = all(pass_flags)
        gatekeeper_ok = None
        assessment_status = "assessable"
        policy = "Unknown mode fell back to strict all-metrics pass policy."

    if not has_not_assessable:
        status = "green" if decision_pass else "red"
        if decision_pass and (fragile_any or disagree_any or abs(score - weighted_threshold) < 0.05):
            status = "amber"

    summary = (
        f"Portfolio is not assessable: {', '.join(not_assessable_metrics)} have invalid control-placebo effects."
        if has_not_assessable
        else f"Portfolio is {'acceptable' if decision_pass else 'not acceptable'} under {decision_mode} mode."
    )

    return {
        "decision_mode": decision_mode,
        "score": float(score),
        "assessable_score": float(assessable_score),
        "assessable_weight": float(assessable_weight),
        "not_assessable_weight": float(not_assessable_weight),
        "threshold": float(weighted_threshold),
        "status": status,
        "assessment_status": assessment_status,
        "decision_pass": bool(decision_pass),
        "gatekeeper_ok": gatekeeper_ok,
        "not_assessable_metrics": not_assessable_metrics,
        "policy": policy,
        "summary": summary,
        "metric_statuses": metric_statuses,
        "method_agreement": method_agreement,
    }


# Legacy: Placeholder NI test (mean-based, for backwards compatibility)
def run_non_inferiority_test(
    baseline_df: pd.DataFrame,
    treatment_df: pd.DataFrame,
    metric: str,
    d_ni: float,
    method: str = "fixed-margin-placeholder",
) -> dict:
    baseline_mean = float(baseline_df[metric].mean())
    treatment_mean = float(treatment_df[metric].mean())

    info = get_metric_info(metric)

    # diff is "worsening" relative to baseline
    diff = compute_worsening_effect(baseline_mean, treatment_mean, info["orientation"])

    verdict = "non-inferior" if diff <= d_ni else "inferior"

    return {
        "method": method,
        "metric": metric,
        "direction": info["orientation"],
        "baseline_mean": baseline_mean,
        "treatment_mean": treatment_mean,
        "difference_worse_than_baseline": diff,
        "d_NI": d_ni,
        "verdict": verdict,
        "note": "Legacy mean-based decision. Treat as exploratory, not as the primary fixed-margin NI conclusion.",
        **build_applicability_fields(True),
    }


# Root health-check
@app.route("/")
def index():
    return jsonify({"status": "ok", "message": "MARGIN-SAS backend running"})


# Frontend static files (separated into `frontend/` directory)
@app.route("/dashboard")
def dashboard():
    # Serve the frontend index HTML from the `frontend` folder
    return send_from_directory("frontend", "index.html")


@app.route("/dashboard/evaluate")
def dashboard_evaluate():
    return send_from_directory("frontend", "evaluate.html")


@app.route("/dashboard/methods")
def dashboard_methods():
    return send_from_directory("frontend", "methods.html")


@app.route("/frontend/<path:filename>")
def frontend_static(filename):
    try:
        return send_from_directory("frontend", filename)
    except Exception:
        abort(404)


# Main NI evaluation endpoint
@app.route("/api/ni-evaluate", methods=["POST"])
def ni_evaluate():
    input_mode = request.form.get("input_mode", "separate_files").strip()
    if input_mode not in {"separate_files", "single_file_columns", "manual_entry"}:
        return jsonify({"error": "input_mode must be one of: separate_files, single_file_columns, manual_entry."}), 400

    saved_files = {}

    # Read analysis params
    metric = normalize_metric_key(request.form.get("metric", "latency"))
    metric_label = request.form.get("metric_label", "").strip()
    metrics_raw = request.form.get("metrics", "")
    metrics = parse_metric_list(metrics_raw, metric)
    if any(m not in VALID_QOS_METRICS for m in metrics):
        return jsonify({"error": f"Invalid metrics '{metrics}'. Must be a subset of {sorted(VALID_QOS_METRICS)}."}), 400

    if len(metrics) > 1 and metric_label:
        return jsonify({"error": "metric_label is only supported for single-metric runs."}), 400

    try:
        preservation_fraction = float(request.form.get("preservation_fraction", 0.8))
    except ValueError:
        return jsonify({"error": "preservation_fraction must be a float."}), 400

    if not (0.0 <= preservation_fraction <= 1.0):
        return jsonify({"error": "preservation_fraction must be between 0 and 1."}), 400

    decision_mode = request.form.get("decision_mode", "strict").strip().lower()
    if decision_mode not in {"strict", "weighted", "gatekeeper"}:
        return jsonify({"error": "decision_mode must be one of: strict, weighted, gatekeeper."}), 400

    try:
        weighted_threshold = float(request.form.get("weighted_threshold", 0.7))
    except ValueError:
        return jsonify({"error": "weighted_threshold must be a float."}), 400
    if not (0.0 <= weighted_threshold <= 1.0):
        return jsonify({"error": "weighted_threshold must be between 0 and 1."}), 400

    gatekeepers_raw = request.form.get("gatekeeper_metrics", "")
    gatekeeper_metrics = [m.strip().lower() for m in gatekeepers_raw.split(",") if m.strip() != ""]
    if any(m not in metrics for m in gatekeeper_metrics):
        return jsonify({"error": "gatekeeper_metrics must be a subset of selected metrics."}), 400

    try:
        metric_weights = parse_metric_weights(request.form.get("metric_weights", ""), metrics)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    try:
        bootstrap_resamples = int(request.form.get("bootstrap_resamples", 1000))
    except ValueError:
        return jsonify({"error": "bootstrap_resamples must be an integer."}), 400
    if bootstrap_resamples < 200 or bootstrap_resamples > 20000:
        return jsonify({"error": "bootstrap_resamples must be between 200 and 20000."}), 400

    bootstrap_seed_raw = request.form.get("bootstrap_seed", "").strip()
    if bootstrap_seed_raw == "":
        bootstrap_seed = 42
    else:
        try:
            bootstrap_seed = int(bootstrap_seed_raw)
        except ValueError:
            return jsonify({"error": "bootstrap_seed must be an integer if provided."}), 400
        if bootstrap_seed < 0:
            return jsonify({"error": "bootstrap_seed must be >= 0."}), 400

    bootstrap_mode = request.form.get("bootstrap_mode", "iid").strip().lower()
    if bootstrap_mode not in {"iid", "block"}:
        return jsonify({"error": "bootstrap_mode must be one of: iid, block."}), 400

    bootstrap_block_size = None
    if bootstrap_mode == "block":
        block_raw = request.form.get("bootstrap_block_size", "").strip()
        if block_raw == "":
            return jsonify({"error": "bootstrap_block_size is required for block bootstrap."}), 400
        try:
            bootstrap_block_size = int(block_raw)
        except ValueError:
            return jsonify({"error": "bootstrap_block_size must be an integer."}), 400
        if bootstrap_block_size <= 0:
            return jsonify({"error": "bootstrap_block_size must be > 0."}), 400

    # Optional synthesis settings (comma-separated values)
    try:
        historical_effects = parse_float_list(request.form.get("synthesis_effects", ""))
        historical_ses = parse_float_list(request.form.get("synthesis_ses", ""))
    except ValueError:
        return jsonify({"error": "synthesis_effects and synthesis_ses must be comma-separated numbers."}), 400

    if len(historical_effects) != len(historical_ses):
        return jsonify({"error": "synthesis_effects and synthesis_ses must have equal lengths."}), 400
    if any(se <= 0 for se in historical_ses):
        return jsonify({"error": "All synthesis standard errors must be > 0."}), 400
    synthesis_justification = request.form.get("synthesis_justification", "").strip()

    # Optional equivalence margin (absolute margin around 0 for worsening effect)
    eq_margin_raw = request.form.get("equivalence_margin", "").strip()
    equivalence_margin = None
    if eq_margin_raw != "":
        try:
            equivalence_margin = float(eq_margin_raw)
        except ValueError:
            return jsonify({"error": "equivalence_margin must be numeric if provided."}), 400
        if equivalence_margin <= 0:
            return jsonify({"error": "equivalence_margin must be > 0."}), 400

    # Optional Bayesian settings
    try:
        bayes_prior_mean = float(request.form.get("bayes_prior_mean", 0.0))
        bayes_prior_sd = float(request.form.get("bayes_prior_sd", 10.0))
        bayes_threshold = float(request.form.get("bayes_threshold", 0.95))
    except ValueError:
        return jsonify({"error": "Bayesian parameters must be numeric: bayes_prior_mean, bayes_prior_sd, bayes_threshold."}), 400

    if bayes_prior_sd <= 0:
        return jsonify({"error": "bayes_prior_sd must be > 0."}), 400
    if not (0.0 < bayes_threshold < 1.0):
        return jsonify({"error": "bayes_threshold must be between 0 and 1 (exclusive)."}), 400

    # Build placebo/baseline/treatment datasets from chosen input mode
    try:
        if len(metrics) > 1 and input_mode != "separate_files":
            return jsonify({"error": "Multi-metric evaluation currently requires separate_files input mode."}), 400
        if input_mode == "separate_files":
            placebo_file = request.files.get("placebo_file")
            baseline_file = request.files.get("baseline_file")
            treatment_file = request.files.get("treatment_file")

            if not (placebo_file and baseline_file and treatment_file):
                return jsonify({"error": "Separate files mode requires placebo_file, baseline_file, and treatment_file."}), 400

            for f in [placebo_file, baseline_file, treatment_file]:
                if not allowed_file(f.filename):
                    return jsonify({"error": f"Invalid file type for {f.filename}. Only CSV/TXT allowed."}), 400

            # Persist uploads for hashing, debugging, and reproducible run packages.
            for name, f in [("placebo", placebo_file), ("baseline", baseline_file), ("treatment", treatment_file)]:
                safe_name = secure_filename(f"{name}_{f.filename}")
                save_path = os.path.join(app.config["UPLOAD_FOLDER"], safe_name)
                f.seek(0)
                f.save(save_path)
                saved_files[name] = safe_name

            df_placebo = load_tabular_file(os.path.join(app.config["UPLOAD_FOLDER"], saved_files["placebo"]))
            df_baseline = load_tabular_file(os.path.join(app.config["UPLOAD_FOLDER"], saved_files["baseline"]))
            df_treatment = load_tabular_file(os.path.join(app.config["UPLOAD_FOLDER"], saved_files["treatment"]))

        elif input_mode == "single_file_columns":
            combined_file = request.files.get("combined_file")
            if not combined_file:
                return jsonify({"error": "Single-file mode requires combined_file."}), 400
            if not allowed_file(combined_file.filename):
                return jsonify({"error": f"Invalid file type for {combined_file.filename}. Only CSV/TXT allowed."}), 400

            combined_has_header_raw = request.form.get("combined_has_header", "true").strip().lower()
            combined_has_header = combined_has_header_raw not in {"false", "0", "no", "off"}

            placebo_col = request.form.get("placebo_column", "").strip()
            baseline_col = request.form.get("baseline_column", "").strip()
            treatment_col = request.form.get("treatment_column", "").strip()
            if not (placebo_col and baseline_col and treatment_col):
                return jsonify({"error": "Single-file mode requires placebo_column, baseline_column, and treatment_column."}), 400
            if len({placebo_col, baseline_col, treatment_col}) < 3:
                return jsonify({"error": "Single-file mode requires three distinct column selections."}), 400

            safe_name = secure_filename(f"combined_{combined_file.filename}")
            combined_path = os.path.join(app.config["UPLOAD_FOLDER"], safe_name)
            combined_file.seek(0)
            combined_file.save(combined_path)
            saved_files["combined"] = safe_name

            df_combined = load_tabular_file(combined_path, has_header=combined_has_header)
            missing_cols = [c for c in [placebo_col, baseline_col, treatment_col] if c not in df_combined.columns]
            if missing_cols:
                return jsonify({
                    "error": f"Selected columns not found: {', '.join(missing_cols)}.",
                    "available_columns": [str(c) for c in df_combined.columns],
                }), 400

            df_placebo = pd.DataFrame({metric: pd.to_numeric(df_combined[placebo_col], errors="coerce")})
            df_baseline = pd.DataFrame({metric: pd.to_numeric(df_combined[baseline_col], errors="coerce")})
            df_treatment = pd.DataFrame({metric: pd.to_numeric(df_combined[treatment_col], errors="coerce")})

            saved_files["column_mapping"] = {
                "placebo": placebo_col,
                "baseline": baseline_col,
                "treatment": treatment_col,
                "has_header": combined_has_header,
            }

        else:  # manual_entry
            placebo_values = parse_manual_numeric_values(request.form.get("placebo_values", ""))
            baseline_values = parse_manual_numeric_values(request.form.get("baseline_values", ""))
            treatment_values = parse_manual_numeric_values(request.form.get("treatment_values", ""))

            if not placebo_values or not baseline_values or not treatment_values:
                return jsonify({"error": "Manual mode requires numeric values for placebo_values, baseline_values, and treatment_values."}), 400

            df_placebo = pd.DataFrame({metric: placebo_values})
            df_baseline = pd.DataFrame({metric: baseline_values})
            df_treatment = pd.DataFrame({metric: treatment_values})
            saved_files["manual"] = {
                "placebo_n": len(placebo_values),
                "baseline_n": len(baseline_values),
                "treatment_n": len(treatment_values),
            }
    except Exception as e:
        return jsonify({"error": f"Failed to prepare datasets from input mode '{input_mode}': {e}"}), 400

    # Capture file hashes and sizes to support reproducibility/auditing.
    file_metadata = {}
    for key, value in saved_files.items():
        if isinstance(value, str):
            path = os.path.join(app.config["UPLOAD_FOLDER"], value)
            if os.path.isfile(path):
                file_metadata[key] = {
                    "filename": value,
                    "sha256": compute_file_hash(path),
                    "size_bytes": int(os.path.getsize(path)),
                }

    settings_used = {
        "metrics": metrics,
        "decision_mode": decision_mode,
        "metric_weights": metric_weights,
        "gatekeeper_metrics": gatekeeper_metrics,
        "weighted_threshold": weighted_threshold,
        "preservation_fraction": float(preservation_fraction),
        "bootstrap_resamples": int(bootstrap_resamples),
        "bootstrap_seed": int(bootstrap_seed),
        "bootstrap_mode": bootstrap_mode,
        "bootstrap_block_size": bootstrap_block_size,
        "bayesian": {
            "prior_mean": float(bayes_prior_mean),
            "prior_sd": float(bayes_prior_sd),
            "threshold": float(bayes_threshold),
        },
        "synthesis": {
            "effects": historical_effects,
            "ses": historical_ses,
            "justification": synthesis_justification,
        },
        "equivalence_margin": equivalence_margin,
    }

    config = {
        "preservation_fraction": preservation_fraction,
        "bootstrap_resamples": bootstrap_resamples,
        "bootstrap_seed": bootstrap_seed,
        "bootstrap_mode": bootstrap_mode,
        "bootstrap_block_size": bootstrap_block_size,
        "bayes_prior_mean": bayes_prior_mean,
        "bayes_prior_sd": bayes_prior_sd,
        "bayes_threshold": bayes_threshold,
        "historical_effects": historical_effects,
        "historical_ses": historical_ses,
        "synthesis_justification": synthesis_justification,
        "equivalence_margin": equivalence_margin,
    }

    # Compute results (single or multi-metric)
    try:
        run_id = uuid.uuid4().hex
        preprocess_summary = {}
        if len(metrics) == 1:
            result, preprocess_summary = evaluate_metric_core(
                df_placebo,
                df_baseline,
                df_treatment,
                metrics[0],
                config,
                allow_harmonize=True,
            )

            if metric_label:
                result["metric_label"] = metric_label
                result["raw_data"]["metric_label"] = metric_label

            response_payload = {
                "status": "ok",
                **result,
                "input_mode": input_mode,
                "saved_files": saved_files,
                "file_metadata": file_metadata,
                "settings_used": settings_used,
                "preprocess_summary": preprocess_summary,
                "run_id": run_id,
                "run_package_url": f"/api/run-package/{run_id}",
            }
        else:
            metric_results = {}
            preprocess_summary = {}
            for m in metrics:
                res, summary = evaluate_metric_core(
                    df_placebo,
                    df_baseline,
                    df_treatment,
                    m,
                    config,
                    allow_harmonize=False,
                )
                metric_results[m] = res
                preprocess_summary[m] = summary

            metric_labels = {m: metric_results[m].get("metric_label") for m in metrics}

            portfolio = aggregate_multi_objective(
                metric_results,
                decision_mode,
                metric_weights,
                gatekeeper_metrics,
                weighted_threshold,
            )

            first_metric = metrics[0]
            response_payload = {
                "status": "ok",
                "metrics": metrics,
                "metric_results": metric_results,
                "portfolio": portfolio,
                "input_mode": input_mode,
                "saved_files": saved_files,
                "file_metadata": file_metadata,
                "settings_used": {**settings_used, "metric_labels": metric_labels},
                "preprocess_summary": preprocess_summary,
                "raw_data": metric_results[first_metric].get("raw_data"),
                "run_id": run_id,
                "run_package_url": f"/api/run-package/{run_id}",
            }

        metadata = {
            "run_id": run_id,
            "timestamp_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "settings_used": settings_used,
            "input_mode": input_mode,
            "saved_files": saved_files,
            "file_metadata": file_metadata,
            "preprocess_summary": preprocess_summary,
        }
        save_run_artifacts(run_id, metadata, response_payload)

        return jsonify(response_payload), 200
    except Exception as e:
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@app.route("/api/batch-run", methods=["POST"])
def batch_run():
    payload = request.get_json(silent=True) or {}
    scenarios = payload.get("scenarios", [])
    if not scenarios:
        return jsonify({"error": "scenarios must be a non-empty list."}), 400

    preservation_fractions = payload.get("preservation_fractions", [0.8])
    try:
        preservation_fractions = [float(p) for p in preservation_fractions]
    except Exception:
        return jsonify({"error": "preservation_fractions must be a list of floats."}), 400

    decision_mode = str(payload.get("decision_mode", "strict")).strip().lower()
    if decision_mode not in {"strict", "weighted", "gatekeeper"}:
        return jsonify({"error": "decision_mode must be one of: strict, weighted, gatekeeper."}), 400

    weighted_threshold = float(payload.get("weighted_threshold", 0.7))
    if not (0.0 <= weighted_threshold <= 1.0):
        return jsonify({"error": "weighted_threshold must be between 0 and 1."}), 400

    bootstrap_mode = str(payload.get("bootstrap_mode", "iid")).strip().lower()
    if bootstrap_mode not in {"iid", "block"}:
        return jsonify({"error": "bootstrap_mode must be one of: iid, block."}), 400

    bootstrap_block_size = payload.get("bootstrap_block_size")
    if bootstrap_mode == "block":
        if bootstrap_block_size is None:
            return jsonify({"error": "bootstrap_block_size is required for block bootstrap."}), 400
        try:
            bootstrap_block_size = int(bootstrap_block_size)
        except ValueError:
            return jsonify({"error": "bootstrap_block_size must be an integer."}), 400
        if bootstrap_block_size <= 0:
            return jsonify({"error": "bootstrap_block_size must be > 0."}), 400

    base_config = {
        "bootstrap_resamples": int(payload.get("bootstrap_resamples", 1000)),
        "bootstrap_seed": int(payload.get("bootstrap_seed", 42)),
        "bootstrap_mode": bootstrap_mode,
        "bootstrap_block_size": bootstrap_block_size,
        "bayes_prior_mean": float(payload.get("bayes_prior_mean", 0.0)),
        "bayes_prior_sd": float(payload.get("bayes_prior_sd", 10.0)),
        "bayes_threshold": float(payload.get("bayes_threshold", 0.95)),
        "historical_effects": payload.get("synthesis_effects", []),
        "historical_ses": payload.get("synthesis_ses", []),
        "synthesis_justification": str(payload.get("synthesis_justification", "")).strip(),
        "equivalence_margin": payload.get("equivalence_margin"),
    }

    scenario_results = []
    method_pass_counts = {}
    total_method_checks = 0

    for idx, scenario in enumerate(scenarios):
        name = scenario.get("name", f"scenario_{idx+1}")
        input_mode = scenario.get("input_mode", "separate_files")
        if input_mode != "separate_files":
            return jsonify({"error": f"Scenario '{name}' only supports separate_files mode in batch."}), 400

        metrics = scenario.get("metrics", payload.get("metrics", []))
        if not metrics:
            return jsonify({"error": f"Scenario '{name}' must define metrics."}), 400
        metrics = [str(m).strip().lower() for m in metrics]
        if any(m not in VALID_QOS_METRICS for m in metrics):
            return jsonify({"error": f"Scenario '{name}' has invalid metrics."}), 400

        gatekeepers = scenario.get("gatekeeper_metrics", payload.get("gatekeeper_metrics", []))
        gatekeepers = [str(m).strip().lower() for m in gatekeepers]
        if any(m not in metrics for m in gatekeepers):
            return jsonify({"error": f"Scenario '{name}' gatekeeper_metrics must be subset of metrics."}), 400

        weights_raw = scenario.get("metric_weights", payload.get("metric_weights", ""))
        if isinstance(weights_raw, dict):
            total = sum(float(v) for v in weights_raw.values())
            if total <= 0:
                return jsonify({"error": f"Scenario '{name}' metric_weights must sum to > 0."}), 400
            weights = {m: float(weights_raw.get(m, 0.0)) / total for m in metrics}
        else:
            try:
                weights = parse_metric_weights(weights_raw, metrics)
            except ValueError as e:
                return jsonify({"error": f"Scenario '{name}': {e}"}), 400

        # Resolve relative paths against data/ first, then cwd fallback.
        def _resolve_path(p):
            if os.path.isabs(p):
                return p
            data_path = os.path.join(app.config["UPLOAD_FOLDER"], p)
            if os.path.isfile(data_path):
                return data_path
            return os.path.join(os.getcwd(), p)

        try:
            placebo_path = _resolve_path(scenario["placebo_file"])
            baseline_path = _resolve_path(scenario["baseline_file"])
            treatment_path = _resolve_path(scenario["treatment_file"])
        except KeyError:
            return jsonify({"error": f"Scenario '{name}' requires placebo_file, baseline_file, treatment_file."}), 400

        df_placebo = load_tabular_file(placebo_path)
        df_baseline = load_tabular_file(baseline_path)
        df_treatment = load_tabular_file(treatment_path)

        runs = []
        for p in preservation_fractions:
            config = {**base_config, "preservation_fraction": float(p)}
            metric_results = {}
            for m in metrics:
                res, _ = evaluate_metric_core(
                    df_placebo,
                    df_baseline,
                    df_treatment,
                    m,
                    config,
                    allow_harmonize=False,
                )
                metric_results[m] = res

            portfolio = aggregate_multi_objective(
                metric_results,
                decision_mode,
                weights,
                gatekeepers,
                weighted_threshold,
            )

            # Update method agreement counts
            for m in metrics:
                for method_key, method in metric_results[m]["methods"].items():
                    verdict = method.get("ni_result", {}).get("verdict", "unknown")
                    method_pass_counts.setdefault(method_key, {"pass": 0, "fail": 0, "not_assessable": 0})
                    if is_not_assessable_verdict(verdict):
                        method_pass_counts[method_key]["not_assessable"] += 1
                    else:
                        method_pass_counts[method_key]["pass" if _is_pass_verdict(verdict) else "fail"] += 1
                    total_method_checks += 1

            runs.append({
                "preservation_fraction": float(p),
                "portfolio": portfolio,
            })

        pass_rate = sum(1 for r in runs if r["portfolio"]["status"] == "green") / max(len(runs), 1)
        scenario_results.append({
            "name": name,
            "metrics": metrics,
            "runs": runs,
            "verdict_stability": float(pass_rate),
        })

    method_agreement = {
        m: {
            "pass": v["pass"],
            "fail": v["fail"],
            "not_assessable": v.get("not_assessable", 0),
            "pass_rate": float(v["pass"]) / max(v["pass"] + v["fail"], 1),
            "not_assessable_rate": float(v.get("not_assessable", 0)) / max(v["pass"] + v["fail"] + v.get("not_assessable", 0), 1),
        }
        for m, v in method_pass_counts.items()
    }

    return jsonify({
        "status": "ok",
        "scenario_results": scenario_results,
        "method_agreement": method_agreement,
        "decision_mode": decision_mode,
        "weighted_threshold": weighted_threshold,
    }), 200


if __name__ == "__main__":
    try:
        print("Starting Flask server on http://127.0.0.1:5000")
        app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)
    except Exception as e:
        print(f"Flask startup error: {e}")
        import traceback
        traceback.print_exc()
