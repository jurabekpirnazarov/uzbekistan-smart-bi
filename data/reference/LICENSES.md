# Licences of reference data

| Data | Source | Licence | Use |
|---|---|---|---|
| Official statistics | SIAT — State Statistics Committee of the Republic of Uzbekistan, https://siat.stat.uz (SDMX JSON) | Open government data published by the State Statistics Committee; cite the source | All observations |
| Region boundaries | dirixtt/GeoJSON-Uzbekistan, `uzbekistan_regional.geojson` — https://github.com/dirixtt/GeoJSON-Uzbekistan | MIT | `regions.geom` |
| District boundaries | geoBoundaries UZB ADM2 (gbOpen, build 2023-12-12), originally OCHA ROCCA via HDX — https://www.geoboundaries.org | CC BY 3.0 IGO (attribution: geoBoundaries, OCHA ROCCA) | `districts.geom` |
| Basemap tiles (frontend) | CARTO Positron / Dark Matter, © OpenStreetMap contributors | CARTO basemap terms (free, attribution shown on the map) | Map background only |

Local files: `data/reference/geo/dirixtt.zip`, `data/reference/geo/geoBoundaries-UZB-ADM2.geojson` (downloaded
by `pipelines/load_reference.py` if missing). Matching overrides: `geo_aliases.csv` (renamed districts),
`district_centroids.csv` (districts created after 2020 → placed inside their parent district).
