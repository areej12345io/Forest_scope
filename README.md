# ForestScope – Forest Monitoring & Change Analysis Dashboard

A web dashboard that compares two 2020 global forest datasets against 198 manually
delineated deforestation polygons:

- **EC JRC Global Forest Cover 2020 v4** (`JRC/GFC2020/V4`, 10 m)
- **Forest Typology (ForTy) 2020 v1.0** (10 m, Earth Engine ImageCollection)

The polygons mark confirmed deforestation after 2020, so forest should have existed
there in 2020. The dashboard shows how each dataset represents those locations.

## Stack

| Part | Technology |
|---|---|
| Database | PostgreSQL 16 + PostGIS (Docker image `postgis/postgis`) |
| Backend | Python, Flask, Gunicorn, Earth Engine Python API (`earthengine-api`) |
| Frontend | HTML, CSS, JavaScript, Mapbox GL JS, Chart.js |
| Packaging | Docker Compose |

## Quick start

You need Docker Desktop (or Docker Engine with Compose v2), a Google Cloud project
registered for Earth Engine, and a Mapbox token already included in `scripts/script.js`.

1. Create your settings file:
   ```
   cp .env.example .env        # Windows: copy .env.example .env
   ```
   Edit `.env`: set `DB_PASSWORD` and `EE_PROJECT` (your Earth Engine project id).
2. Add your Earth Engine credentials (see the next section).
3. Start everything:
   ```
   docker compose up --build
   ```
4. Open **http://localhost:5000**.

The first start builds the images, creates the database, imports the polygons, and
starts the web app. Stop with `Ctrl+C`, or `docker compose down`.

## Earth Engine authentication

The app needs to be able to use Earth Engine from inside the container. Choose one option.

### Option A – service account (recommended for evaluators)

1. In your Google Cloud project, enable the **Earth Engine API**.
2. Create a **service account** and download a **JSON key**.
3. In **IAM**, give the service account these roles on the project:
   - **Earth Engine Resource Writer** – needed to create the map tiles. The read-only
     *Earth Engine Resource Viewer* role is not enough: the map layers fail with
     `Permission 'earthengine.maps.create' denied`.
   - **Service Usage Consumer**

   Role names and registration steps change over time, so check Google's current Earth
   Engine service account documentation if a step does not match.
4. Save the key as **`secrets/ee-key.json`** (the folder is mounted read-only into the
   container; it is not committed and not copied into the image).

If the ForTy layer reports a permission error, the account also needs read access to the
asset `projects/nature-trace/assets/forest_typology`.

### Option B – your personal Earth Engine login

1. Run `earthengine authenticate` on your own machine.
2. Create `docker-compose.override.yml` next to `docker-compose.yml`:
   ```yaml
   services:
     app:
       volumes:
         - <path-to-your-home>/.config/earthengine:/root/.config/earthengine:ro
   ```
   (Windows example: `C:/Users/<name>/.config/earthengine`.)
3. Leave `secrets/` empty. The app falls back to these credentials when no key file exists.

## What happens at startup

1. `db` starts PostgreSQL + PostGIS and waits until it accepts connections.
2. `loader` runs `db/load_polygons.py` once: it applies `db/schema.sql` and imports
   `data/polygons.geojson` into the table `deforestation_polygons`. It can be re-run safely.
3. `app` starts Flask/Gunicorn on port 5000. It serves the dashboard and the JSON API.

The database is also published on host port **5433** (`DB_HOST_PORT` in `.env`) so it can
be inspected, for example:

```
docker compose exec db psql -U forestuser -d forestscope -c "SELECT count(*) FROM deforestation_polygons;"
```

## Project layout

```
docker-compose.yml   Dockerfile   requirements.txt   .env.example
index.html           styles/      scripts/            media/
py/app.py            Flask API + Earth Engine analysis
db/schema.sql        table + spatial index (PostGIS)
db/load_polygons.py  polygon import
data/polygons.geojson   the supplied polygons
cache/combined_results.json   saved JRC + ForTy results per polygon
analysis/summarize_results.py   reproduces the figures in ANALYSIS.md
ANALYSIS.md          findings, limits and recommendations
secrets/             (not committed) Earth Engine key
```

## Using the dashboard

- **☰ menu → JRC Forest Data / ForTy Forest Data → Map** toggles the dataset layer.
- **… → Chart** opens comparison charts: JRC status, JRC forest share, JRC by region and by
  polygon size, ForTy dominant class, ForTy by region, and JRC vs ForTy agreement.
- **Study Area Polygons** shows all polygons, or one selected polygon (the map zooms to it).
- **Dataset Agreement Map** shows one dot per polygon, coloured by whether JRC and ForTy both,
  one, or neither show forest. The legend counts each group and can hide groups or regions
  (Brazil, Uganda).
- **Click a polygon** to see its JRC and ForTy values in a popup.

## Design decisions

### Database contents
The database holds only the supplied polygons and their attributes (`id`, `verified`,
`year`, `geom` as MultiPolygon, SRID 4326, with a GiST index). The GeoJSON has no id
property, so polygons are numbered 1–198 in file order. Neither dataset is stored in
the database; both are read directly from Earth Engine.

### Stored derived results (justification)
`cache/combined_results.json` holds the per-polygon JRC and ForTy results. This is a derived
result, so the reason for storing it is:

- Computing it needs about 200 polygons x several Earth Engine reductions, which takes
  minutes and uses Earth Engine quota. The dashboard needs popups and charts to be instant.
- Both datasets are fixed 2020 products, so the results do not change between runs.
- It is a plain file, not a database table, so the database stays limited to the supplied
  polygons. The file is only a cache and can be deleted and rebuilt.

Trade-off: the cache goes stale if the polygons or the dataset versions change. To rebuild
it, open **http://localhost:5000/api/analyze-combined-all** and wait until the page finishes
(several minutes). The file in `cache/` is replaced only if the run succeeds.

### Analysis choices
- Statistics use a 10 m scale to match both datasets.
- JRC stores only forest pixels (class 1 = forest; non-forest is masked). The forest
  percentage is therefore the share of the polygon covered by JRC forest, calculated with
  masked pixels counted as 0. A polygon with 0% has no JRC forest pixel inside it.
- ForTy values are the raw band means. The "dominant class" in the charts is the highest
  of the five bands; "Other land" is estimated as 250 minus their sum, the same rule used
  for the ForTy map layer.

## Analysis

The findings, limits and recommendations are in [ANALYSIS.md](ANALYSIS.md). It separates
descriptive comparison, plausibility checks, what can and cannot be validated, and fitness
for purpose. To reproduce the figures from the saved results and the polygons:

```
python analysis/summarize_results.py
```

## Troubleshooting

| Problem | Fix |
|---|---|
| App exits with an Earth Engine "project not found" error | Set `EE_PROJECT` in `.env` to your real project id. |
| Earth Engine credentials / permission error | Check `secrets/ee-key.json`, or use Option B. |
| Map layer fails with `earthengine.maps.create` denied | Add the *Earth Engine Resource Writer* role to the service account and wait a minute or two. |
| `Connection refused` from the loader | Run `docker compose up` again; the loader retries for about a minute. |
| Popups and charts are empty | `cache/combined_results.json` is missing; rebuild it (see above). |
| Port 5000 or 5433 already in use | Stop the other program, or change the port mapping. |
| Some map tiles stay blank, console shows `429` | Earth Engine's request limit. Wait a few seconds, then pan or zoom slightly. |
| Blank map | The Mapbox token in `scripts/script.js` must allow `http://localhost:5000`. |




## AI Assistant

I added a local AI assistant to ForestScope so users can ask questions about the forest datasets and the results without having to look through all the data themselves.

The assistant uses Ollama with the `qwen2.5:3b` model and is connected to the dashboard through Flask. It runs locally instead of using an external AI API.

Users can ask questions about individual polygons, JRC and ForTy results, differences between the datasets, and the limitations of the analysis.

For questions about a specific polygon, the backend retrieves the saved results and returns the available information directly. For general questions, it sends a summary of the analysis to the AI model, which explains the results in simple language.

### How to use it

1. Install Ollama and download the model using `ollama pull qwen2.5:3b`.
2. Make sure Ollama is running on your computer.
3. Start the dashboard using the Docker Compose instructions above.
4. Open `http://localhost:5000` and type a question in the AI Assistant panel.

### Limitations

The assistant helps users understand the results, but its answers are not guaranteed to be correct. General answers generated by the language model should be checked against the saved results and `ANALYSIS.md`.

If a polygon has no valid JRC pixels, its forest cover cannot be determined from that observation. Also, agreement between JRC and ForTy does not prove that either dataset is correct.

The assistant depends on Ollama running on the host computer. Response times depend on the computer's performance and the amount of information the model needs to process.

### Possible improvements

Further work could include testing the assistant with more questions, improving response speed, and checking how reliably it explains the results and their limitations.

More: see [NEXT_STEPS.md](NEXT_STEPS.md).