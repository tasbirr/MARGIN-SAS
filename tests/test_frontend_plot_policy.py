import json
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
  sys.path.insert(0, ROOT)

from app import app


client = app.test_client()

# Uses a headless Node VM to execute frontend plotting logic.


def post_manual(metric, placebo, baseline, treatment):
    response = client.post(
        "/api/ni-evaluate",
        data={
            "input_mode": "manual_entry",
            "metric": metric,
            "preservation_fraction": "0.8",
            "bootstrap_resamples": "200",
            "placebo_values": ",".join(str(x) for x in placebo),
            "baseline_values": ",".join(str(x) for x in baseline),
            "treatment_values": ",".join(str(x) for x in treatment),
        },
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


NODE_RENDER_SCRIPT = r"""
const fs = require('fs');
const vm = require('vm');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
const code = fs.readFileSync('frontend/js/app.js', 'utf8');

function makeElement(id, elements) {
  const element = {
    id,
    textContent: '',
    innerHTML: '',
    hidden: false,
    className: '',
    value: '',
    checked: id.startsWith('toggle'),
    style: {},
    children: [],
    files: [],
    dataset: {},
    setAttribute(name, value) { this[name] = String(value); },
    getAttribute(name) { return this[name]; },
    appendChild(child) { this.children.push(child); return child; },
    remove() {},
    focus() {},
  };
  const classes = new Set();
  element.classList = {
    add(...names) { names.forEach((name) => classes.add(name)); element.className = Array.from(classes).join(' '); },
    remove(...names) { names.forEach((name) => classes.delete(name)); element.className = Array.from(classes).join(' '); },
    toggle(name, force) {
      if (force === undefined ? !classes.has(name) : force) classes.add(name);
      else classes.delete(name);
      element.className = Array.from(classes).join(' ');
    }
  };
  elements[id] = element;
  return element;
}

function render(data) {
  const elements = {};
  const records = {};
  const purged = [];
  const document = {
    body: makeElement('body', elements),
    documentElement: makeElement('html', elements),
    getElementById(id) { return elements[id] || makeElement(id, elements); },
    createElement(tag) { return makeElement(`${tag}-${Object.keys(elements).length}`, elements); },
    querySelectorAll() { return []; }
  };
  const context = {
    console,
    document,
    window: {
      addEventListener() {},
      matchMedia() { return { matches: false }; },
      setTimeout() {}
    },
    localStorage: { getItem() { return null; }, setItem() {} },
    Plotly: {
      newPlot(id, traces, layout, config) { records[id] = { traces, layout, config }; },
      purge(id) { purged.push(id); }
    },
    URL: { createObjectURL() { return 'blob:test'; }, revokeObjectURL() {} },
    Blob: function Blob() {}
  };
  vm.createContext(context);
  vm.runInContext(code, context);
  context.renderResults(data);
  return {
    records,
    purged,
    primaryTitle: elements.primaryPlotTitle?.textContent,
    primarySummary: elements.primarySummary?.textContent,
    comparisonTitle: elements.comparisonTitle?.textContent,
    comparisonSummary: elements.comparisonSummary?.textContent,
    warningHidden: elements.niWarning?.hidden,
  };
}

process.stdout.write(JSON.stringify(render(payload)));
"""


def render_frontend(payload):
    proc = subprocess.run(
        ["node", "-e", NODE_RENDER_SCRIPT],
        input=json.dumps(payload),
        text=True,
        encoding="utf-8",
    cwd=ROOT,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    return json.loads(proc.stdout)


valid = post_manual(
    "latency",
    placebo=[20.0] * 12,
    baseline=[10.0] * 12,
    treatment=[11.0] * 12,
)
valid_render = render_frontend(valid)
valid_plot = valid_render["records"]["plot"]
valid_annotations = [a.get("text", "") for a in valid_plot["layout"].get("annotations", [])]
valid_shapes = valid_plot["layout"].get("shapes", [])

assert valid["ni_applicable"] is True
assert "Forest-style Effect Plot" in valid_plot["layout"]["title"]
assert any("NI margin Delta" in text for text in valid_annotations)
assert "ACCEPTABLE" in valid_annotations
assert "FAILURE" in valid_annotations
assert any(shape.get("type") == "rect" for shape in valid_shapes)
assert any(
    shape.get("type") == "line"
    and abs(float(shape.get("x0")) - float(valid["d_NI"])) < 1e-9
    and abs(float(shape.get("x1")) - float(valid["d_NI"])) < 1e-9
    for shape in valid_shapes
)


invalid = post_manual(
    "throughput",
    placebo=[100.0] * 12,
    baseline=[90.0] * 12,
    treatment=[89.0] * 12,
)
invalid_render = render_frontend(invalid)
invalid_plot = invalid_render["records"]["plot"]
invalid_annotations = [a.get("text", "") for a in invalid_plot["layout"].get("annotations", [])]
invalid_shapes = invalid_plot["layout"].get("shapes", [])

assert invalid["ni_applicable"] is False
assert invalid["d_NI"] is None
assert invalid["ni_result"]["verdict"] == "not_assessable"
assert invalid_render["warningHidden"] is False
assert invalid_render["primaryTitle"] == "Descriptive effect plot"
assert invalid_plot["layout"]["title"] == "Treatment vs Baseline Effect (Descriptive Only)"
assert "Fixed-margin NI not assessable; plot shown for descriptive interpretation only." in invalid_annotations
assert "ACCEPTABLE" not in invalid_annotations
assert "FAILURE" not in invalid_annotations
assert not any(shape.get("type") == "rect" for shape in invalid_shapes)
assert any(
    shape.get("type") == "line"
    and float(shape.get("x0")) == 0.0
    and float(shape.get("x1")) == 0.0
    for shape in invalid_shapes
)
assert "formal fixed-margin NI conclusion" in invalid_render["primarySummary"]


m1_check = invalid_render["records"]["comparisonPlot"]
m1_annotations = [a.get("text", "") for a in m1_check["layout"].get("annotations", [])]
m1_shapes = m1_check["layout"].get("shapes", [])

assert invalid_render["comparisonTitle"] == "Control–Placebo Effect Check", invalid_render["comparisonTitle"]
assert m1_check["layout"]["title"] == "Control–Placebo Effect Check"
assert "NI not assessable because M1_CI.lower <= 0" in m1_annotations
assert any(
    shape.get("type") == "line"
    and float(shape.get("x0")) == 0.0
    and float(shape.get("x1")) == 0.0
    for shape in m1_shapes
)

print("Frontend plot policy tests passed.")
