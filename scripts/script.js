mapboxgl.accessToken = (window.FORESTSCOPE_CONFIG || {}).mapboxToken || '';

const API = location.protocol === 'file:' ? 'http://127.0.0.1:5000' : '';
// Create Map
const map = new mapboxgl.Map({
  container: 'map',
  style: 'mapbox://styles/mapbox/dark-v11',
  center: [8.2, 48.0],   // [longitude, latitude]
  zoom: 3
});

map.addControl(new mapboxgl.NavigationControl(), 'top-right');

// ========================================
// MAP STYLE SWITCHER
// ========================================

const styleButton = document.getElementById('map-style-button');
const styleMenu = document.getElementById('map-style-menu');

if (styleButton && styleMenu) {
  // Open / close style menu
  styleButton.addEventListener('click', function () {
    if (styleMenu.style.display === 'block') {
      styleMenu.style.display = 'none';
    } else {
      styleMenu.style.display = 'block';
    }
  });

  // Change map style
  const styleInputs = document.querySelectorAll(
    '#map-style-menu input[name="map-style"]'
  );

  styleInputs.forEach(function (input) {
    input.addEventListener('change', function () {
      const selectedStyle = this.value;

      // Layers are re-added automatically on the 'style.load' event below
      map.setStyle('mapbox://styles/mapbox/' + selectedStyle);

      // Close menu after selection
      styleMenu.style.display = 'none';
    });
  });
}

/* ---------- State ---------- */
const POLYGON_LAYERS = ['forest-polygon-fill', 'forest-polygon-line'];

let polygonsLoaded = false;
let polygonGeoJSON = null;
let combinedResultsById = {};
let selectedPolygonId = null;
let polygonPopup = null;

// Remembered so they can be put back after the base map style changes
let completeLayerVisible = false;     // "Complete Polygon Layer" on/off
const rasterState = {};               // layerId -> { sourceId, tileUrl, visible }

/* ---------- Dataset agreement map ---------- */
// Okabe-Ito colours (readable with common colour-vision differences)
const AGREEMENT_CLASSES = [
  { id: 'both',       label: 'Both show forest',                color: '#009E73' },
  { id: 'forty_only', label: 'ForTy only (JRC has no forest)',  color: '#E69F00' },
  { id: 'jrc_only',   label: 'JRC only (ForTy: other land)',    color: '#56B4E9' },
  { id: 'neither',    label: 'Neither shows forest',            color: '#CC79A7' }
];

const FORTY_BAND_KEYS = [
  'PrimaryForest', 'NaturallyRegeneratingForest', 'PlantedForest',
  'PlantationForest', 'TreeCropsAndAgroforestry'
];

let agreementGeoJSON = null;
let agreementVisible = false;
const agreementActive = Object.fromEntries(AGREEMENT_CLASSES.map(c => [c.id, true]));

// Geographic grouping: the 198 polygons form two far-apart clusters
// (south-east Brazil, about 16-23 deg S; Uganda, about 0.7 deg S to 0.6 deg N).
const REGIONS = ['Brazil', 'Uganda'];
const regionActive = Object.fromEntries(REGIONS.map(r => [r, true]));

function regionOf(feature) {
  const center = boundsOf([feature]).getCenter();
  return center.lat < -10 ? 'Brazil' : 'Uganda';
}

// Polygon area in m2. A local flat projection on the WGS84 ellipsoid is accurate for
// polygons this small (it matches PostGIS ST_Area(geography) to well under 1%).
function ringAreaM2(ring) {
  const a = 6378137;
  const e2 = 0.00669437999014;
  const rad = Math.PI / 180;
  const lat0 = (ring.reduce((sum, p) => sum + p[1], 0) / ring.length) * rad;
  const w = 1 - e2 * Math.sin(lat0) ** 2;
  const metresPerDegLat = (a * (1 - e2)) / Math.pow(w, 1.5) * rad;
  const metresPerDegLon = (a / Math.sqrt(w)) * Math.cos(lat0) * rad;

  const [lon0, latRef] = ring[0];
  const pts = ring.map(p => [(p[0] - lon0) * metresPerDegLon, (p[1] - latRef) * metresPerDegLat]);

  let twice = 0;
  for (let i = 0; i < pts.length; i++) {
    const [x1, y1] = pts[i];
    const [x2, y2] = pts[(i + 1) % pts.length];
    twice += x1 * y2 - x2 * y1;
  }
  return Math.abs(twice) / 2;
}

function geometryAreaM2(geometry) {
  const polygons = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates;
  let total = 0;
  polygons.forEach(rings => rings.forEach((ring, i) => {
    total += i === 0 ? ringAreaM2(ring) : -ringAreaM2(ring);   // later rings are holes
  }));
  return total;
}

// Attach region and area to each saved result (used by the popup and the charts)
function enrichResults() {
  if (!polygonGeoJSON) return;
  polygonGeoJSON.features.forEach(feature => {
    const record = combinedResultsById[feature.properties?.polygon_id];
    if (!record) return;
    record.region = regionOf(feature);
    record.area_m2 = geometryAreaM2(feature.geometry);
  });
}

// Same rule as the charts: ForTy "forest type" = one of the five bands is the highest;
// "other land" is estimated as 250 minus their sum.
function fortyHasForestType(record) {
  const values = record.forty?.values;
  if (!values) return false;
  const scores = FORTY_BAND_KEYS.map(key => Number(values[key]) || 0);
  const other = Math.max(0, 250 - scores.reduce((a, b) => a + b, 0));
  return Math.max(...scores) >= other;
}

// JRC "has forest" = any forest share inside the polygon
function agreementClass(record) {
  const jrcForest = (record.jrc?.forest_percentage ?? 0) > 0;
  const fortyForest = fortyHasForestType(record);
  if (jrcForest && fortyForest) return 'both';
  if (fortyForest) return 'forty_only';
  if (jrcForest) return 'jrc_only';
  return 'neither';
}

function agreementLabel(record) {
  return AGREEMENT_CLASSES.find(c => c.id === agreementClass(record)).label;
}

function agreementFilter() {
  const classes = AGREEMENT_CLASSES.filter(c => agreementActive[c.id]).map(c => c.id);
  const regions = REGIONS.filter(r => regionActive[r]);

  if (!classes.length || !regions.length) {
    return ['==', ['get', 'agreement'], '__none__'];
  }
  return ['all',
    ['in', ['get', 'agreement'], ['literal', classes]],
    ['in', ['get', 'region'], ['literal', regions]]
  ];
}

// One dot per polygon: polygons are far too small to see at low zoom
function buildAgreementData() {
  if (!polygonGeoJSON) return;

  const features = [];
  polygonGeoJSON.features.forEach(feature => {
    const id = feature.properties?.polygon_id;
    const result = combinedResultsById[id];
    if (id === undefined || !result) return;

    const center = boundsOf([feature]).getCenter();
    features.push({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [center.lng, center.lat] },
      properties: {
        polygon_id: id,
        agreement: agreementClass(result),
        region: result.region || regionOf(feature)
      }
    });
  });

  agreementGeoJSON = { type: 'FeatureCollection', features };
}

function addAgreementLayer() {
  if (!agreementGeoJSON || map.getSource('agreement-points')) return;

  map.addSource('agreement-points', { type: 'geojson', data: agreementGeoJSON });

  const colorMatch = ['match', ['get', 'agreement']];
  AGREEMENT_CLASSES.forEach(c => colorMatch.push(c.id, c.color));
  colorMatch.push('#999999');

  map.addLayer({
    id: 'agreement-points',
    type: 'circle',
    source: 'agreement-points',
    layout: { visibility: agreementVisible ? 'visible' : 'none' },
    filter: agreementFilter(),
    paint: {
      'circle-color': colorMatch,
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 2, 4, 8, 6, 14, 9],
      'circle-stroke-color': '#ffffff',
      'circle-stroke-width': 1.5,
      'circle-opacity': 0.9
    }
  });
}

function buildAgreementLegend() {
  const box = document.getElementById('agreement-items');
  if (!box || !agreementGeoJSON) return;

  const counts = {};
  agreementGeoJSON.features.forEach(f => {
    counts[f.properties.agreement] = (counts[f.properties.agreement] || 0) + 1;
  });
  const total = agreementGeoJSON.features.length || 1;

  box.replaceChildren();

  AGREEMENT_CLASSES.forEach(c => {
    const row = document.createElement('label');
    row.className = 'agreement-item';

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = agreementActive[c.id];
    checkbox.addEventListener('change', () => {
      agreementActive[c.id] = checkbox.checked;
      if (map.getLayer('agreement-points')) {
        map.setFilter('agreement-points', agreementFilter());
      }
    });

    const dot = document.createElement('span');
    dot.className = 'agreement-dot';
    dot.style.background = c.color;

    const text = document.createElement('span');
    text.className = 'agreement-text';
    text.textContent = c.label;

    const count = document.createElement('span');
    count.className = 'agreement-count';
    const n = counts[c.id] || 0;
    count.textContent = `${n} (${Math.round(n / total * 100)}%)`;

    row.append(checkbox, dot, text, count);
    box.appendChild(row);
  });

  // Region filter
  const heading = document.createElement('div');
  heading.className = 'agreement-subhead';
  heading.textContent = 'Region';
  box.appendChild(heading);

  const regionCounts = {};
  agreementGeoJSON.features.forEach(f => {
    regionCounts[f.properties.region] = (regionCounts[f.properties.region] || 0) + 1;
  });

  REGIONS.forEach(region => {
    const row = document.createElement('label');
    row.className = 'agreement-item';

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = regionActive[region];
    checkbox.addEventListener('change', () => {
      regionActive[region] = checkbox.checked;
      if (map.getLayer('agreement-points')) {
        map.setFilter('agreement-points', agreementFilter());
      }
    });

    const text = document.createElement('span');
    text.className = 'agreement-text';
    text.textContent = region;

    const count = document.createElement('span');
    count.className = 'agreement-count';
    count.textContent = String(regionCounts[region] || 0);

    row.append(checkbox, text, count);
    box.appendChild(row);
  });
}

/* ---------- Helpers ---------- */
function boundsOf(features) {
  const bounds = new mapboxgl.LngLatBounds();
  const add = coords =>
    typeof coords[0] === 'number' ? bounds.extend(coords) : coords.forEach(add);
  features.forEach(f => add(f.geometry.coordinates));
  return bounds;
}

function escapeHTML(value) {
  return String(value ?? 'No data available').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[char]);
}

function setSelected(id) {
  selectedPolygonId = id;
  const filter = ['==', ['get', 'polygon_id'], id ?? ''];
  ['selected-polygon-fill', 'selected-polygon-line'].forEach(layerId => {
    if (map.getLayer(layerId)) map.setFilter(layerId, filter);
  });
}

/* ---------- Layers that must survive a base map change ---------- */
function addPolygonLayers() {
  // Needs the data, and must not run twice
  if (!polygonGeoJSON || map.getSource('forest-polygon')) return;

  map.addSource('forest-polygon', { type: 'geojson', data: polygonGeoJSON });

  const visibility = completeLayerVisible ? 'visible' : 'none';
  const selectedFilter = ['==', ['get', 'polygon_id'], selectedPolygonId ?? ''];

  // Complete layer
  map.addLayer({
    id: 'forest-polygon-fill',
    type: 'fill',
    source: 'forest-polygon',
    layout: { visibility },
    paint: { 'fill-color': '#FF00FF', 'fill-opacity': 0.65 }
  });

  map.addLayer({
    id: 'forest-polygon-line',
    type: 'line',
    source: 'forest-polygon',
    layout: { visibility },
    paint: { 'line-color': '#ffe082', 'line-width': 2 }
  });

  // Highlight for the selected polygon
  map.addLayer({
    id: 'selected-polygon-fill',
    type: 'fill',
    source: 'forest-polygon',
    filter: selectedFilter,
    paint: { 'fill-color': '#00E676', 'fill-opacity': 0.45 }
  });

  map.addLayer({
    id: 'selected-polygon-line',
    type: 'line',
    source: 'forest-polygon',
    filter: selectedFilter,
    paint: { 'line-color': '#00E676', 'line-width': 4 }
  });
}

function restoreRasterLayers() {
  Object.entries(rasterState).forEach(([layerId, state]) => {
    if (map.getLayer(layerId)) return;

    if (!map.getSource(state.sourceId)) {
      map.addSource(state.sourceId, {
        type: 'raster',
        tiles: [state.tileUrl],
        tileSize: 256,
        maxzoom: 14
      });
    }

    map.addLayer(
      {
        id: layerId,
        type: 'raster',
        source: state.sourceId,
        layout: { visibility: state.visible ? 'visible' : 'none' },
        paint: { 'raster-opacity': 0.8 }
      },
      // Insert BELOW the polygons so the rasters never cover them
      map.getLayer('forest-polygon-fill') ? 'forest-polygon-fill' : undefined
    );
  });
}

// Fires after the first load AND after every map.setStyle(...)
map.on('style.load', () => {
  addPolygonLayers();
  addAgreementLayer();
  restoreRasterLayers();
});

/* ---------- Load polygons + saved results ---------- */
map.on('load', async () => {
  // 1) Polygons from PostGIS
  try {
    const response = await fetch(`${API}/api/polygons`);
    if (!response.ok) throw new Error(`Backend error: ${response.status}`);

    polygonGeoJSON = await response.json();

    // Standardize the ID so every polygon can be selected
    polygonGeoJSON.features.forEach(feature => {
      const props = feature.properties || {};
      const id = props.polygon_id ?? props.id;
      if (id !== undefined && id !== null) {
        feature.properties = { ...props, polygon_id: String(id) };
      }
    });

    addPolygonLayers();
    restoreRasterLayers();

    polygonsLoaded = true;
    createSubpolygonCheckboxes();   // only now do the polygons exist
    console.log(`Loaded ${polygonGeoJSON.features.length} polygons from PostGIS.`);

  } catch (error) {
    console.error('Could not load PostGIS polygons:', error);
    alert('Could not load the study area polygons. Check that Flask is running.');
  }

  // 2) Saved JRC + ForTy results (separate, so polygons still show if this fails)
  try {
    const resultsResponse = await fetch(`${API}/api/combined-results`);
    if (!resultsResponse.ok) throw new Error(`Backend error: ${resultsResponse.status}`);

    const resultsData = await resultsResponse.json();
    combinedResultsById = {};
    (resultsData.results || []).forEach(result => {
      combinedResultsById[String(result.polygon_id)] = result;
    });

    enrichResults();
    buildAgreementData();
    addAgreementLayer();
    buildAgreementLegend();
  } catch (error) {
    console.warn('Could not load combined results:', error);
  }
});

/* ---------- Subpolygon checkboxes ---------- */
function createSubpolygonCheckboxes() {
  const list = document.getElementById('subpolygon-list');
  if (!list || !polygonGeoJSON) return;

  list.replaceChildren();

  const features = polygonGeoJSON.features
    .filter(f => f.properties?.polygon_id !== undefined)
    .sort((a, b) =>
      a.properties.polygon_id.localeCompare(b.properties.polygon_id, undefined, { numeric: true })
    );

  features.forEach(feature => {
    const id = feature.properties.polygon_id;

    const label = document.createElement('label');
    label.className = 'polygon-option';

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'subpolygon-checkbox';
    checkbox.value = id;

    const text = document.createElement('span');
    text.textContent = `Polygon ${id}`;

    checkbox.addEventListener('change', () => {
      if (checkbox.checked) {
        // One polygon selected at a time
        list.querySelectorAll('.subpolygon-checkbox').forEach(other => {
          if (other !== checkbox) other.checked = false;
        });
        setSelected(id);
        flyToPolygon(feature);
      } else if (selectedPolygonId === id) {
        setSelected(null);
      }
    });

    label.append(checkbox, text);
    list.appendChild(label);
  });

  if (!features.length) {
    list.textContent = 'No polygon IDs found in the API response.';
  }
}

function flyToPolygon(feature) {
  const bounds = boundsOf([feature]);
  if (!bounds.isEmpty()) {
    map.fitBounds(bounds, { padding: 100, maxZoom: 16, duration: 1200 });
  }
}

/* ---------- Complete Polygon Layer button ---------- */
const showAllPolygonsBtn = document.getElementById('show-all-polygons-btn');

if (showAllPolygonsBtn) {
  showAllPolygonsBtn.addEventListener('click', () => {
    if (!polygonsLoaded) {
      alert('Polygons are still loading. Please wait.');
      return;
    }

    const turnOn = !completeLayerVisible;
    completeLayerVisible = turnOn;

    POLYGON_LAYERS.forEach(id => {
      if (map.getLayer(id)) {
        map.setLayoutProperty(id, 'visibility', turnOn ? 'visible' : 'none');
      }
    });

    showAllPolygonsBtn.textContent = turnOn
      ? 'Hide Complete Polygon Layer'
      : 'Complete Polygon Layer';

    if (turnOn && polygonGeoJSON.features.length) {
      const bounds = boundsOf(polygonGeoJSON.features);
      if (!bounds.isEmpty()) {
        map.fitBounds(bounds, { padding: 50, maxZoom: 5, duration: 1000 });
      }
    }
  });
}

/* ---------- Dataset Agreement Map button ---------- */
const agreementBtn = document.getElementById('agreement-btn');
const agreementLegend = document.getElementById('agreement-legend');

if (agreementBtn) {
  agreementBtn.addEventListener('click', () => {
    if (!polygonsLoaded || !agreementGeoJSON) {
      alert('The polygons or saved results are still loading. Please wait.');
      return;
    }

    agreementVisible = !agreementVisible;

    if (map.getLayer('agreement-points')) {
      map.setLayoutProperty('agreement-points', 'visibility', agreementVisible ? 'visible' : 'none');
    }
    agreementBtn.setAttribute('aria-pressed', agreementVisible);
    if (agreementLegend) agreementLegend.hidden = !agreementVisible;

    if (agreementVisible) {
      const bounds = boundsOf(polygonGeoJSON.features);
      if (!bounds.isEmpty()) {
        map.fitBounds(bounds, { padding: 60, maxZoom: 5, duration: 1000 });
      }
      // Close the side menu so the legend is visible
      const menu = document.getElementById('sidebar');
      const toggle = document.getElementById('menu-btn');
      if (menu) menu.classList.remove('open');
      if (toggle) toggle.setAttribute('aria-expanded', false);
    }
  });
}

/* ---------- Popup (click a polygon) ---------- */
function showPolygonPopup(feature, lngLat) {
  const id = String(feature.properties.polygon_id);
  const result = combinedResultsById[id];
  if (!result) return;

  const jrc = result.jrc || {};
  const forty = result.forty || {};
  const values = forty.values || {};

  const bands = [
    ['Primary forest', 'PrimaryForest'],
    ['Naturally regenerating forest', 'NaturallyRegeneratingForest'],
    ['Planted forest', 'PlantedForest'],
    ['Plantation forest', 'PlantationForest'],
    ['Tree crops and agroforestry', 'TreeCropsAndAgroforestry']
  ];

  const fortyRows = bands.map(([label, key]) => `
    <tr>
      <td>${escapeHTML(label)}</td>
      <td>${values[key] == null ? 'No data' : escapeHTML(Number(values[key]).toFixed(2))}</td>
    </tr>`).join('');

  const html = `
    <div class="forest-popup">
      <h3>Polygon ${escapeHTML(id)}</h3>
      <p><b>Verified:</b> ${escapeHTML(result.verified)}</p>
      <p><b>Year:</b> ${escapeHTML(result.year)}</p>
      <p><b>Region:</b> ${escapeHTML(result.region)}</p>
      <p><b>Polygon area:</b> ${result.area_m2 == null ? 'n/a' : Math.round(result.area_m2).toLocaleString('en-US') + ' m²'}</p>
      <p><b>Dataset agreement:</b> ${escapeHTML(agreementLabel(result))}</p>
      <hr>
      <h4>JRC — Forest Cover 2020</h4>
      <p><b>Status:</b> ${escapeHTML(jrc.status)}</p>
      <p><b>Forest cover:</b> ${jrc.forest_percentage == null
        ? 'No valid data' : escapeHTML(jrc.forest_percentage) + '%'}</p>
      <hr>
      <h4>ForTy — Forest Typology 2020</h4>
      <p><b>Status:</b> ${escapeHTML(forty.status)}</p>
      <table>${fortyRows}</table>
      <small>ForTy values are raw dataset values, not percentages.</small>
    </div>`;

  if (polygonPopup) polygonPopup.remove();

  polygonPopup = new mapboxgl.Popup({ closeButton: true, closeOnClick: false, maxWidth: '340px' })
    .setLngLat(lngLat)
    .setHTML(html)
    .addTo(map);
}

function polygonsAt(point) {
  if (!polygonsLoaded) return [];

  // Only query layers that exist right now (they are briefly missing during a style change)
  const layers = ['agreement-points', 'forest-polygon-fill', 'selected-polygon-fill']
    .filter(id => map.getLayer(id));

  if (!layers.length) return [];
  return map.queryRenderedFeatures(point, { layers });
}

// One map-level handler (avoids double popups where layers overlap)
map.on('click', e => {
  const features = polygonsAt(e.point);
  if (features.length) showPolygonPopup(features[0], e.lngLat);
});

map.on('mousemove', e => {
  map.getCanvas().style.cursor = polygonsAt(e.point).length ? 'pointer' : '';
});

/* ---------- Side menu ---------- */
const menuBtn = document.getElementById('menu-btn');
const sidebar = document.getElementById('sidebar');
const chartPanel = document.getElementById('chart-panel');
const chartTitle = document.getElementById('chart-title');

// Open / close the sidebar
menuBtn.addEventListener('click', () => {
  const isOpen = sidebar.classList.toggle('open');
  menuBtn.setAttribute('aria-expanded', isOpen);
});

// Expand / collapse every section that has sub-items
// (this now includes Study Area Polygons; it no longer toggles the layer)
document.querySelectorAll('.has-sub > .side-title').forEach(btn => {
  btn.addEventListener('click', () => {
    const isOpen = btn.parentElement.classList.toggle('open');
    btn.setAttribute('aria-expanded', isOpen);
  });
});

// Map / Chart sub-buttons (JRC + ForTy only)
document.querySelectorAll('.sub-btn:not(.polygon-layer-btn)').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.sub-btn:not(.polygon-layer-btn)')
      .forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    showView(btn.dataset.section, btn.dataset.view);
  });
});

async function showView(section, view) {
  if (view === 'chart') {
    showChart(section);
    return;
  }

  chartPanel.hidden = true;

  let endpoint, sourceId, layerId, otherLayerId;

  if (section === 'Forest Cover') {
    endpoint = `${API}/api/jrc-forest`;
    sourceId = 'jrc-forest';
    layerId = 'jrc-forest-layer';
    otherLayerId = 'forty-forest-layer';
  } else if (section === 'Change Analysis') {
    endpoint = `${API}/api/forty-forest`;
    sourceId = 'forty-forest';
    layerId = 'forty-forest-layer';
    otherLayerId = 'jrc-forest-layer';
  } else {
    return;
  }

  // If the selected layer is already visible, turn it OFF
  if (map.getLayer(layerId) && map.getLayoutProperty(layerId, 'visibility') !== 'none') {
    map.setLayoutProperty(layerId, 'visibility', 'none');
    if (rasterState[layerId]) rasterState[layerId].visible = false;
    console.log(`${section} layer turned OFF.`);
    return;
  }

  try {
    const response = await fetch(endpoint);
    if (!response.ok) throw new Error(`Backend error: ${response.status}`);

    const data = await response.json();
    if (!data.tile_url) throw new Error('Earth Engine did not return a tile URL.');

    if (!map.isStyleLoaded()) {
      await new Promise(resolve => map.once('idle', resolve));
    }

    // Hide the other forest layer
    if (map.getLayer(otherLayerId)) {
      map.setLayoutProperty(otherLayerId, 'visibility', 'none');
    }
    if (rasterState[otherLayerId]) rasterState[otherLayerId].visible = false;

    // Refresh this layer's tiles
    if (map.getLayer(layerId)) map.removeLayer(layerId);
    if (map.getSource(sourceId)) map.removeSource(sourceId);

    // Remember it, so it can be restored after a base map change
    rasterState[layerId] = { sourceId, tileUrl: data.tile_url, visible: true };

    map.addSource(sourceId, { type: 'raster', tiles: [data.tile_url], tileSize: 256, maxzoom: 14 });

    // Insert BELOW the polygons so the rasters never cover them
    map.addLayer(
      { id: layerId, type: 'raster', source: sourceId, paint: { 'raster-opacity': 0.8 } },
      map.getLayer('forest-polygon-fill') ? 'forest-polygon-fill' : undefined
    );

    console.log(`${section} layer turned ON.`);

  } catch (error) {
    console.error(`${section} loading error:`, error);
    alert(`Could not load ${section}. Check the Flask terminal and browser console (F12).`);
  }
}
