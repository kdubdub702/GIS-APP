# GIS-APP

LV Billboards + Parcel Join (ArcGIS REST → CSV + KML)

## Endpoints (validated)
- Billboards:
  - https://services1.arcgis.com/F1v0ufATbBQScMtY/ArcGIS/rest/services/CLV_Billboards/FeatureServer/3/query
- Parcels:
  - https://services1.arcgis.com/F1v0ufATbBQScMtY/arcgis/rest/services/CC_PARCELS_SHP/FeatureServer/257/query

## What’s new
- Geometry is now fetched (outSR=4326) so the DataFrame includes:
  - `LONGITUDE`, `LATITUDE`
- Export options from the GUI:
  - CSV (analysis)
  - KML (Google Earth / Google My Maps)
  - Demo KML (first 200 rows) for sales/prospecting

## Google Earth
1. Open Google Earth (desktop or web)
2. Projects → Open → Import KML
3. Select your exported `.kml`

## Google My Maps (Google Maps)
1. Open Google My Maps
2. Create new map → Import
3. Upload your `.kml`
4. Share publicly or privately

## Files
- `engine_v2.py` : ArcGIS fetch + parcel join (+ adds lon/lat)
- `kml_utils.py` : reusable KML/KMZ generation helpers
- `lv_billboards_gui_v2.py` : Tk app (Search + Join, Export CSV, Export KML, Create Demo KML)
