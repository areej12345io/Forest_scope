## Unresolved questions

- The exact ForTy band scale and class definitions still need to be confirmed.
- It is unclear whether plantation and tree-crop classes should be counted as forest.
- Some differences between ForTy and JRC, especially in Uganda, need further investigation.
- The best threshold for deciding whether a polygon is “detected” still needs to be defined.

## Challenges

- Some polygons are very small compared with the 10 m pixels.
- JRC masked pixels cannot clearly be separated into missing data and non-forest.
- Earth Engine has tile and request limits at high zoom levels.
- Pixel counts were unreliable for some small polygons, so forest share is used instead.


## Trade-offs

- Results are saved as a JSON file, so they can become outdated when the data changes.
- Polygon IDs are based on their order in the GeoJSON file.
- Region assignment is based on latitude rather than country boundaries.
- A 10 m scale was used for both datasets.
- The dashboard depends on a Mapbox token and a chart library from a CDN.

## Next steps

- Confirm the ForTy classes and scale.
- Add independent validation and uncertainty estimates.
- Test small buffers around polygons.
- Add proper country or region boundaries.
- Improve the results-building process and show the results date.
- Add authentication, testing, and other production improvements.