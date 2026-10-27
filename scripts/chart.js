/* ForestScope charts
   Uses `combinedResultsById` (declared in script.js) and Chart.js.
   Load order in index.html: chart.js CDN -> script.js -> charts.js */

/* ---------- Categories & colours ---------- */
const FORTY_CLASSES = [
  { key: 'PrimaryForest',               label: 'Primary forest',            color: '#1B7837' },
  { key: 'NaturallyRegeneratingForest', label: 'Naturally regenerating',    color: '#7FBF7B' },
  { key: 'PlantedForest',               label: 'Planted forest',            color: '#1D91C0' },
  { key: 'PlantationForest',            label: 'Plantation forest',         color: '#E65FA9' },
  { key: 'TreeCropsAndAgroforestry',    label: 'Tree crops & agroforestry', color: '#E6AB02' }
];
const FORTY_OTHER = { label: 'Other land (estimated)', color: '#FDE278' };
const FORTY_NONE  = { label: 'No ForTy data',          color: '#9aa5a0' };

const FORTY_ORDER = [...FORTY_CLASSES.map(c => c.label), FORTY_OTHER.label, FORTY_NONE.label];
const FORTY_COLORS = Object.fromEntries(
  [...FORTY_CLASSES, FORTY_OTHER, FORTY_NONE].map(c => [c.label, c.color])
);

const JRC_ORDER = ['No forest (0%)', 'Partial forest (1–99%)', 'Full forest (100%)'];
const JRC_COLORS = {
  'No forest (0%)': '#9aa5a0',
  'Partial forest (1–99%)': '#c8a951',
  'Full forest (100%)': '#2f6f4e'
};

/* ---------- Classify one saved result ---------- */
// JRC only stores forest pixels (non-forest is masked), so the forest share of the
// polygon is the meaningful number. Use it, not the pixel count.
function jrcCategory(record) {
  const pct = record.jrc?.forest_percentage;
  if (pct == null || pct <= 0) return JRC_ORDER[0];
  if (pct >= 100) return JRC_ORDER[2];
  return JRC_ORDER[1];
}

// Same rule as the ForTy map layer: sixth class = 250 - sum of the five bands
function fortyDominant(record) {
  const values = record.forty?.values;
  if (!values) return FORTY_NONE.label;

  const entries = FORTY_CLASSES.map(c => [c.label, Number(values[c.key]) || 0]);
  const sum = entries.reduce((total, [, v]) => total + v, 0);
  entries.push([FORTY_OTHER.label, Math.max(0, 250 - sum)]);

  return entries.reduce((best, cur) => (cur[1] > best[1] ? cur : best))[0];
}

function countBy(records, fn, order) {
  const counts = Object.fromEntries(order.map(k => [k, 0]));
  records.forEach(r => { counts[fn(r)] += 1; });
  return counts;
}

/* ---------- Chart builders (return Chart.js configs) ---------- */
function buildJrcStatus(records) {
  const counts = countBy(records, jrcCategory, JRC_ORDER);
  const total = records.length;

  return {
    type: 'doughnut',
    data: {
      labels: JRC_ORDER,
      datasets: [{
        data: JRC_ORDER.map(k => counts[k]),
        backgroundColor: JRC_ORDER.map(k => JRC_COLORS[k]),
        borderColor: '#ffffff',
        borderWidth: 2
      }]
    },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'bottom' },
        tooltip: {
          callbacks: {
            label: ctx =>
              ` ${ctx.label}: ${ctx.parsed} polygons (${(ctx.parsed / total * 100).toFixed(1)}%)`
          }
        }
      }
    }
  };
}

function buildJrcShare(records) {
  const bins = [
    ['0%', 0, 0], ['1–25%', 0.0001, 25], ['26–50%', 25.0001, 50],
    ['51–75%', 50.0001, 75], ['76–99%', 75.0001, 99.9999], ['100%', 100, 100]
  ];
  const data = bins.map(([, lo, hi]) =>
    records.filter(r => {
      const p = r.jrc?.forest_percentage ?? 0;
      return p >= lo && p <= hi;
    }).length
  );

  return {
    type: 'bar',
    data: {
      labels: bins.map(b => b[0]),
      datasets: [{
        data,
        backgroundColor: ['#9aa5a0', '#e0c46c', '#b9c97a', '#8fbf9f', '#4f9a70', '#1d4733'],
        borderRadius: 6
      }]
    },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { title: { display: true, text: 'Share of the polygon covered by JRC forest' } },
        y: { beginAtZero: true, ticks: { precision: 0 }, title: { display: true, text: 'Polygons' } }
      }
    }
  };
}

function buildFortyDominant(records) {
  const counts = countBy(records, fortyDominant, FORTY_ORDER);

  return {
    type: 'bar',
    data: {
      labels: FORTY_ORDER,
      datasets: [{
        data: FORTY_ORDER.map(k => counts[k]),
        backgroundColor: FORTY_ORDER.map(k => FORTY_COLORS[k]),
        borderRadius: 6
      }]
    },
    options: {
      indexAxis: 'y',
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { beginAtZero: true, ticks: { precision: 0 }, title: { display: true, text: 'Polygons' } }
      }
    }
  };
}

function buildComparison(records) {
  // rows = ForTy dominant class, stacks = what JRC says for the same polygons
  const table = Object.fromEntries(
    FORTY_ORDER.map(f => [f, Object.fromEntries(JRC_ORDER.map(j => [j, 0]))])
  );
  records.forEach(r => { table[fortyDominant(r)][jrcCategory(r)] += 1; });

  const labels = FORTY_ORDER.filter(f => JRC_ORDER.some(j => table[f][j] > 0));

  return {
    type: 'bar',
    data: {
      labels,
      datasets: JRC_ORDER.map(j => ({
        label: 'JRC: ' + j,
        data: labels.map(f => table[f][j]),
        backgroundColor: JRC_COLORS[j]
      }))
    },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { position: 'bottom' } },
      scales: {
        x: { stacked: true, title: { display: true, text: 'ForTy dominant class' } },
        y: { stacked: true, beginAtZero: true, ticks: { precision: 0 }, title: { display: true, text: 'Polygons' } }
      }
    }
  };
}

// 100% stacked bars: one bar per group, one colour per category.
// Records carry `region` and `area_m2` (added in script.js after the results load).
function percentStacked(records, groupOf, groupOrder, catOf, catOrder, colors, xTitle) {
  const groups = groupOrder.filter(g => records.some(r => groupOf(r) === g));
  const counts = {};
  groups.forEach(g => { counts[g] = Object.fromEntries(catOrder.map(k => [k, 0])); });
  records.forEach(r => {
    const g = groupOf(r);
    if (counts[g]) counts[g][catOf(r)] += 1;
  });
  const totals = Object.fromEntries(
    groups.map(g => [g, Object.values(counts[g]).reduce((a, b) => a + b, 0)])
  );

  return {
    type: 'bar',
    data: {
      labels: groups.map(g => `${g} (n=${totals[g]})`),
      datasets: catOrder.map(k => ({
        label: k,
        backgroundColor: colors[k],
        data: groups.map(g => 100 * counts[g][k] / totals[g]),
        counts: groups.map(g => counts[g][k])
      }))
    },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'bottom' },
        tooltip: {
          callbacks: {
            label: ctx =>
              ` ${ctx.dataset.label}: ${ctx.parsed.y.toFixed(0)}% (${ctx.dataset.counts[ctx.dataIndex]} polygons)`
          }
        }
      },
      scales: {
        x: { stacked: true, title: { display: true, text: xTitle } },
        y: { stacked: true, min: 0, max: 100, title: { display: true, text: '% of polygons' } }
      }
    }
  };
}

const REGION_ORDER = ['Brazil', 'Uganda'];
const SIZE_BINS = [
  ['<100 m²', 0, 100], ['100–400 m²', 100, 400], ['400–1,000 m²', 400, 1000],
  ['1,000–4,000 m²', 1000, 4000], ['>4,000 m²', 4000, Infinity]
];
const sizeBinOf = r => {
  const a = r.area_m2 ?? 0;
  const bin = SIZE_BINS.find(([, lo, hi]) => a >= lo && a < hi);
  return bin ? bin[0] : SIZE_BINS[0][0];
};

function buildJrcByRegion(records) {
  return percentStacked(records, r => r.region, REGION_ORDER, jrcCategory, JRC_ORDER, JRC_COLORS, 'Region');
}

function buildJrcBySize(records) {
  return percentStacked(records, sizeBinOf, SIZE_BINS.map(b => b[0]), jrcCategory, JRC_ORDER, JRC_COLORS,
    'Polygon area (one JRC/ForTy pixel = 100 m²)');
}

function buildFortyByRegion(records) {
  return percentStacked(records, r => r.region, REGION_ORDER, fortyDominant, FORTY_ORDER, FORTY_COLORS, 'Region');
}

/* ---------- Which charts belong to which sidebar section ---------- */
const CHART_TITLES = {
  'Forest Cover': 'JRC Forest Cover 2020',
  'Change Analysis': 'ForTy Forest Typology 2020'
};

const CHART_SETS = {
  'Forest Cover': [
    {
      tab: 'Status',
      build: buildJrcStatus,
      note: 'Polygons mark confirmed deforestation after 2020, so forest is expected. JRC stores only ' +
            'forest pixels (non-forest is masked), so 0% means JRC maps no forest inside the polygon.'
    },
    {
      tab: 'Forest share',
      build: buildJrcShare,
      note: 'Share of each polygon covered by JRC forest pixels at 10 m. If JRC matched the confirmed ' +
            'forest, every polygon would be near 100%.'
    },
    {
      tab: 'By region',
      build: buildJrcByRegion,
      note: 'The same three JRC groups for each region. Regions are derived from polygon location ' +
            '(two separate clusters), so differences may also reflect polygon size and year.'
    },
    {
      tab: 'By size',
      build: buildJrcBySize,
      note: 'Robustness check: does JRC miss mainly the tiniest polygons? Compare the bars. A polygon ' +
            'smaller than 100 m² is smaller than one pixel.'
    }
  ],
  'Change Analysis': [
    {
      tab: 'Dominant class',
      build: buildFortyDominant,
      note: 'Dominant class = highest of the five ForTy bands. “Other land” is estimated as 250 minus ' +
            'their sum, the same rule used for the map layer.'
    },
    {
      tab: 'By region',
      build: buildFortyByRegion,
      note: 'ForTy dominant class for each region. Plantation forest and most tree crops / agroforestry ' +
            'polygons occur in one region only.'
    },
    {
      tab: 'JRC vs ForTy',
      build: buildComparison,
      note: 'Each bar is a ForTy dominant class; the colours show what JRC says about the same polygons. ' +
            'Forest in one dataset but non-forest or no data in the other shows where they disagree.'
    }
  ]
};

/* ---------- Rendering ---------- */
let activeChart = null;
let chartDefaultsSet = false;

function drawChart(set, records) {
  const canvas = document.getElementById('chart-canvas');
  const note = document.getElementById('chart-note');

  // Make sure the chart area always has a height, even if the CSS is missing
  canvas.parentElement.style.position = 'relative';
  canvas.parentElement.style.height = '300px';

  if (activeChart) {
    activeChart.destroy();
    activeChart = null;
  }

  try {
    activeChart = new Chart(canvas, set.build(records));
    note.textContent = `${set.note} (n = ${records.length} polygons)`;
  } catch (error) {
    console.error('Chart error:', error);
    note.textContent = 'Chart error: ' + error.message;
  }
}

function showChart(section) {
  const sets = CHART_SETS[section];
  const panel = document.getElementById('chart-panel');
  const title = document.getElementById('chart-title');
  const tabs = document.getElementById('chart-tabs');
  const note = document.getElementById('chart-note');
  if (!sets || !panel) return;

  title.textContent = CHART_TITLES[section] || section;
  tabs.replaceChildren();
  panel.hidden = false;

  if (activeChart) {
    activeChart.destroy();
    activeChart = null;
  }

  if (typeof Chart === 'undefined') {
    note.textContent = 'Chart.js did not load. Check the script tag and your internet connection.';
    return;
  }

  const records = Object.values(combinedResultsById);
  console.log('Charts: loaded results =', records.length);
  if (!records.length) {
    note.textContent = 'Saved results are not loaded yet. Run /api/analyze-combined-all, then refresh.';
    return;
  }

  if (!chartDefaultsSet) {
    Chart.defaults.font.family = '"Segoe UI", "Open Sans", system-ui, sans-serif';
    Chart.defaults.color = '#1d4733';
    chartDefaultsSet = true;
  }

  sets.forEach((set, index) => {
    const tab = document.createElement('button');
    tab.type = 'button';
    tab.className = 'chart-tab' + (index === 0 ? ' active' : '');
    tab.textContent = set.tab;
    tab.addEventListener('click', () => {
      tabs.querySelectorAll('.chart-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      drawChart(set, records);
    });
    tabs.appendChild(tab);
  });

  drawChart(sets[0], records);
}

const chartCloseBtn = document.getElementById('chart-close');
if (chartCloseBtn) {
  chartCloseBtn.addEventListener('click', () => {
    document.getElementById('chart-panel').hidden = true;
  });
}
