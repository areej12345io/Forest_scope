
from flask import Flask, jsonify
from flask_cors import CORS
from flask import abort, send_from_directory
from dotenv import load_dotenv
import ee
import os
import json
import psycopg2
import csv
import tempfile
import urllib.request
import urllib.error
from io import StringIO
from flask import Response
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))
CORS(app)


# ============================================================
# GOOGLE EARTH ENGINE CONNECTION
# ============================================================

def init_earth_engine():
    project = os.getenv("EE_PROJECT")
    if not project:
        raise RuntimeError("Set the EE_PROJECT environment variable.")

    key_file = os.getenv("EE_SERVICE_ACCOUNT_KEY")

    if key_file and os.path.exists(key_file):
        with open(key_file, encoding="utf-8") as file:
            email = json.load(file)["client_email"]
        credentials = ee.ServiceAccountCredentials(email, key_file)
        ee.Initialize(credentials, project=project)
    else:
        ee.Initialize(project=project)


init_earth_engine()


# ============================================================
# POSTGRESQL / POSTGIS CONNECTION
# ============================================================

def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "forestscope"),
        user=os.getenv("DB_USER", "forestuser"),
        password=os.environ["DB_PASSWORD"]
    )


# ============================================================
# JRC FOREST COVER 2020 MAP
# ============================================================

@app.route("/api/jrc-forest")
def jrc_forest():
    image = ee.Image("JRC/GFC2020/V4")
    forest = image.select("Map").eq(1).selfMask()

    visualization = {
        "min": 1,
        "max": 1,
        "palette": ["4d9221"]
    }

    map_data = forest.getMapId(visualization)

    return jsonify({
        "tile_url": map_data["tile_fetcher"].url_format
    })


# ============================================================
# FORTY FOREST TYPOLOGY 2020 MAP
# ============================================================

@app.route("/api/forty-forest")
def forty_forest():
    dataset = (
        ee.ImageCollection(
            "projects/nature-trace/assets/"
            "forest_typology/forest_typology_2020_v1_0_collection"
        )
        .mosaic()
    )

    # Estimate the sixth class from the five probability bands.
    other_land = ee.Image(250).subtract(
        dataset.select([0, 1, 2, 3, 4]).reduce(
            ee.Reducer.sum()
        )
    )

    # Select the highest-probability class.
    classified = (
        dataset
        .addBands(other_land)
        .toArray()
        .arrayArgmax()
        .arrayGet([0])
        .add(1)
    )

    visualization = {
        "min": 1,
        "max": 6,
        "palette": [
            "1B7837",
            "7FBF7B",
            "1D91C0",
            "E65FA9",
            "E6AB02",
            "FDE278"
        ]
    }

    map_data = classified.getMapId(visualization)

    return jsonify({
        "tile_url": map_data["tile_fetcher"].url_format
    })


# ============================================================
# GET ALL DEFORESTATION POLYGONS FROM POSTGIS
# ============================================================

@app.route("/api/polygons")
def get_polygons():
    connection = None

    try:
        connection = get_db_connection()

        with connection.cursor(
            cursor_factory=RealDictCursor
        ) as cursor:
            cursor.execute("""
                SELECT
                    id,
                    verified,
                    year,
                    ST_AsGeoJSON(geom)::json AS geometry
                FROM deforestation_polygons
                WHERE geom IS NOT NULL
                ORDER BY id;
            """)

            rows = cursor.fetchall()

        features = []

        for row in rows:
            features.append({
                "type": "Feature",
                "geometry": row["geometry"],
                "properties": {
                    "id": row["id"],
                    "verified": row["verified"],
                    "year": row["year"]
                }
            })

        return jsonify({
            "type": "FeatureCollection",
            "features": features
        })

    except Exception as error:
        app.logger.exception(
            "Could not retrieve polygons"
        )

        return jsonify({
            "error": str(error)
        }), 500

    finally:
        if connection is not None:
            connection.close()



# ============================================================
# ANALYZE ONE POLYGON USING JRC FOREST COVER 2020
# ============================================================

@app.route("/api/analyze/<int:polygon_id>")
def analyze_polygon(polygon_id):
    connection = None

    try:
        # Get the selected polygon as GeoJSON.
        connection = get_db_connection()

        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT
                    id,
                    verified,
                    year,
                    ST_AsGeoJSON(geom) AS geometry
                FROM deforestation_polygons
                WHERE id = %s
                  AND geom IS NOT NULL;
            """, (polygon_id,))

            row = cursor.fetchone()

        if row is None:
            return jsonify({
                "error": f"Polygon {polygon_id} not found."
            }), 404

        polygon_id, verified, year, geometry_geojson = row

        # Convert GeoJSON text to a Python dictionary.
        polygon_geojson = json.loads(geometry_geojson)

        # Convert the polygon geometry to Earth Engine geometry.
        polygon = ee.Geometry(polygon_geojson)

        # Load JRC Global Forest Cover 2020.
        jrc = ee.Image("JRC/GFC2020/V4").select("Map")

        # ----------------------------------------------------
        # STEP 1: Count pixels with valid original JRC data.
        # Do NOT unmask the original image here.
        # ----------------------------------------------------
        valid_result = jrc.reduceRegion(
            reducer=ee.Reducer.count(),
            geometry=polygon,
            scale=10,
            maxPixels=1e9
        ).getInfo()

        valid_pixel_count = valid_result.get("Map")

        # If no valid pixels exist, do not report 0% forest.
        if valid_pixel_count is None or valid_pixel_count == 0:
            return jsonify({
                "polygon_id": polygon_id,
                "verified": verified,
                "year": year,
                "valid_jrc_pixel_count": 0,
                "jrc_forest_percentage": None,
                "interpretation": (
                    "No valid JRC data was available for this polygon "
                    "at the analysis scale. Forest percentage cannot "
                    "be calculated."
                )
            })

        # ----------------------------------------------------
        # STEP 2: Calculate forest percentage using valid pixels.
        # Class 1 represents forest.
        # Preserve the original data mask.
        # ----------------------------------------------------
        forest = jrc.eq(1)

        result = forest.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=polygon,
            scale=10,
            maxPixels=1e9
        ).getInfo()

        forest_fraction = result.get("Map")

        if forest_fraction is not None:
            forest_percentage = round(
                forest_fraction * 100, 2
            )

            interpretation = (
                "Percentage of valid sampled JRC pixels classified "
                "as forest."
            )
        else:
            forest_percentage = None

            interpretation = (
                "Valid JRC pixels were counted, but the forest "
                "percentage could not be calculated."
            )

        # ----------------------------------------------------
        # STEP 3: Return the analysis result.
        # ----------------------------------------------------
        return jsonify({
            "polygon_id": polygon_id,
            "verified": verified,
            "year": year,
            "valid_jrc_pixel_count": valid_pixel_count,
            "jrc_forest_percentage": forest_percentage,
            "interpretation": interpretation
        })

    except Exception as error:
        app.logger.exception(
            "Polygon analysis failed"
        )

        return jsonify({
            "error": str(error)
        }), 500

    finally:
        if connection is not None:
            connection.close()


@app.route("/api/analyze-forty/<int:polygon_id>")
def analyze_forty_polygon(polygon_id):
    connection = None

    try:
        connection = get_db_connection()

        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT
                    id,
                    verified,
                    year,
                    ST_AsGeoJSON(geom) AS geometry
                FROM deforestation_polygons
                WHERE id = %s AND geom IS NOT NULL;
            """, (polygon_id,))

            row = cursor.fetchone()

        if row is None:
            return jsonify({
                "error": f"Polygon {polygon_id} not found."
            }), 404

        polygon_id, verified, year, geometry_geojson = row

        polygon = ee.Geometry(json.loads(geometry_geojson))

        # ForTy is an ImageCollection, not a single Image.
        forty_collection = (
            ee.ImageCollection(
                "projects/nature-trace/assets/"
                "forest_typology/forest_typology_2020_v1_0_collection"
            )
            .filterBounds(polygon)
        )

        tile_count = forty_collection.size().getInfo()

        if tile_count == 0:
            return jsonify({
                "polygon_id": polygon_id,
                "verified": verified,
                "year": year,
                "forty_status": "No ForTy data",
                "forty_tile_count": 0,
                "forty_values": None
            })

        forty_image = forty_collection.mosaic()

        result = forty_image.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=polygon,
            scale=10,
            maxPixels=1e9
        ).getInfo()

        return jsonify({
            "polygon_id": polygon_id,
            "verified": verified,
            "year": year,
            "forty_status": "Available",
            "forty_tile_count": tile_count,
            "forty_values": {
                "PrimaryForest": result.get("PrimaryForest"),
                "NaturallyRegeneratingForest":
                    result.get("NaturallyRegeneratingForest"),
                "PlantedForest": result.get("PlantedForest"),
                "PlantationForest": result.get("PlantationForest"),
                "TreeCropsAndAgroforestry":
                    result.get("TreeCropsAndAgroforestry")
            }
        })

    except Exception as error:
        app.logger.exception(
            "ForTy analysis failed for polygon %s",
            polygon_id
        )

        return jsonify({
            "error": str(error)
        }), 500

    finally:
        if connection is not None:
            connection.close()


@app.route("/api/analyze-combined/<int:polygon_id>")
def analyze_combined_polygon(polygon_id):
    connection = None

    try:
        connection = get_db_connection()

        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT
                    id,
                    verified,
                    year,
                    ST_AsGeoJSON(geom) AS geometry
                FROM deforestation_polygons
                WHERE id = %s AND geom IS NOT NULL;
            """, (polygon_id,))

            row = cursor.fetchone()

        if row is None:
            return jsonify({
                "error": f"Polygon {polygon_id} not found."
            }), 404

        polygon_id, verified, year, geometry_geojson = row
        polygon = ee.Geometry(json.loads(geometry_geojson))

        # --------------------------------------------------
        # JRC
        # --------------------------------------------------

        jrc = ee.Image("JRC/GFC2020/V4").select("Map")

        valid_result = jrc.reduceRegion(
            reducer=ee.Reducer.count(),
            geometry=polygon,
            scale=10,
            maxPixels=1e9
        ).getInfo()

        valid_pixel_count = valid_result.get("Map") or 0

        if valid_pixel_count == 0:
            jrc_forest_percentage = None
            jrc_status = "No valid JRC data"
        else:
            forest_result = jrc.eq(1).reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=polygon,
                scale=10,
                maxPixels=1e9
            ).getInfo()

            forest_fraction = forest_result.get("Map")

            if forest_fraction is None:
                jrc_forest_percentage = None
                jrc_status = "No valid JRC data"
            else:
                jrc_forest_percentage = round(
                    forest_fraction * 100,
                    2
                )

                if jrc_forest_percentage > 0:
                    jrc_status = "Forest"
                else:
                    jrc_status = "Non-forest"

        # --------------------------------------------------
        # ForTy
        # --------------------------------------------------

        forty_collection = (
            ee.ImageCollection(
                "projects/nature-trace/assets/"
                "forest_typology/forest_typology_2020_v1_0_collection"
            )
            .filterBounds(polygon)
        )

        forty_tile_count = forty_collection.size().getInfo()

        if forty_tile_count == 0:

            forty_status = "No ForTy data"
            forty_values = None

        else:

            forty_image = forty_collection.mosaic()

            forty_result = forty_image.reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=polygon,
                scale=10,
                maxPixels=1e9
            ).getInfo()

            forty_status = "Available"

            forty_values = {
                "PrimaryForest":
                    forty_result.get("PrimaryForest"),

                "NaturallyRegeneratingForest":
                    forty_result.get(
                        "NaturallyRegeneratingForest"
                    ),

                "PlantedForest":
                    forty_result.get("PlantedForest"),

                "PlantationForest":
                    forty_result.get(
                        "PlantationForest"
                    ),

                "TreeCropsAndAgroforestry":
                    forty_result.get(
                        "TreeCropsAndAgroforestry"
                    )
            }

        # --------------------------------------------------
        # Combined response
        # --------------------------------------------------

        return jsonify({
            "polygon_id": polygon_id,
            "verified": verified,
            "year": year,

            "jrc": {
                "status": jrc_status,
                "forest_percentage": jrc_forest_percentage,
                "valid_pixel_count": valid_pixel_count
            },

            "forty": {
                "status": forty_status,
                "tile_count": forty_tile_count,
                "values": forty_values
            }
        })

    except Exception as error:

        app.logger.exception(
            "Combined analysis failed for polygon %s",
            polygon_id
        )

        return jsonify({
            "error": str(error)
        }), 500

    finally:

        if connection is not None:
            connection.close()



@app.route("/api/analyze-combined-all")
def analyze_combined_all():
    connection = None
    temp_path = None

    try:
        # 1. Read all polygons from PostGIS
        connection = get_db_connection()

        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT
                    id,
                    verified,
                    year,
                    ST_AsGeoJSON(geom) AS geometry
                FROM deforestation_polygons
                WHERE geom IS NOT NULL
                ORDER BY id;
            """)
            rows = cursor.fetchall()

        if not rows:
            return jsonify({"results": [], "count": 0})

        # 2. Convert database polygons to Earth Engine features
        features = []

        for polygon_id, verified, year, geometry_json in rows:
            geometry = ee.Geometry(json.loads(geometry_json))

            features.append(
                ee.Feature(
                    geometry,
                    {
                        "polygon_id": polygon_id,
                        "verified": verified,
                        "year": year
                    }
                )
            )

        areas = ee.FeatureCollection(features)

        # 3. Analyze JRC forest cover
        jrc = ee.Image("JRC/GFC2020/V4").select("Map")

        jrc_counts = jrc.reduceRegions(
            collection=areas,
            reducer=ee.Reducer.count(),
            scale=10,
            tileScale=4
        )

        jrc_forest = jrc.unmask(0).eq(1)   # JRC masks non-forest, so fill with 0

        jrc_means = jrc_forest.reduceRegions(
            collection=areas,
            reducer=ee.Reducer.mean(),
            scale=10,
            tileScale=4
        )

        # 4. Analyze ForTy forest typology
        forty_collection = ee.ImageCollection(
            "projects/nature-trace/assets/"
            "forest_typology/forest_typology_2020_v1_0_collection"
        ).filterBounds(areas.geometry())

        forty_image = forty_collection.mosaic()

        forty_results = forty_image.reduceRegions(
            collection=areas,
            reducer=ee.Reducer.mean(),
            scale=10,
            tileScale=4
        )

        # 5. Retrieve results from Earth Engine
        counts_info = jrc_counts.getInfo()
        means_info = jrc_means.getInfo()
        forty_info = forty_results.getInfo()

        def properties_by_id(collection_info):
            output = {}

            for feature in collection_info["features"]:
                props = feature["properties"]
                polygon_id = props.get("polygon_id")

                if polygon_id is not None:
                    output[int(polygon_id)] = props

            return output

        counts = properties_by_id(counts_info)
        means = properties_by_id(means_info)
        forty = properties_by_id(forty_info)

        # 6. Combine JRC and ForTy results
        results = []

        for polygon_id, verified, year, _ in rows:
            count_value = counts.get(
                polygon_id, {}
            ).get("count")

            forest_fraction = means.get(
                polygon_id, {}
            ).get("mean")

            # The count is weighted by how much of each pixel the polygon covers,
            # so it can be below 1 for polygons smaller than a pixel. Don't truncate.
            valid_pixels = (
                round(float(count_value), 2)
                if count_value is not None
                else 0
            )

            if forest_fraction is None:
                jrc_status = "No JRC result"
                forest_percentage = None
            else:
                forest_percentage = round(float(forest_fraction) * 100, 2)
                jrc_status = (
                    "Forest pixels present"
                    if forest_percentage > 0
                    else "No forest pixels"
                )

            forty_props = forty.get(polygon_id, {})

            band_names = [
                "PrimaryForest",
                "NaturallyRegeneratingForest",
                "PlantedForest",
                "PlantationForest",
                "TreeCropsAndAgroforestry"
            ]

            forty_values = {
                band: forty_props.get(band)
                for band in band_names
            }

            forty_available = any(
                value is not None
                for value in forty_values.values()
            )

            results.append({
                "polygon_id": polygon_id,
                "verified": verified,
                "year": year,
                "jrc": {
                    "status": jrc_status,
                    "forest_percentage": forest_percentage,
                    "valid_pixel_count": valid_pixels
                },
                "forty": {
                    "status": (
                        "Available"
                        if forty_available
                        else "No ForTy data"
                    ),
                    "values": (
                        forty_values if forty_available else None
                    )
                }
            })

        # 7. Save the combined results to a JSON cache
        cache_folder = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "cache"
        )
        os.makedirs(cache_folder, exist_ok=True)

        cache_file = os.path.join(
            cache_folder,
            "combined_results.json"
        )

        # Write to a temporary file first
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=cache_folder,
            delete=False
        ) as temp_file:
            json.dump(
                {
                    "count": len(results),
                    "results": results
                },
                temp_file
            )
            temp_path = temp_file.name

        # Replace the cache file after writing succeeds
        os.replace(temp_path, cache_file)
        temp_path = None

        return jsonify({
            "count": len(results),
            "results": results,
            "saved": True
        })

    except Exception as error:
        app.logger.exception("Combined bulk analysis failed")
        return jsonify({"error": str(error)}), 500

    finally:
        # Remove an unfinished temporary file if necessary
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

        if connection is not None:
            connection.close()


# 8. Read saved results without rerunning Earth Engine
@app.route("/api/combined-results")
def get_combined_results():
    cache_file = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "cache",
        "combined_results.json"
    )

    if not os.path.exists(cache_file):
        return jsonify({
            "error": (
                "No saved results yet. "
                "Run /api/analyze-combined-all first."
            )
        }), 404

    try:
        with open(cache_file, "r", encoding="utf-8") as file:
            return jsonify(json.load(file))

    except (OSError, json.JSONDecodeError):
        app.logger.exception("Could not read combined results cache")
        return jsonify({
            "error": "Could not read the saved results file."
        }), 500

# ============================================================
# ANALYZE ALL POLYGONS USING JRC FOREST COVER 2020
# ============================================================

@app.route("/api/analyze-all")
def analyze_all_polygons():
    connection = None

    try:
        connection = get_db_connection()

        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT
                    id,
                    verified,
                    year,
                    ST_AsGeoJSON(geom)
                FROM deforestation_polygons
                WHERE geom IS NOT NULL
                ORDER BY id;
            """)
            rows = cursor.fetchall()

        jrc = ee.Image("JRC/GFC2020/V4").select("Map")
        results = []

        for polygon_id, verified, year, geometry_geojson in rows:
            try:
                polygon = ee.Geometry(json.loads(geometry_geojson))

                # Count only pixels with valid original JRC data.
                valid_result = jrc.reduceRegion(
                    reducer=ee.Reducer.count(),
                    geometry=polygon,
                    scale=10,
                    maxPixels=1e9
                ).getInfo()

                valid_pixel_count = valid_result.get("Map") or 0

                if valid_pixel_count == 0:
                    forest_percentage = None
                    status = "No valid JRC data"
                else:
                    # Calculate forest percentage without filling masked data.
                    forest_result = jrc.eq(1).reduceRegion(
                        reducer=ee.Reducer.mean(),
                        geometry=polygon,
                        scale=10,
                        maxPixels=1e9
                    ).getInfo()

                    forest_fraction = forest_result.get("Map")

                    if forest_fraction is None:
                        forest_percentage = None
                        status = "Forest percentage unavailable"
                    else:
                        forest_percentage = round(
                            forest_fraction * 100, 2
                        )
                        status = "Available"

                results.append({
                    "polygon_id": polygon_id,
                    "verified": verified,
                    "year": year,
                    "valid_jrc_pixel_count": valid_pixel_count,
                    "jrc_forest_percentage": forest_percentage,
                    "jrc_status": status
                })

            except Exception as polygon_error:
                app.logger.exception(
                    "JRC analysis failed for polygon %s", polygon_id
                )

                results.append({
                    "polygon_id": polygon_id,
                    "verified": verified,
                    "year": year,
                    "valid_jrc_pixel_count": None,
                    "jrc_forest_percentage": None,
                    "jrc_status": "Analysis error",
                    "error": str(polygon_error)
                })

        return jsonify({
            "total_polygons": len(results),
            "dataset": "JRC Global Forest Cover 2020",
            "results": results
        })

    except Exception as error:
        app.logger.exception("Bulk JRC analysis failed")
        return jsonify({"error": str(error)}), 500

    finally:
        if connection is not None:
            connection.close()




@app.route("/api/analyze-all.csv")
def download_analysis_csv():
    try:
        data = analyze_all_polygons().get_json()

        if "error" in data:
            return jsonify(data), 500

        output = StringIO()
        fieldnames = [
            "polygon_id",
            "verified",
            "year",
            "valid_jrc_pixel_count",
            "jrc_forest_percentage",
            "jrc_status"
        ]

        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data["results"])

        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={
                "Content-Disposition":
                    "attachment; filename=forestscope_jrc_analysis.csv"
            }
        )

    except Exception as error:
        app.logger.exception("CSV export failed")
        return jsonify({"error": str(error)}), 500






@app.route("/api/assistant", methods=["POST"])
def forestscope_assistant():
    import math
    import re
    import urllib.request
    import urllib.error
    from flask import request

    try:
        # 1. Validate the question.
        payload = request.get_json(silent=True) or {}
        message = payload.get("message", "")

        if not isinstance(message, str) or not message.strip():
            return jsonify({"error": "Please enter a question."}), 400

        message = message.strip()

        if len(message) > 1000:
            return jsonify({
                "error": "Please keep questions under 1000 characters."
            }), 400

        # 2. Load the saved analysis.
        cache_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "cache",
            "combined_results.json"
        )

        if not os.path.exists(cache_file):
            return jsonify({
                "error": "Saved analysis results are not available yet."
            }), 503

        with open(cache_file, "r", encoding="utf-8") as file:
            saved_data = json.load(file)

        records = saved_data.get("results", [])

        if not isinstance(records, list):
            return jsonify({
                "error": "The saved analysis has an unexpected format."
            }), 500

        # Keep only dictionary records.
        records = [row for row in records if isinstance(row, dict)]
        total = len(records)

        def valid_number(value):
            """Return True only for finite numeric values, not booleans."""
            return (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
            )

        def get_numeric_forty_values(record):
            forty = record.get("forty") or {}
            if not isinstance(forty, dict):
                return {}

            values = forty.get("values") or {}
            if not isinstance(values, dict):
                return {}

            return {
                name: value
                for name, value in values.items()
                if valid_number(value)
            }

        # 3. Detect polygon-specific questions.
        # Examples: "polygon 136", "Polygon #136", "tell me polygon 136".
        match = re.search(
            r"\bpolygon\s*#?\s*(\d+)\b",
            message,
            re.IGNORECASE
        )

        requested_id = match.group(1) if match else None

        if requested_id is not None:
            selected_record = next(
                (
                    row for row in records
                    if str(row.get("polygon_id")) == requested_id
                ),
                None
            )

            if selected_record is None:
                return jsonify({
                    "answer": (
                        f"Polygon {requested_id} was not found "
                        "in the saved analysis records."
                    )
                })

            # 4. Answer polygon facts directly from Python.
            # This prevents the language model from changing saved facts.
            jrc = selected_record.get("jrc") or {}
            forty = selected_record.get("forty") or {}

            if not isinstance(jrc, dict):
                jrc = {}
            if not isinstance(forty, dict):
                forty = {}

            lines = [
                f"Polygon {requested_id}",
                f"Verified: {selected_record.get('verified', 'Unknown')}",
                f"Year: {selected_record.get('year', 'Unknown')}",
            ]

            valid_pixels = jrc.get("valid_pixel_count")
            forest_percentage = jrc.get("forest_percentage")

            if not valid_number(valid_pixels) or valid_pixels <= 0:
                lines.extend([
                    "JRC status: No valid JRC pixels.",
                    (
                        "Forest cover cannot be determined from this "
                        "observation because there are no valid JRC pixels."
                    )
                ])
            else:
                lines.append(
                    f"JRC status: {jrc.get('status', 'Available')}"
                )
                lines.append(
                    f"JRC valid pixel count: {valid_pixels:g}"
                )

                if valid_number(forest_percentage):
                    lines.append(
                        f"JRC forest cover: {forest_percentage:.2f}%"
                    )
                else:
                    lines.append(
                        "JRC forest percentage is not available as a "
                        "valid numeric value."
                    )

            # Report all saved ForTy values and calculate the dominant class.
            forty_values = get_numeric_forty_values(selected_record)

            if forty_values:
                dominant_class = max(
                    forty_values,
                    key=forty_values.get
                )

                lines.extend([
                    f"ForTy status: {forty.get('status', 'Available')}",
                    f"Dominant ForTy class: {dominant_class}",
                    (
                        "Dominant class saved value: "
                        f"{forty_values[dominant_class]:.2f}"
                    ),
                    "Saved ForTy class-band values (not percentages):"
                ])

                for class_name, value in forty_values.items():
                    lines.append(f"- {class_name}: {value:.2f}")
            else:
                lines.append(
                    "No usable numeric ForTy class values are present "
                    "in this saved record."
                )

            lines.append(
                "Interpretation note: agreement between datasets "
                "does not prove accuracy or independent validation."
            )

            # No Ollama call for exact polygon lookups.
            return jsonify({"answer": "\n".join(lines)})

        # 5. Prepare reliable summary statistics for general questions.
        valid_jrc_rows = []

        for row in records:
            jrc = row.get("jrc") or {}
            if not isinstance(jrc, dict):
                continue

            valid_pixels = jrc.get("valid_pixel_count")
            percentage = jrc.get("forest_percentage")

            if (
                valid_number(valid_pixels)
                and valid_pixels > 0
                and valid_number(percentage)
            ):
                valid_jrc_rows.append(row)

        jrc_no_valid_data = total - len(valid_jrc_rows)

        complete_forest_rows = [
            row for row in valid_jrc_rows
            if row["jrc"]["forest_percentage"] >= 99.999
        ]

        complete_forest_rows.sort(
            key=lambda row: row["jrc"]["valid_pixel_count"],
            reverse=True
        )

        # The displayed list contains at most 20 records.
        complete_forest_polygons = [
            {
                "polygon_id": row.get("polygon_id"),
                "year": row.get("year"),
                "forest_percentage": row["jrc"]["forest_percentage"],
                "valid_pixel_count": row["jrc"]["valid_pixel_count"]
            }
            for row in complete_forest_rows[:20]
        ]

        # Count polygons whose dominant ForTy class is forest-related.
        forest_classes = {
            "PrimaryForest",
            "NaturallyRegeneratingForest",
            "PlantedForest",
            "PlantationForest",
            "NaturallyRegeneratingForest"
        }

        forty_forest_dominant_count = 0

        for row in records:
            numeric_values = get_numeric_forty_values(row)

            if numeric_values:
                dominant_class = max(
                    numeric_values,
                    key=numeric_values.get
                )

                if dominant_class in forest_classes:
                    forty_forest_dominant_count += 1

        # 6. Build a concise context for general questions.
        context = {
            "portal_description": (
                "ForestScope is a dashboard for inspecting saved "
                "post-2020 deforestation polygon records and comparing "
                "them with the JRC Global Forest Change 2020 forest-cover "
                "product and ForTy 2020 forest typology."
            ),
            "polygon_count": total,
            "jrc_valid_polygon_count": len(valid_jrc_rows),
            "jrc_no_valid_data_count": jrc_no_valid_data,
            "complete_jrc_forest_polygon_count": len(
                complete_forest_rows
            ),
            "complete_jrc_forest_polygons_ranked_by_valid_pixel_count":
                complete_forest_polygons,
            "ranking_note": (
                "The supplied ranking list contains at most 20 polygons. "
                "It is ranked by valid JRC pixel count, not forest area. "
                "Do not invent ranks outside the supplied list."
            ),
            "forty_forest_class_dominant_count":
                forty_forest_dominant_count,
            "important_limitations": [
                "JRC is a 2020 forest-cover product, not an annual "
                "deforestation-change product.",
                "Zero valid JRC pixels means forest cover cannot be "
                "determined from that observation.",
                "ForTy class-band values are not percentages.",
                "The dominant ForTy class is the class with the largest "
                "saved numeric value.",
                "Agreement or disagreement between datasets does not "
                "establish which dataset is correct.",
                "Dataset agreement is not independent validation.",
                "Valid pixel count is not the same as forest area."
            ]
        }

        # 7. Ask Ollama to answer general analytical questions.
        prompt = (
            "You are the ForestScope analysis assistant. Answer clearly "
            "and concisely using only the supplied context.\n\n"
            "RULES:\n"
            "1. Never invent measurements, statistics, or polygon IDs.\n"
            "2. Use the supplied statistics and ranking list exactly.\n"
            "3. Never claim a rank outside the supplied ranking list.\n"
            "4. Pixel count is not forest area.\n"
            "5. ForTy class-band values are not percentages.\n"
            "6. Zero valid JRC pixels means forest cover cannot be "
            "determined from that observation.\n"
            "7. JRC represents forest cover in 2020, not annual "
            "deforestation change.\n"
            "8. Agreement between datasets does not prove accuracy "
            "or independent validation.\n"
            "9. If the context does not answer a question, say so.\n\n"
            "ANALYSIS CONTEXT:\n"
            + json.dumps(context, ensure_ascii=False)
            + "\n\nUSER QUESTION:\n"
            + message
        )

        # 8. Call the local Ollama model for general questions only.
        request_data = json.dumps({
            "model": "qwen2.5:3b",
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": 180
            }
        }).encode("utf-8")

        ollama_request = urllib.request.Request(
            "http://host.docker.internal:11434/api/generate",
            data=request_data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(
            ollama_request,
            timeout=180
        ) as response:
            model_result = json.loads(
                response.read().decode("utf-8")
            )

        answer = model_result.get("response", "").strip()

        if not answer:
            return jsonify({
                "error": "The local assistant returned an empty answer."
            }), 502

        return jsonify({"answer": answer})

    except urllib.error.HTTPError as error:
        app.logger.exception("Ollama returned an HTTP error")
        return jsonify({
            "error": f"The local AI model returned HTTP {error.code}."
        }), 502

    except (urllib.error.URLError, TimeoutError) as error:
        app.logger.warning(
            "ForestScope Ollama request failed: %s", error
        )
        return jsonify({
            "error": (
                "The local AI model could not respond in time. "
                "Check that Ollama is running and try again."
            )
        }), 503

    except (OSError, json.JSONDecodeError):
        app.logger.exception("ForestScope assistant failed")
        return jsonify({
            "error": (
                "Could not load the saved analysis or process "
                "the local AI response."
            )
        }), 500

    except Exception:
        app.logger.exception("Unexpected ForestScope assistant error")
        return jsonify({
            "error": "The assistant encountered an unexpected error."
        }), 500



# ============================================================
# START FLASK SERVER
# ============================================================

@app.route("/config.js")
def front_end_config():
    body = "window.FORESTSCOPE_CONFIG = " + json.dumps(
        {"mapboxToken": os.getenv("MAPBOX_TOKEN", "")}
    ) + ";"
    return Response(body, mimetype="application/javascript")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/<path:filename>")
def front_end_files(filename):
    if filename.split("/")[0] in ("styles", "scripts", "media"):
        return send_from_directory(BASE_DIR, filename)
    abort(404)
if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False
    )

