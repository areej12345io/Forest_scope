-- ForestScope database schema (safe to run more than once)
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS deforestation_polygons (
    id       SERIAL PRIMARY KEY,
    verified VARCHAR,
    year     VARCHAR,
    geom     geometry(MultiPolygon, 4326)
);

CREATE INDEX IF NOT EXISTS deforestation_polygons_geom_geom_idx
    ON deforestation_polygons USING GIST (geom);
