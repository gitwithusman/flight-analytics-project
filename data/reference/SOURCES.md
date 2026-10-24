# Reference data sources

| File | Source | License / terms |
|---|---|---|
| `airports_reference.csv` | OurAirports - https://ourairports.com/data/ (`airports.csv`, `countries.csv`, GitHub mirror `davidmegginson/ourairports-data`), filtered to airports that have an IATA code | Released into the **public domain** by OurAirports. Accuracy is community-maintained; coordinates are those published by OurAirports. |
| `world_land_110m.geojson` | Natural Earth 1:110m physical vectors, `ne_110m_land` - https://www.naturalearthdata.com | **Public domain**. Used only to draw the land outline of the offline route map. |

No data in these files was written or estimated by the application. Airport coordinates used by the
route map and distance calculations come exclusively from `airports_reference.csv`.
