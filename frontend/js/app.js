// Frontend JS for MARGIN-SAS Dashboard

function el(id) { return document.getElementById(id); }

let selectedMethod = 'ci_based';
let lastResponse = null;
const THEME_STORAGE_KEY = 'ni-sas-theme';

function getSavedTheme() {
    try {
        return localStorage.getItem(THEME_STORAGE_KEY);
    } catch (_) {
        return null;
    }
}

function saveTheme(theme) {
    try {
        localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch (_) {}
}

function applyTheme(theme) {
    const selectedTheme = theme === 'dark' ? 'dark' : 'light';
    document.documentElement.dataset.theme = selectedTheme;
    document.querySelectorAll('[data-theme-option]').forEach((button) => {
        const active = button.dataset.themeOption === selectedTheme;
        button.classList.toggle('active', active);
        button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
}

function initThemeControls() {
    const systemTheme = window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    applyTheme(getSavedTheme() || systemTheme);
    document.querySelectorAll('[data-theme-option]').forEach((button) => {
        button.addEventListener('click', () => {
            const theme = button.dataset.themeOption === 'dark' ? 'dark' : 'light';
            applyTheme(theme);
            saveTheme(theme);
        });
    });
}

function plotlyAvailable(plotId, summaryId, message) {
    if (typeof Plotly !== 'undefined') return true;
    const plot = el(plotId);
    const summary = el(summaryId);
    if (plot) {
        plot.innerHTML = `<div class="plot-fallback">${message}</div>`;
    }
    if (summary) {
        summary.textContent = message;
    }
    return false;
}

function setText(id, text) {
    const node = el(id);
    if (node) node.textContent = text;
}

function finiteNumber(value) {
    const n = Number(value);
    return Number.isFinite(n) ? n : NaN;
}

function paddedRange(values) {
    const finite = values.map(finiteNumber).filter(Number.isFinite);
    if (!finite.length) return [-1, 1];
    const min = Math.min(...finite);
    const max = Math.max(...finite);
    const span = Math.max(max - min, Math.max(Math.abs(min), Math.abs(max), 1) * 0.12, 0.1);
    return [min - span * 0.25, max + span * 0.25];
}

function getActiveMetricKey(data) {
    return data.metric || (data.metrics && data.metrics.length ? data.metrics[0] : null);
}

function getActiveMetricResult(data) {
    const key = getActiveMetricKey(data);
    if (key && data.metric_results && data.metric_results[key]) {
        return data.metric_results[key];
    }
    return data;
}

function getActiveMetricLabel(data) {
    const metricData = getActiveMetricResult(data);
    return metricData.metric_label || metricData.metric || data.metric_label || data.metric || 'Metric';
}

function getActiveMetricOrientation(data) {
    const metricData = getActiveMetricResult(data);
    return metricData.metric_orientation || data.metric_orientation || '';
}

function formatOrientation(raw) {
    if (!raw) return '';
    return String(raw).replace(/[_-]/g, ' ');
}

function showFileNames() {
    const p = el('placebo');
    const b = el('baseline');
    const t = el('treatment');
    el('placeboName').textContent = p.files[0] ? p.files[0].name : 'no file';
    el('baselineName').textContent = b.files[0] ? b.files[0].name : 'no file';
    el('treatmentName').textContent = t.files[0] ? t.files[0].name : 'no file';
    const c = el('combinedFile');
    const cn = el('combinedName');
    if (cn) cn.textContent = c && c.files[0] ? c.files[0].name : 'no file';
}

function detectDelimiterFromHeaderLine(line) {
    if (line.includes('\t')) return '\t';
    if (line.includes(';')) return ';';
    return ',';
}

function isNumericRow(values) {
    return values.length > 0 && values.every((v) => v !== '' && Number.isFinite(Number(v)));
}

function populateColumnDropdowns(columns) {
    ['placeboColumn', 'baselineColumn', 'treatmentColumn'].forEach((id) => {
        const sel = el(id);
        if (!sel) return;
        sel.innerHTML = '';
        columns.forEach((c) => {
            const opt = document.createElement('option');
            opt.value = c;
            opt.textContent = c;
            sel.appendChild(opt);
        });
    });

    const cols = columns.map((c) => String(c).toLowerCase());
    const setIfFound = (id, candidates) => {
        const idx = cols.findIndex((c) => candidates.some((k) => c.includes(k)));
        if (idx >= 0 && el(id)) el(id).selectedIndex = idx;
    };
    setIfFound('placeboColumn', ['placebo']);
    setIfFound('baselineColumn', ['sr-pomdp', 'baseline', 'control']);
    setIfFound('treatmentColumn', ['mr-pomdp', 'treatment', 'new']);
}

function tryExtractColumnsFromFile(file) {
    return new Promise((resolve) => {
        const reader = new FileReader();
        reader.onload = () => {
            try {
                const txt = String(reader.result || '');
                const lines = txt.split(/\r?\n/).filter((l) => l.trim() !== '');
                if (!lines.length) return resolve([]);
                const delim = detectDelimiterFromHeaderLine(lines[0]);
                const firstRow = lines[0].split(delim).map((x) => x.trim()).filter(Boolean);
                const hasHeaderToggle = el('combinedHasHeader');
                const userHasHeader = hasHeaderToggle ? hasHeaderToggle.checked : true;
                const looksNumeric = isNumericRow(firstRow);

                if (looksNumeric) {
                    if (hasHeaderToggle) hasHeaderToggle.checked = false;
                    return resolve(firstRow.map((_, idx) => `col${idx + 1}`));
                }

                if (!userHasHeader) {
                    return resolve(firstRow.map((_, idx) => `col${idx + 1}`));
                }

                resolve(firstRow);
            } catch (_) {
                resolve([]);
            }
        };
        reader.onerror = () => resolve([]);
        reader.readAsText(file);
    });
}

function updateInputModeUI() {
    const mode = el('inputMode')?.value || 'separate_files';
    const activate = (id, yes) => {
        const node = el(id);
        if (!node) return;
        node.classList.toggle('active', yes);
        node.setAttribute('aria-hidden', yes ? 'false' : 'true');
        node.querySelectorAll('input, select, textarea').forEach((field) => {
            field.disabled = !yes;
            field.required = yes && field.dataset.required === 'true';
        });
    };
    activate('separateFilesSection', mode === 'separate_files');
    activate('singleFileSection', mode === 'single_file_columns');
    activate('manualEntrySection', mode === 'manual_entry');
}

function hasRequiredInputsForCurrentMode() {
    const mode = el('inputMode')?.value || 'separate_files';
    if (mode === 'separate_files') {
        return !!(el('placebo')?.files[0] && el('baseline')?.files[0] && el('treatment')?.files[0]);
    }
    if (mode === 'single_file_columns') {
        return !!(el('combinedFile')?.files[0] && el('placeboColumn')?.value && el('baselineColumn')?.value && el('treatmentColumn')?.value);
    }
    return !!(el('placeboValues')?.value.trim() && el('baselineValues')?.value.trim() && el('treatmentValues')?.value.trim());
}

async function postForm(formData) {
    const res = await fetch('/api/ni-evaluate', { method: 'POST', body: formData });
    const json = await res.json();
    if (!res.ok) throw new Error(json.error || 'Server error');
    return json;
}

function getMethodData(data, methodKey) {
    const metricData = getActiveMetricResult(data);
    if (metricData.methods && metricData.methods[methodKey]) {
        return metricData.methods[methodKey];
    }
    return {
        label: 'Fixed-margin 95-95 (CI-based)',
        preferred: true,
        M1: metricData.M1,
        M1_CI: metricData.M1_CI,
        d_NI: metricData.d_NI,
        ni_result: metricData.ni_result
    };
}

function getCiLowerForCurrentDecision(data) {
    const ci = getMethodData(data, 'ci_based');
    if (ci && ci.M1_CI && ci.M1_CI.lower !== undefined) return Number(ci.M1_CI.lower);
    const metricData = getActiveMetricResult(data);
    if (metricData.M1_CI && metricData.M1_CI.lower !== undefined) return Number(metricData.M1_CI.lower);
    return 0;
}

function renderControlPlaceboEffectCheckPlot(data) {
    if (!plotlyAvailable('comparisonPlot', 'comparisonSummary', 'Control-placebo effect check unavailable because the chart library did not load.')) return;

    const metricData = getActiveMetricResult(data);
    const metricLabel = getActiveMetricLabel(data);
    const m1 = finiteNumber(metricData.M1 ?? metricData.methods?.ci_based?.M1);
    const m1Ci = metricData.M1_CI || metricData.methods?.ci_based?.M1_CI || {};
    const lower = finiteNumber(m1Ci.lower);
    const upper = finiteNumber(m1Ci.upper);

    setText('comparisonTitle', 'Control–Placebo Effect Check');

    if (!Number.isFinite(m1) || !Number.isFinite(lower) || !Number.isFinite(upper)) {
        Plotly.purge('comparisonPlot');
        setText('comparisonSummary', 'Control-placebo effect check unavailable because M1 or M1_CI is missing.');
        return;
    }

    const trace = {
        x: [m1],
        y: ['M1'],
        mode: 'markers',
        type: 'scatter',
        name: 'M1 control-placebo effect',
        marker: {
            color: '#b45309',
            size: 13,
            line: { color: '#7c2d12', width: 2 }
        },
        error_x: {
            type: 'data',
            symmetric: false,
            array: [Math.max(0, upper - m1)],
            arrayminus: [Math.max(0, m1 - lower)],
            color: '#b45309',
            thickness: 3,
            width: 0
        },
        hovertemplate: 'M1: %{x:.6f}<br>95% CI: [' + lower.toFixed(6) + ', ' + upper.toFixed(6) + ']<extra></extra>'
    };

    const range = paddedRange([lower, upper, m1, 0]);
    const layout = {
        title: 'Control–Placebo Effect Check',
        xaxis: { title: `Oriented control-placebo effect M1 (${metricLabel})`, range, zeroline: false },
        yaxis: { title: '', showticklabels: true, range: [-0.5, 0.5] },
        shapes: [
            {
                type: 'line',
                x0: 0,
                x1: 0,
                y0: -0.5,
                y1: 0.5,
                line: { color: '#495057', width: 2 }
            }
        ],
        annotations: [
            {
                x: 0,
                y: 0.35,
                xref: 'x',
                yref: 'y',
                text: 'No benefit threshold (0)',
                showarrow: false,
                font: { color: '#495057', size: 12 }
            },
            {
                x: lower,
                y: -0.3,
                xref: 'x',
                yref: 'y',
                text: 'NI not assessable because M1_CI.lower <= 0',
                showarrow: true,
                arrowhead: 2,
                ax: 30,
                ay: 30,
                font: { color: '#b45309', size: 11 }
            }
        ],
        showlegend: false,
        margin: { t: 58, r: 20, b: 58, l: 42 },
        plot_bgcolor: '#ffffff',
        paper_bgcolor: '#ffffff'
    };

    Plotly.newPlot('comparisonPlot', [trace], layout, { responsive: true });
    setText('comparisonSummary', 'This plot checks whether the active control demonstrates benefit over placebo. Fixed-margin NI is not assessable when M1_CI.lower <= 0.');
}

function renderMethodComparisonPlot(data) {
    if (!plotlyAvailable('comparisonPlot', 'comparisonSummary', 'Method comparison plot unavailable because the chart library did not load.')) return;

    const metricData = getActiveMetricResult(data);
    const methods = metricData.methods || {};
    const metricLabel = getActiveMetricLabel(data);
    const labels = [];
    const margins = [];
    const effects = [];

    if (metricData.ni_applicable === false) {
        renderControlPlaceboEffectCheckPlot(data);
        return;
    }

    setText('comparisonTitle', 'Method comparison');

    if (!Object.keys(methods).length) {
        Plotly.purge('comparisonPlot');
        const summary = el('comparisonSummary');
        if (summary) summary.textContent = 'Method comparison unavailable for this response.';
        return;
    }

    Object.entries(methods).forEach(([key, method]) => {
        labels.push(method.label || key);
        margins.push(Number(method.d_NI ?? NaN));
        const r = method.ni_result || {};
        const effect = r.point_estimate_diff ?? r.difference_worse_than_baseline ?? r.posterior?.mean ?? NaN;
        effects.push(Number(effect));
    });

    const marginTrace = {
        x: labels,
        y: margins,
        type: 'bar',
        name: 'Margin (d)',
        marker: { color: '#2454d6' }
    };

    const effectTrace = {
        x: labels,
        y: effects,
        type: 'bar',
        name: 'Observed effect',
        marker: { color: '#d97706' }
    };

    const layout = {
        barmode: 'group',
        margin: { t: 20, r: 10, b: 90, l: 55 },
        yaxis: { title: `Worsening effect / margin (${metricLabel})` },
        xaxis: { tickangle: -20 }
    };

    Plotly.newPlot('comparisonPlot', [marginTrace, effectTrace], layout, { responsive: true });
}

function renderPosteriorPlot(data) {
    if (!plotlyAvailable('posteriorPlot', 'posteriorSummary', 'Posterior plot unavailable because the chart library did not load.')) return;

    const bayes = getMethodData(data, 'bayesian')?.ni_result;
    if (!bayes || !bayes.posterior) {
        Plotly.purge('posteriorPlot');
        return;
    }

    const mu = Number(bayes.posterior.mean);
    const sd = Number(bayes.posterior.sd);
    const d = Number(getMethodData(data, 'bayesian').d_NI);
    const metricLabel = getActiveMetricLabel(data);

    if (!Number.isFinite(d)) {
        const marker = {
            x: [mu], y: [1], mode: 'markers', type: 'scatter', marker: { size: 10, color: '#2454d6' }, name: 'Posterior summary'
        };
        Plotly.newPlot('posteriorPlot', [marker], { margin: { t: 20, r: 10, b: 50, l: 45 }, xaxis: { title: `Worsening effect (${metricLabel})` }, yaxis: { visible: false } }, { responsive: true });
        return;
    }

    if (!isFinite(mu) || !isFinite(sd) || sd <= 0) {
        const marker = {
            x: [mu], y: [1], mode: 'markers', type: 'scatter', marker: { size: 10, color: '#2a9d8f' }, name: 'Posterior point'
        };
        Plotly.newPlot('posteriorPlot', [marker], { margin: { t: 20, r: 10, b: 50, l: 45 }, xaxis: { title: `Worsening effect (${metricLabel})` }, yaxis: { visible: false } }, { responsive: true });
        return;
    }

    const xs = [];
    const ys = [];
    const start = mu - 4 * sd;
    const end = mu + 4 * sd;
    const n = 160;
    for (let i = 0; i < n; i++) {
        const x = start + (i / (n - 1)) * (end - start);
        const y = (1 / (sd * Math.sqrt(2 * Math.PI))) * Math.exp(-0.5 * ((x - mu) / sd) ** 2);
        xs.push(x);
        ys.push(y);
    }

    const density = {
        x: xs,
        y: ys,
        mode: 'lines',
        type: 'scatter',
        line: { color: '#2454d6', width: 3 },
        name: 'Posterior density'
    };

    const layout = {
        margin: { t: 20, r: 10, b: 50, l: 45 },
        xaxis: { title: `Worsening effect (${metricLabel})` },
        yaxis: { title: 'Density' },
        shapes: [
            { type: 'line', x0: d, x1: d, y0: 0, y1: Math.max(...ys), line: { color: '#264653', width: 2, dash: 'dash' } }
        ],
        annotations: [
            { x: d, y: Math.max(...ys), text: `d = ${d.toFixed(4)}`, showarrow: true, arrowhead: 2, ay: -30 }
        ]
    };

    Plotly.newPlot('posteriorPlot', [density], layout, { responsive: true });
}

function renderRawDataPlot(data) {
    if (!plotlyAvailable('rawDataPlot', 'rawDataSummary', 'Raw data plot unavailable because the chart library did not load.')) return;

    const metricData = getActiveMetricResult(data);
    const raw = metricData.raw_data || data.raw_data;
    if (!raw || !raw.placebo || !raw.baseline || !raw.treatment) {
        Plotly.purge('rawDataPlot');
        const summary = el('rawDataSummary');
        if (summary) summary.textContent = 'Raw data plot unavailable for this run.';
        return;
    }

    const showPlacebo = el('togglePlacebo')?.checked ?? true;
    const showBaseline = el('toggleBaseline')?.checked ?? true;
    const showTreatment = el('toggleTreatment')?.checked ?? true;

    const traces = [];
    if (showPlacebo) {
        traces.push({
            x: raw.placebo.x,
            y: raw.placebo.y,
            mode: 'lines',
            type: 'scatter',
            name: 'Placebo',
            line: { color: '#94a3b8', width: 2 }
        });
    }
    if (showBaseline) {
        traces.push({
            x: raw.baseline.x,
            y: raw.baseline.y,
            mode: 'lines',
            type: 'scatter',
            name: 'Baseline',
            line: { color: '#2563eb', width: 2 }
        });
    }
    if (showTreatment) {
        traces.push({
            x: raw.treatment.x,
            y: raw.treatment.y,
            mode: 'lines',
            type: 'scatter',
            name: 'Treatment',
            line: { color: '#ef4444', width: 2 }
        });
    }

    if (!traces.length) {
        traces.push({
            x: [0],
            y: [0],
            mode: 'markers',
            type: 'scatter',
            marker: { opacity: 0 },
            showlegend: false,
            hoverinfo: 'skip'
        });
    }

    const metricLabel = raw.metric_label || raw.metric || 'Metric value';
    const layout = {
        margin: { t: 20, r: 10, b: 50, l: 55 },
        xaxis: { title: 'Timestep' },
        yaxis: { title: metricLabel },
        legend: { orientation: 'h', x: 0, y: 1.2 }
    };

    Plotly.newPlot('rawDataPlot', traces, layout, { responsive: true });

    const summary = el('rawDataSummary');
    if (summary) {
        summary.textContent = `Shows trajectory of ${metricLabel} over time. Plotted points - Placebo: ${raw.placebo.n_plotted}/${raw.placebo.n_total}, Baseline: ${raw.baseline.n_plotted}/${raw.baseline.n_total}, Treatment: ${raw.treatment.n_plotted}/${raw.treatment.n_total}.`;
    }
}

function renderSensitivityHeatmap(data) {
    if (!plotlyAvailable('sensitivityPlot', 'sensitivitySummary', 'Sensitivity heatmap unavailable because the chart library did not load.')) return;

    const metricData = getActiveMetricResult(data);
    if (metricData.ni_applicable === false) {
        Plotly.purge('sensitivityPlot');
        const summary = el('sensitivitySummary');
        if (summary) summary.textContent = 'Sensitivity heatmap is not shown because the fixed-margin NI threshold is not assessable for this metric.';
        return;
    }

    const ps = [];
    for (let p = 0.5; p <= 0.95 + 1e-9; p += 0.05) ps.push(Number(p.toFixed(2)));

    const ciMethod = getMethodData(data, 'ci_based');
    const meanMethod = getMethodData(data, 'mean_based');
    const synMethod = getMethodData(data, 'synthesis');
    const bayesMethod = getMethodData(data, 'bayesian');
    const eqMethod = getMethodData(data, 'equivalence');

    const m1Lower = getCiLowerForCurrentDecision(data);
    const diffCiUpper = Number(ciMethod?.ni_result?.ci_upper ?? metricData.ni_result?.ci_upper ?? NaN);
    const diffMean = Number(meanMethod?.ni_result?.difference_worse_than_baseline ?? NaN);
    const synLower = Number(synMethod?.details?.pooled_m1_ci_lower ?? NaN);
    const postMean = Number(bayesMethod?.ni_result?.posterior?.mean ?? NaN);
    const postSd = Number(bayesMethod?.ni_result?.posterior?.sd ?? NaN);
    const bayesThreshold = Number(bayesMethod?.ni_result?.threshold ?? 0.95);
    const eqCiLower = Number(eqMethod?.ni_result?.ci_lower ?? NaN);
    const eqCiUpper = Number(eqMethod?.ni_result?.ci_upper ?? NaN);

    const methods = ['CI-based', 'Synthesis', 'Bayesian', 'Equivalence', 'Mean-based'];

    const z = methods.map(() => ps.map(() => 0));

    ps.forEach((p, i) => {
        const dCi = m1Lower * (1 - p);
        const dMean = Number(meanMethod?.M1 ?? 0) * (1 - p);
        const dSyn = isFinite(synLower) ? synLower * (1 - p) : dCi;
        const dEq = Math.abs(dCi);

        z[0][i] = isFinite(diffCiUpper) && diffCiUpper <= dCi ? 1 : 0;
        z[1][i] = isFinite(diffCiUpper) && diffCiUpper <= dSyn ? 1 : 0;

        if (isFinite(postMean) && isFinite(postSd) && postSd > 0) {
            const prob = 0.5 * (1 + erf((dCi - postMean) / (postSd * Math.sqrt(2))));
            z[2][i] = prob >= bayesThreshold ? 1 : 0;
        } else {
            z[2][i] = 0;
        }

        z[3][i] = isFinite(eqCiLower) && isFinite(eqCiUpper) && eqCiLower >= -dEq && eqCiUpper <= dEq ? 1 : 0;
        z[4][i] = isFinite(diffMean) && diffMean <= dMean ? 1 : 0;
    });

    const trace = {
        z,
        x: ps,
        y: methods,
        type: 'heatmap',
        colorscale: [
            [0, '#f8d7da'],
            [0.5, '#fff3cd'],
            [1, '#d4edda']
        ],
        zmin: 0,
        zmax: 1,
        showscale: false,
        hovertemplate: 'Method: %{y}<br>p=%{x}<br>Pass=%{z}<extra></extra>'
    };

    const layout = {
        margin: { t: 20, r: 10, b: 45, l: 100 },
        xaxis: { title: 'Preservation fraction (p)' }
    };

    Plotly.newPlot('sensitivityPlot', [trace], layout, { responsive: true });
}

function erf(x) {
    const sign = x >= 0 ? 1 : -1;
    x = Math.abs(x);
    const a1 = 0.254829592;
    const a2 = -0.284496736;
    const a3 = 1.421413741;
    const a4 = -1.453152027;
    const a5 = 1.061405429;
    const p = 0.3275911;
    const t = 1 / (1 + p * x);
    const y = 1 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * Math.exp(-x * x);
    return sign * y;
}

function fmtNum(v, digits = 4) {
    const n = Number(v);
    return Number.isFinite(n) ? n.toFixed(digits) : 'N/A';
}

function fmtNullable(v, digits = 4, fallback = 'N/A') {
    if (v === null || v === undefined || v === '') return fallback;
    const n = Number(v);
    return Number.isFinite(n) ? n.toFixed(digits) : fallback;
}

function isNotAssessable(verdict) {
    return String(verdict || '').toLowerCase() === 'not_assessable';
}

function verdictForDisplay(verdict) {
    return String(verdict || 'unknown').replace(/_/g, ' ').toUpperCase();
}

function updateNiWarning(data) {
    const warning = el('niWarning');
    if (!warning) return;
    const metricData = getActiveMetricResult(data);
    const summary = metricData.study_summary || data.study_summary || {};
    const notAssessable = metricData.ni_applicable === false || summary.ni_applicable === false;
    warning.hidden = !notAssessable;
    if (!notAssessable) return;

    const m1Ci = metricData.M1_CI || summary.M1_CI || {};
    if (el('niWarningText')) el('niWarningText').textContent = metricData.warning || summary.warning || metricData.reason || summary.reason || 'Fixed-margin NI is not assessable for this run.';
    if (el('niWarningMetric')) el('niWarningMetric').textContent = getActiveMetricLabel(data);
    if (el('niWarningOrientation')) el('niWarningOrientation').textContent = formatOrientation(getActiveMetricOrientation(data)) || '-';
    if (el('niWarningPlacebo')) el('niWarningPlacebo').textContent = fmtNullable(summary.placebo_mean ?? metricData.placebo_mean, 6);
    if (el('niWarningBaseline')) el('niWarningBaseline').textContent = fmtNullable(summary.baseline_mean ?? metricData.baseline_mean, 6);
    if (el('niWarningM1')) el('niWarningM1').textContent = fmtNullable(metricData.M1 ?? summary.M1, 6);
    if (el('niWarningM1Ci')) el('niWarningM1Ci').textContent = `[${fmtNullable(m1Ci.lower, 6)}, ${fmtNullable(m1Ci.upper, 6)}]`;
    if (el('niWarningReason')) el('niWarningReason').textContent = metricData.reason || summary.reason || 'The active-control effect over placebo is not positive on the selected metric.';
}

function renderMethodAgreement(data) {
    const body = el('agreementBody');
    const consensus = el('agreementConsensus');
    if (!body || !consensus) return;

    body.innerHTML = '';
    const metricData = getActiveMetricResult(data);
    const methods = metricData.methods || {};
    const rows = Object.values(methods);
    let passCount = 0;
    let failCount = 0;
    let notAssessableCount = 0;

    if (!rows.length) {
        consensus.textContent = 'Method agreement unavailable for this response.';
        return;
    }

    rows.forEach((m) => {
        const verdict = String(m?.ni_result?.verdict || 'unknown').toLowerCase();
        const passes = verdict === 'non-inferior' || verdict === 'equivalent';
        const notAssessable = isNotAssessable(verdict);
        if (notAssessable) notAssessableCount += 1;
        else if (passes) passCount += 1;
        else failCount += 1;

        const tr = document.createElement('tr');
        const tdMethod = document.createElement('td');
        tdMethod.textContent = m.label || 'Method';
        const tdResult = document.createElement('td');
        tdResult.textContent = verdictForDisplay(verdict);
        tdResult.className = notAssessable ? 'result-warning' : (passes ? 'result-pass' : 'result-fail');
        tr.appendChild(tdMethod);
        tr.appendChild(tdResult);
        body.appendChild(tr);
    });

    const total = rows.length;
    const unanimous = passCount === total || failCount === total || notAssessableCount === total;
    consensus.textContent = `Consensus: ${Math.max(passCount, failCount, notAssessableCount)}/${total} methods agree (${passCount} pass, ${failCount} fail, ${notAssessableCount} not assessable). ${unanimous ? 'Unanimous result.' : 'Mixed result across methods.'}`;
}

function updateMiniKpis(data) {
    const metricData = getActiveMetricResult(data);
    const raw = metricData.raw_data || data.raw_data || {};
    const totalSamples = (raw.placebo?.n_total || 0) + (raw.baseline?.n_total || 0) + (raw.treatment?.n_total || 0);
    const methodLabel = getMethodData(data, selectedMethod)?.label || '-';
    const p = Number(data.preservation_fraction ?? el('preservation')?.value ?? NaN);

    const methods = metricData.methods || data.methods || {};
    const rows = Object.values(methods);
    const notAssessable = rows.filter((m) => isNotAssessable(m?.ni_result?.verdict)).length;
    const pass = rows.filter((m) => {
        const v = String(m?.ni_result?.verdict || '').toLowerCase();
        return v === 'non-inferior' || v === 'equivalent';
    }).length;

    if (el('kpiSamples')) el('kpiSamples').textContent = totalSamples ? String(totalSamples) : '-';
    if (el('kpiMethod')) el('kpiMethod').textContent = methodLabel;
    if (el('kpiP')) el('kpiP').textContent = Number.isFinite(p) ? p.toFixed(2) : '-';
    if (el('kpiAgreement')) el('kpiAgreement').textContent = rows.length ? (notAssessable ? `${notAssessable}/${rows.length} not assessable` : `${pass}/${rows.length} pass`) : '-';
}

function updateStudySummary(data, methodData, methodResult, fallbackResult) {
    const summary = el('studySummaryText');
    const reasoning = el('verdictReasoning');
    if (!summary || !reasoning) return;

    const metricData = getActiveMetricResult(data);
    const metricLabel = getActiveMetricLabel(data);
    const orientationText = formatOrientation(getActiveMetricOrientation(data));
    const s = metricData.study_summary || data.study_summary || {};
    const baselineMean = Number(s.baseline_mean ?? methodResult.baseline_mean ?? fallbackResult.baseline_mean);
    const treatmentMean = Number(s.treatment_mean ?? methodResult.treatment_mean ?? fallbackResult.treatment_mean);
    const effect = Number(s.observed_effect ?? methodResult.point_estimate_diff ?? methodResult.difference_worse_than_baseline ?? fallbackResult.point_estimate_diff);
    const ciLower = Number(s.ci_lower ?? methodResult.ci_lower ?? fallbackResult.ci_lower);
    const ciUpper = Number(s.ci_upper ?? methodResult.ci_upper ?? fallbackResult.ci_upper);
    const marginRaw = s.ni_margin ?? methodData.d_NI;
    const verdict = String(s.verdict ?? methodResult.verdict ?? fallbackResult.verdict ?? 'unknown').toLowerCase();
    const b = methodResult.bootstrap_ci;
    const bText = b ? ` | Bootstrap 95% CI (${b.n_resamples}): [${fmtNum(b.lower, 6)}, ${fmtNum(b.upper, 6)}]` : '';
    const orientationNote = orientationText ? ` (${orientationText})` : '';

    summary.textContent = `Metric: ${metricLabel}${orientationNote} | Baseline mean: ${fmtNum(baselineMean, 6)} | Treatment mean: ${fmtNum(treatmentMean, 6)} | Observed worsening effect: ${fmtNum(effect, 6)} | 95% CI: [${fmtNum(ciLower, 6)}, ${fmtNum(ciUpper, 6)}]${bText} | NI margin: ${fmtNullable(marginRaw, 6, 'not defined')}. Conclusion: ${verdictForDisplay(verdict)}.`;

    reasoning.textContent = s.reasoning || methodResult.reason || `Decision rule uses CI upper <= d_NI. Here, CI upper is ${fmtNum(ciUpper, 6)} and d_NI is ${fmtNullable(marginRaw, 6, 'not defined')}.`;
}

function syncSliderDisplay() {
    const slider = el('preservationSlider');
    const output = el('preservationSliderValue');
    const numeric = el('preservation');
    if (!slider || !output || !numeric) return;
    output.textContent = Number(slider.value).toFixed(2);
    numeric.value = Number(slider.value).toFixed(2);
}

function buildFormDataFromInputs() {
    const formData = new FormData();
    const mode = el('inputMode')?.value || 'separate_files';
    formData.append('input_mode', mode);

    if (mode === 'separate_files') {
        formData.append('placebo_file', el('placebo').files[0]);
        formData.append('baseline_file', el('baseline').files[0]);
        formData.append('treatment_file', el('treatment').files[0]);
    } else if (mode === 'single_file_columns') {
        formData.append('combined_file', el('combinedFile').files[0]);
        formData.append('placebo_column', el('placeboColumn').value);
        formData.append('baseline_column', el('baselineColumn').value);
        formData.append('treatment_column', el('treatmentColumn').value);
        formData.append('combined_has_header', el('combinedHasHeader')?.checked ? 'true' : 'false');
    } else {
        formData.append('placebo_values', el('placeboValues').value);
        formData.append('baseline_values', el('baselineValues').value);
        formData.append('treatment_values', el('treatmentValues').value);
    }

    formData.append('metric', el('metric').value);
    formData.append('metrics', el('metricsList')?.value ?? '');
    formData.append('preservation_fraction', el('preservation').value);
    formData.append('decision_mode', el('decisionMode')?.value ?? 'strict');
    formData.append('metric_weights', el('metricWeights')?.value ?? '');
    formData.append('gatekeeper_metrics', el('gatekeeperMetrics')?.value ?? '');
    formData.append('weighted_threshold', el('weightedThreshold')?.value ?? '0.7');
    formData.append('bayes_prior_mean', el('bayesPriorMean').value);
    formData.append('bayes_prior_sd', el('bayesPriorSd').value);
    formData.append('bayes_threshold', el('bayesThreshold').value);
    formData.append('bootstrap_resamples', el('bootstrapResamples').value);
    formData.append('bootstrap_seed', el('bootstrapSeed')?.value ?? '');
    formData.append('bootstrap_mode', el('bootstrapMode')?.value ?? 'iid');
    formData.append('bootstrap_block_size', el('bootstrapBlockSize')?.value ?? '');
    formData.append('synthesis_effects', el('synthesisEffects').value);
    formData.append('synthesis_ses', el('synthesisSes').value);
    formData.append('equivalence_margin', el('equivalenceMargin').value);
    return formData;
}

async function downloadStudyReport() {
    if (!lastResponse) {
        el('error').textContent = 'Error: Run an evaluation first, then download the study report.';
        el('error').classList.add('show');
        return;
    }
    try {
        const res = await fetch('/api/study-report', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(lastResponse)
        });
        if (!res.ok) {
            let msg = 'Failed to generate PDF report.';
            try {
                const e = await res.json();
                msg = e.error || msg;
            } catch (_) {}
            throw new Error(msg);
        }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'margin_sas_study_report.pdf';
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    } catch (err) {
        el('error').textContent = `Error: ${err.message}`;
        el('error').classList.add('show');
    }
}

async function downloadRunPackage() {
    if (!lastResponse || !lastResponse.run_package_url) {
        el('error').textContent = 'Error: Run an evaluation first, then download the run package.';
        el('error').classList.add('show');
        return;
    }
    try {
        const res = await fetch(lastResponse.run_package_url, { method: 'GET' });
        if (!res.ok) throw new Error('Failed to download run package.');
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `run_${lastResponse.run_id || 'package'}.zip`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    } catch (err) {
        el('error').textContent = `Error: ${err.message}`;
        el('error').classList.add('show');
    }
}

async function evaluateCurrentForm() {
    setLoading(true);
    el('error').classList.remove('show');
    el('results').classList.remove('show');
    try {
        const formData = buildFormDataFromInputs();
        const data = await postForm(formData);
        lastResponse = data;
        renderResults(data);
    } catch (err) {
        el('error').textContent = `Error: ${err.message}`;
        el('error').classList.add('show');
    } finally {
        setLoading(false);
    }
}

function updateChartSummaries(data, methodData, methodResult, fallbackResult) {
    const metricData = getActiveMetricResult(data);
    const metricLabel = getActiveMetricLabel(data);
    const orientationText = formatOrientation(getActiveMetricOrientation(data));
    const diff = methodResult.point_estimate_diff ?? methodResult.difference_worse_than_baseline ?? fallbackResult.point_estimate_diff;
    const ciLower = methodResult.ci_lower ?? methodResult.posterior?.ci95_lower ?? fallbackResult.ci_lower;
    const ciUpper = methodResult.ci_upper ?? methodResult.posterior?.ci95_upper ?? fallbackResult.ci_upper;
    const dni = methodData.d_NI;
    const verdict = (methodResult.verdict || fallbackResult.verdict || '').toLowerCase();
    const notAssessable = isNotAssessable(verdict);
    const decisionText = notAssessable
        ? 'This method is not assessable as a formal NI conclusion.'
        : (verdict === 'non-inferior' || verdict === 'equivalent')
        ? 'This method currently supports acceptance.'
        : 'This method currently does not support acceptance.';

    const primary = el('primarySummary');
    if (primary) {
        const b = methodResult.bootstrap_ci;
        const bText = b ? ` Bootstrap 95% CI (${b.n_resamples} resamples): [${fmtNum(b.lower, 6)}, ${fmtNum(b.upper, 6)}].` : '';
        const orientationNote = orientationText ? ` Orientation: ${orientationText}.` : '';
        if (metricData.ni_applicable === false) {
            primary.textContent = `This scenario does not support a formal fixed-margin NI conclusion because the active control does not demonstrate benefit over placebo. Worsening effect (${metricLabel}) = ${fmtNum(diff, 6)}; 95% CI = [${fmtNum(ciLower, 6)}, ${fmtNum(ciUpper, 6)}].${bText}${orientationNote}`;
        } else {
            primary.textContent = `Worsening effect (${metricLabel}) = ${fmtNum(diff, 6)}; 95% CI = [${fmtNum(ciLower, 6)}, ${fmtNum(ciUpper, 6)}]; NI margin Delta = ${fmtNullable(dni, 6, 'not defined')}.${bText} Rule: NI when CI upper <= Delta only when the margin is valid. ${decisionText}${orientationNote}`;
        }
    }

    const methods = metricData.methods || {};
    const comparisons = Object.values(methods).map((m) => {
        const r = m.ni_result || {};
        const effect = Number(r.point_estimate_diff ?? r.difference_worse_than_baseline ?? r.posterior?.mean ?? NaN);
        const margin = Number(m.d_NI ?? NaN);
        const pass = Number.isFinite(effect) && Number.isFinite(margin) ? effect <= margin : false;
        return { pass };
    });
    const passCount = comparisons.filter(x => x.pass).length;
    const totalCount = comparisons.length;
    const comparison = el('comparisonSummary');
    if (comparison) {
        if (metricData.ni_applicable === false) {
            comparison.textContent = 'Control-placebo effect check explains why the NI margin is invalid: fixed-margin NI is not assessable when M1_CI.lower <= 0.';
        } else {
            comparison.textContent = `Each bar pair shows observed worsening (${metricLabel}) vs margin for a method. If observed effect is at or below margin, that method passes. Current run: ${passCount}/${totalCount || 0} methods pass.`;
        }
    }

    const bayes = getMethodData(data, 'bayesian')?.ni_result;
    const posterior = el('posteriorSummary');
    if (posterior) {
        if (bayes && bayes.posterior) {
            posterior.textContent = `Posterior mean (worsening effect for ${metricLabel}) = ${fmtNum(bayes.posterior.mean)} with SD = ${fmtNum(bayes.posterior.sd)}. Probability P(effect <= d) = ${fmtNullable(bayes.probability_non_inferior)}; threshold = ${fmtNum(bayes.threshold, 2)}. Bayesian verdict: ${verdictForDisplay(bayes.verdict || 'N/A')}.`;
        } else {
            posterior.textContent = 'Bayesian summary unavailable for this run (missing posterior inputs/output).';
        }
    }

    const ciMethod = getMethodData(data, 'ci_based');
    const sensitivity = el('sensitivitySummary');
    if (sensitivity) {
        const ciUpperSens = Number(ciMethod?.ni_result?.ci_upper ?? metricData.ni_result?.ci_upper ?? NaN);
        const pMin = 0.5;
        const pMax = 0.95;
        const dAtMin = getCiLowerForCurrentDecision(data) * (1 - pMin);
        const dAtMax = getCiLowerForCurrentDecision(data) * (1 - pMax);
        sensitivity.textContent = `Heatmap colors show NI pass/fail as preservation fraction p changes from ${pMin} to ${pMax}. Green means pass, red means fail. For CI-based NI, CI upper is ${fmtNum(ciUpperSens, 6)}; margin moves from ${fmtNum(dAtMin, 6)} (p=${pMin}) to ${fmtNum(dAtMax, 6)} (p=${pMax}).`;
    }
}

function renderTreatmentBaselineDescriptivePlot(data, methodResult, fallbackResult) {
    if (!plotlyAvailable('plot', 'primarySummary', 'Descriptive effect plot unavailable because the chart library did not load.')) return;

    const metricData = getActiveMetricResult(data);
    const metricLabel = getActiveMetricLabel(data);
    const primaryResult = metricData.methods?.ci_based?.ni_result || fallbackResult || methodResult;
    const diff = finiteNumber(primaryResult.point_estimate_diff ?? primaryResult.difference_worse_than_baseline ?? methodResult.point_estimate_diff);
    const ciLower = finiteNumber(primaryResult.ci_lower ?? methodResult.ci_lower);
    const ciUpper = finiteNumber(primaryResult.ci_upper ?? methodResult.ci_upper);
    const bootstrap = primaryResult.bootstrap_ci || methodResult.bootstrap_ci || fallbackResult.bootstrap_ci;

    setText('primaryPlotTitle', 'Descriptive effect plot');

    if (!Number.isFinite(diff) || !Number.isFinite(ciLower) || !Number.isFinite(ciUpper)) {
        Plotly.purge('plot');
        setText('primarySummary', 'Descriptive treatment-vs-baseline plot unavailable because the effect estimate or confidence interval is missing.');
        return;
    }

    const traces = [
        {
            x: [diff],
            y: ['95% CI'],
            mode: 'markers',
            type: 'scatter',
            name: 'Point estimate',
            marker: {
                color: '#2454d6',
                size: 13,
                line: { color: '#173ea6', width: 2 }
            },
            error_x: {
                type: 'data',
                symmetric: false,
                array: [Math.max(0, ciUpper - diff)],
                arrayminus: [Math.max(0, diff - ciLower)],
                color: '#2454d6',
                thickness: 3,
                width: 0
            },
            hovertemplate: 'Effect: %{x:.6f}<br>95% CI: [' + ciLower.toFixed(6) + ', ' + ciUpper.toFixed(6) + ']<extra></extra>'
        }
    ];

    const rangeValues = [diff, ciLower, ciUpper, 0];
    if (bootstrap && Number.isFinite(finiteNumber(bootstrap.lower)) && Number.isFinite(finiteNumber(bootstrap.upper))) {
        const bLower = finiteNumber(bootstrap.lower);
        const bUpper = finiteNumber(bootstrap.upper);
        const bMid = finiteNumber((bLower + bUpper) / 2);
        rangeValues.push(bLower, bUpper);
        traces.push({
            x: [bLower, bUpper],
            y: ['Bootstrap 95% CI', 'Bootstrap 95% CI'],
            mode: 'lines',
            type: 'scatter',
            name: 'Bootstrap interval',
            line: { color: '#0f766e', width: 4 },
            hovertemplate: 'Bootstrap CI: %{x:.6f}<extra></extra>'
        });
        traces.push({
            x: [bMid],
            y: ['Bootstrap 95% CI'],
            mode: 'markers',
            type: 'scatter',
            name: 'Bootstrap midpoint',
            marker: { color: '#0f766e', size: 8 },
            hovertemplate: 'Bootstrap midpoint: %{x:.6f}<extra></extra>'
        });
    }

    const layout = {
        title: 'Treatment vs Baseline Effect (Descriptive Only)',
        xaxis: { title: `Worsening effect (${metricLabel})`, range: paddedRange(rangeValues), zeroline: false },
        yaxis: { title: '', showticklabels: true, range: [-0.7, traces.length > 1 ? 1.4 : 0.7] },
        shapes: [
            {
                type: 'line',
                x0: 0,
                x1: 0,
                y0: -0.7,
                y1: traces.length > 1 ? 1.4 : 0.7,
                line: { color: '#495057', width: 2 }
            }
        ],
        annotations: [
            {
                x: 0,
                y: traces.length > 1 ? 1.2 : 0.5,
                xref: 'x',
                yref: 'y',
                text: 'No difference (0)',
                showarrow: false,
                font: { color: '#495057', size: 12 }
            },
            {
                x: diff,
                y: -0.52,
                xref: 'x',
                yref: 'y',
                text: 'Fixed-margin NI not assessable; plot shown for descriptive interpretation only.',
                showarrow: true,
                arrowhead: 2,
                ax: 40,
                ay: 35,
                font: { color: '#b45309', size: 11 }
            }
        ],
        showlegend: traces.length > 1,
        margin: { t: 70, r: 20, b: 60, l: 70 },
        plot_bgcolor: '#ffffff',
        paper_bgcolor: '#ffffff'
    };

    Plotly.newPlot('plot', traces, layout, { responsive: true });
    setText('primarySummary', 'This scenario does not support a formal fixed-margin NI conclusion because the active control does not demonstrate benefit over placebo.');
}

function renderResults(data) {
    const metricData = getActiveMetricResult(data);
    const metricLabel = getActiveMetricLabel(data);
    const orientationText = formatOrientation(getActiveMetricOrientation(data));
    const methodData = getMethodData(data, selectedMethod);
    const methodResult = methodData.ni_result || metricData.ni_result;
    const fallbackResult = metricData.ni_result;

    updateNiWarning(data);

    el('m1Value').textContent = fmtNullable(methodData.M1, 6);
    if (methodData.M1_CI && methodData.M1_CI.lower !== undefined) {
        el('m1CiValue').textContent = `[${fmtNullable(methodData.M1_CI.lower, 6)}, ${fmtNullable(methodData.M1_CI.upper, 6)}]`;
    } else {
        el('m1CiValue').textContent = 'N/A';
    }

    el('dniValue').textContent = fmtNullable(methodData.d_NI, 6, 'Not defined');

    const ciUpperDisplay = methodResult.ci_upper ?? methodResult.posterior?.ci95_upper ?? fallbackResult.ci_upper;
    el('ciValue').textContent = fmtNullable(ciUpperDisplay, 6);
    el('baselineValue').textContent = fmtNullable(methodResult.baseline_mean ?? fallbackResult.baseline_mean, 6);
    el('treatmentValue').textContent = fmtNullable(methodResult.treatment_mean ?? fallbackResult.treatment_mean, 6);

    if (methodResult.probability_non_inferior !== undefined && methodResult.probability_non_inferior !== null) {
        el('posteriorProbValue').textContent = methodResult.probability_non_inferior.toFixed(4);
    } else {
        el('posteriorProbValue').textContent = 'N/A';
    }

    const verdict = (methodResult.verdict || fallbackResult.verdict).toLowerCase();
    const v = el('verdict');
    v.textContent = `Verdict: ${verdictForDisplay(verdict)}`;
    const verdictClass = isNotAssessable(verdict) ? 'not-assessable' : (verdict === 'equivalent' ? 'non-inferior' : (verdict === 'not-equivalent' ? 'inferior' : verdict));
    v.className = 'verdict ' + verdictClass;

    el('methodIndicator').textContent = `Selected margin: ${methodData.label}`;

    el('results').classList.add('show');
    el('rawJson').textContent = JSON.stringify(data, null, 2);

    const portfolioText = el('portfolioText');
    if (portfolioText) {
        if (data.portfolio) {
            const status = String(data.portfolio.status || 'unknown').toUpperCase();
            const assessment = String(data.portfolio.assessment_status || 'assessable').replace(/_/g, ' ');
            const score = Number(data.portfolio.score ?? NaN);
            const threshold = Number(data.portfolio.threshold ?? NaN);
            const mode = data.portfolio.decision_mode || 'strict';
            const na = data.portfolio.not_assessable_metrics?.length ? ` Not assessable metrics: ${data.portfolio.not_assessable_metrics.join(', ')}.` : '';
            portfolioText.textContent = `Portfolio status: ${status}. Assessment: ${assessment}. Mode: ${mode}. Score: ${fmtNum(score, 3)} (threshold ${fmtNum(threshold, 3)}). ${data.portfolio.summary || ''}${na}`;
        } else {
            portfolioText.textContent = 'Single-metric run. Portfolio verdict not applicable.';
        }
    }

    const settingsText = el('settingsText');
    if (settingsText) {
        const settings = data.settings_used || {};
        let metricsList = metricLabel;
        if (settings.metric_labels && settings.metrics) {
            metricsList = settings.metrics.map((m) => settings.metric_labels[m] || m).join(', ');
        } else if (settings.metrics) {
            metricsList = settings.metrics.join(', ');
        }
        const mode = settings.decision_mode || 'strict';
        const bootstrapMode = settings.bootstrap_mode || 'iid';
        const orientationNote = orientationText ? ` Orientation: ${orientationText}.` : '';
        settingsText.textContent = `Metrics: ${metricsList}. Decision mode: ${mode}. Bootstrap: ${bootstrapMode}. Preservation fraction: ${fmtNum(settings.preservation_fraction, 2)}.${orientationNote}`;
    }

    const preprocessText = el('preprocessText');
    if (preprocessText) {
        const summary = data.preprocess_summary || {};
        if (data.metric_results) {
            const metricKey = getActiveMetricKey(data);
            const s = summary[metricKey] || {};
            preprocessText.textContent = `Metric ${metricLabel} (${metricKey}): placebo rows ${s.placebo?.rows_before || '-'} -> ${s.placebo?.rows_after || '-'}, baseline rows ${s.baseline?.rows_before || '-'} -> ${s.baseline?.rows_after || '-'}, treatment rows ${s.treatment?.rows_before || '-'} -> ${s.treatment?.rows_after || '-'}.`;
        } else {
            preprocessText.textContent = `Placebo rows ${summary.placebo?.rows_before || '-'} -> ${summary.placebo?.rows_after || '-'}, baseline rows ${summary.baseline?.rows_before || '-'} -> ${summary.baseline?.rows_after || '-'}, treatment rows ${summary.treatment?.rows_before || '-'} -> ${summary.treatment?.rows_after || '-'}.`;
        }
    }

    // Forest-style NI effect plot (clinical-trial style)
    // x-axis: worsening effect, with vertical lines at 0 and d_NI
    const diff = methodResult.point_estimate_diff ?? methodResult.difference_worse_than_baseline ?? fallbackResult.point_estimate_diff;
    const ci_lower = methodResult.ci_lower ?? methodResult.posterior?.ci95_lower ?? fallbackResult.ci_lower;
    const ci_upper = methodResult.ci_upper ?? methodResult.posterior?.ci95_upper ?? fallbackResult.ci_upper;
    const dniRaw = methodData.d_NI;
    const dni = dniRaw === null || dniRaw === undefined ? NaN : Number(dniRaw);
    const formalNiPlotAvailable = metricData.ni_applicable === true && Number.isFinite(dni);

    if (!formalNiPlotAvailable) {
        renderTreatmentBaselineDescriptivePlot(data, methodResult, fallbackResult);
        renderRawDataPlot(data);
        renderMethodComparisonPlot(data);
        renderPosteriorPlot(data);
        renderSensitivityHeatmap(data);
        renderMethodAgreement(data);
        updateStudySummary(data, methodData, methodResult, fallbackResult);
        updateChartSummaries(data, methodData, methodResult, fallbackResult);
        updateMiniKpis(data);
        return;
    }

    setText('primaryPlotTitle', 'Primary effect plot');

    const forestTrace = {
        x: [diff],
        y: ['Effect estimate'],
        mode: 'markers',
        type: 'scatter',
        name: 'Point estimate',
        marker: {
            color: '#6f42c1',
            size: 13,
            line: { color: '#3b2a80', width: 2 }
        },
        error_x: {
            type: 'data',
            symmetric: false,
            array: [Math.max(0, ci_upper - diff)],
            arrayminus: [Math.max(0, diff - ci_lower)],
            color: '#17a2b8',
            thickness: 3,
            width: 0
        },
        hovertemplate: 'Effect: %{x:.6f}<br>95% CI: [' + Number(ci_lower).toFixed(6) + ', ' + Number(ci_upper).toFixed(6) + ']<extra></extra>'
    };

    const xMin = Math.min(ci_lower, 0, dni) - Math.max(0.05, Math.abs(ci_upper - ci_lower) * 0.2);
    const xMax = Math.max(ci_upper, 0, dni) + Math.max(0.05, Math.abs(ci_upper - ci_lower) * 0.2);

    const marginBandWidth = Math.max((xMax - xMin) * 0.015, 0.001);
    const shapes = [
        {
            type: 'rect',
            x0: xMin,
            x1: dni,
            y0: -0.5,
            y1: 0.5,
            fillcolor: 'rgba(40, 167, 69, 0.10)',
            line: { width: 0 },
            layer: 'below'
        },
        {
            type: 'rect',
            x0: dni,
            x1: xMax,
            y0: -0.5,
            y1: 0.5,
            fillcolor: 'rgba(220, 53, 69, 0.10)',
            line: { width: 0 },
            layer: 'below'
        },
        {
            type: 'rect',
            x0: dni - marginBandWidth,
            x1: dni + marginBandWidth,
            y0: -0.5,
            y1: 0.5,
            fillcolor: 'rgba(255, 127, 14, 0.18)',
            line: { width: 0 },
            layer: 'below'
        },
        {
            type: 'line',
            x0: 0,
            x1: 0,
            y0: -0.5,
            y1: 0.5,
            line: { color: '#495057', width: 2 }
        },
        {
            type: 'line',
            x0: dni,
            x1: dni,
            y0: -0.5,
            y1: 0.5,
            line: { color: '#ff7f0e', width: 3, dash: 'dash' }
        }
    ];

    if (selectedMethod === 'equivalence') {
        shapes.push({
            type: 'line',
            x0: -Math.abs(dni),
            x1: -Math.abs(dni),
            y0: -0.5,
            y1: 0.5,
            line: { color: '#2ca02c', width: 2, dash: 'dot' }
        });
    }

    const annotations = [
        {
            x: 0,
            y: 0.42,
            xref: 'x',
            yref: 'y',
            text: 'No difference (0)',
            showarrow: false,
            font: { color: '#495057', size: 12 }
        },
        {
            x: (xMin + dni) / 2,
            y: -0.32,
            xref: 'x',
            yref: 'y',
            text: 'ACCEPTABLE',
            showarrow: false,
            font: { color: '#1f7a35', size: 11 }
        },
        {
            x: (dni + xMax) / 2,
            y: -0.32,
            xref: 'x',
            yref: 'y',
            text: 'FAILURE',
            showarrow: false,
            font: { color: '#b4232d', size: 11 }
        },
        {
            x: dni,
            y: -0.42,
            xref: 'x',
            yref: 'y',
            text: `NI margin Delta = ${dni.toFixed(6)}`,
            showarrow: false,
            font: { color: '#ff7f0e', size: 12 }
        },
        {
            x: ci_upper,
            y: 0.2,
            xref: 'x',
            yref: 'y',
            text: `CI upper = ${Number(ci_upper).toFixed(6)}`,
            showarrow: true,
            arrowhead: 2,
            ax: 40,
            ay: -30,
            font: { color: '#17a2b8', size: 11 }
        }
    ];

    const layout = {
        title: `${methodData.label} - Forest-style Effect Plot`,
        xaxis: { title: `Worsening effect (${metricLabel})`, range: [xMin, xMax], zeroline: false },
        yaxis: { title: '', showticklabels: false, range: [-0.5, 0.5] },
        shapes,
        annotations,
        showlegend: false,
        margin: { t: 70, r: 20, b: 60, l: 40 },
        plot_bgcolor: '#ffffff',
        paper_bgcolor: '#ffffff'
    };

    if (plotlyAvailable('plot', 'primarySummary', 'Primary effect plot unavailable because the chart library did not load.')) {
        Plotly.newPlot('plot', [forestTrace], layout, { responsive: true });
    }
    renderRawDataPlot(data);
    renderMethodComparisonPlot(data);
    renderPosteriorPlot(data);
    renderSensitivityHeatmap(data);
    renderMethodAgreement(data);
    updateStudySummary(data, methodData, methodResult, fallbackResult);
    updateChartSummaries(data, methodData, methodResult, fallbackResult);
    updateMiniKpis(data);
}

function setLoading(yes) {
    const btn = el('submitBtn');
    const spinner = el('spinner');
    const form = el('uploadForm');
    if (yes) {
        btn.disabled = true;
        btn.textContent = 'Evaluating...';
    } else {
        btn.disabled = false;
        btn.textContent = 'Evaluate';
    }
    if (form) form.setAttribute('aria-busy', yes ? 'true' : 'false');
    if (spinner) spinner.style.display = yes ? 'block' : 'none';
}

async function copyJSON() {
    const txt = el('rawJson').textContent;
    try {
        await navigator.clipboard.writeText(txt);
        const btn = el('copyBtn');
        if (!btn) return;
        const original = btn.textContent;
        btn.textContent = 'Copied';
        window.setTimeout(() => { btn.textContent = original; }, 1400);
    } catch (_) {
        const raw = el('rawJson');
        if (raw) raw.focus();
    }
}

function downloadJSON() {
    const txt = el('rawJson').textContent;
    const blob = new Blob([txt], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'ni_result.json';
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
}

window.addEventListener('DOMContentLoaded', () => {
    initThemeControls();

    if (!el('uploadForm')) return;

    ['placebo','baseline','treatment','combinedFile'].forEach(id => el(id)?.addEventListener('change', showFileNames));
    el('inputMode')?.addEventListener('change', updateInputModeUI);
    el('combinedFile')?.addEventListener('change', async () => {
        const f = el('combinedFile')?.files?.[0];
        if (!f) return;
        const cols = await tryExtractColumnsFromFile(f);
        if (cols.length) populateColumnDropdowns(cols);
    });
    el('combinedHasHeader')?.addEventListener('change', async () => {
        const f = el('combinedFile')?.files?.[0];
        if (!f) return;
        const cols = await tryExtractColumnsFromFile(f);
        if (cols.length) populateColumnDropdowns(cols);
    });
    el('copyBtn')?.addEventListener('click', copyJSON);
    el('downloadBtn')?.addEventListener('click', downloadJSON);
    el('reportBtn')?.addEventListener('click', downloadStudyReport);
    el('packageBtn')?.addEventListener('click', downloadRunPackage);
    el('preservationSlider')?.addEventListener('input', syncSliderDisplay);
    ['togglePlacebo', 'toggleBaseline', 'toggleTreatment'].forEach((id) => {
        el(id)?.addEventListener('change', () => {
            if (lastResponse) renderRawDataPlot(lastResponse);
        });
    });
    el('applySliderBtn')?.addEventListener('click', async () => {
        if (!hasRequiredInputsForCurrentMode()) {
            el('error').textContent = 'Error: Please complete required inputs for the selected mode before re-evaluating.';
            el('error').classList.add('show');
            return;
        }
        await evaluateCurrentForm();
    });

    document.querySelectorAll('.margin-card').forEach(card => {
        card.addEventListener('click', () => {
            const method = card.dataset.method;
            if (!method) return;
            selectedMethod = method;
            document.querySelectorAll('.margin-card').forEach((c) => {
                c.classList.remove('selected');
                c.setAttribute('aria-pressed', 'false');
            });
            card.classList.add('selected');
            card.setAttribute('aria-pressed', 'true');
            if (lastResponse) {
                renderResults(lastResponse);
            }
        });
    });

    el('uploadForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        await evaluateCurrentForm();
    });

    // initialize filenames
    showFileNames();
    updateInputModeUI();
    syncSliderDisplay();
});
