"""Create the schema and import the supplied GeoJSON polygons.

Safe to run more than once: existing polygons are updated, not duplicated.
"""
import json
import os
import sys
import time

import psycopg2

GEOJSON_PATH = os.getenv("GEOJSON_PATH", "data/polygons.geojson")
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")


def first_value(props, *names):
    """Return the first non-null property matching any name (case-insensitive)."""
    lowered = {str(key).lower(): value for key, value in props.items()}
    for name in names:
        if lowered.get(name) is not None:
            return lowered[name]
    return None


def connect_with_retry(attempts=30, delay=2):
    """Wait for PostgreSQL to accept connections (it restarts once after first-time setup)."""
    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            return psycopg2.connect(
                host=os.environ["DB_HOST"],
                port=os.getenv("DB_PORT", "5432"),
                dbname=os.environ["DB_NAME"],
                user=os.environ["DB_USER"],
                password=os.environ["DB_PASSWORD"],
            )
        except psycopg2.OperationalError as error:
            last_error = error
            print(f"Database not ready (attempt {attempt}/{attempts}), retrying in {delay}s...")
            time.sleep(delay)

    sys.exit(f"Could not connect to the database: {last_error}")


def main():
    if not os.path.exists(GEOJSON_PATH):
        sys.exit(
            f"GeoJSON not found at {GEOJSON_PATH}. "
            "Put the supplied file in the data/ folder as polygons.geojson."
        )

    with open(GEOJSON_PATH, encoding="utf-8") as file:
        features = json.load(file).get("features", [])

    if not features:
        sys.exit("The GeoJSON file contains no features.")

    print("Property names in the first feature:",
          list((features[0].get("properties") or {}).keys()))

    connection = connect_with_retry()

    try:
        with connection, connection.cursor() as cursor:
            with open(SCHEMA_PATH, encoding="utf-8") as file:
                cursor.execute(file.read())

            loaded = 0

            for position, feature in enumerate(features, start=1):
                geometry = feature.get("geometry")
                if not geometry:
                    print(f"Skipping feature {position}: no geometry")
                    continue

                props = feature.get("properties") or {}

                polygon_id = first_value(props, "id", "polygon_id", "fid", "objectid")
                if polygon_id is None:
                    polygon_id = feature.get("id")
                polygon_id = int(polygon_id) if polygon_id is not None else position

                verified = first_value(props, "verified")
                year = first_value(props, "year")

                cursor.execute(
                    """
                    INSERT INTO deforestation_polygons (id, verified, year, geom)
                    VALUES (
                        %s, %s, %s,
                        ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))
                    )
                    ON CONFLICT (id) DO UPDATE
                    SET verified = EXCLUDED.verified,
                        year = EXCLUDED.year,
                        geom = EXCLUDED.geom;
                    """,
                    (
                        polygon_id,
                        str(verified) if verified is not None else None,
                        str(year) if year is not None else None,
                        json.dumps(geometry),
                    ),
                )
                loaded += 1

            # Keep the id sequence ahead of the imported ids
            cursor.execute(
                """
                SELECT setval(
                    pg_get_serial_sequence('deforestation_polygons', 'id'),
                    (SELECT COALESCE(MAX(id), 1) FROM deforestation_polygons)
                );
                """
            )

        print(f"Imported {loaded} polygons into deforestation_polygons.")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
