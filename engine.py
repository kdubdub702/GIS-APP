import re
import json
import requests
import pandas as pd

UA = {"User-Agent": "Mozilla/5.0"}

# Clark County parcels layer (hosted in the same ArcGIS org you've been using)
PARCELS_QUERY = "https://services1.arcgis.com/F1v0ufATbBQScMtY/arcgis/rest/services/CC_PARCELS_SHP/FeatureServer/257/query"


# ----------------------
# Small utilities
# ----------------------

def digits_only(s: str) -> str:
    return re.sub(r"\D+", "", s or "")

def safe_sql(s: str) -> str:
    return (s or "").replace("'", "''").strip()

def layer_query_url(layer_url: str) -> str:
    base = (layer_url or "").rstrip("/")
    if not base:
        raise ValueError("Missing layer_url")
    if base.lower().endswith("/query"):
        return base
    return base + "/query"

def arcgis_get_json(query_url: str, params: dict) -> dict:
    """
    ArcGIS REST query helper.

    IMPORTANT:
    - Large geometries in the query string can trigger IIS 404 errors (query string too long).
    - To avoid that, use POST when geometry is present or the URL would be long.
    """
    use_post = False

    # Geometry almost always explodes URL length -> use POST
    if "geometry" in params:
        use_post = True
    else:
        # Heuristic: if the encoded URL would be long, use POST
        try:
            from urllib.parse import urlencode
            if len(query_url) + 1 + len(urlencode(params)) > 1800:
                use_post = True
        except Exception:
            pass

    if use_post:
        r = requests.post(query_url, data=params, headers=UA, timeout=90)
    else:
        r = requests.get(query_url, params=params, headers=UA, timeout=90)

    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}\nURL: {r.url}\nBody: {r.text[:600]}")

    j = r.json()
    if "error" in j:
        msg = j["error"].get("message") or "ArcGIS error"
        raise RuntimeError(msg)
    return j


def fetch_ids_where(query_url: str, where: str) -> list[int]:
    """
    Gets OBJECTIDs for a where-clause (supports pagination by using returnIdsOnly).
    """
    j = arcgis_get_json(query_url, {
        "f": "pjson",
        "where": where,
        "returnIdsOnly": "true"
    })
    oids = j.get("objectIds") or []
    return [int(x) for x in oids]


def fetch_by_objectids(query_url: str, object_ids: list[int], out_fields="*", chunk_size=200,
                       return_geometry: bool = False, out_sr: int | None = None):
    """
    Fetch records by OBJECTID list in chunks. Returns (df, geoms?)
    """
    if not object_ids:
        return pd.DataFrame(), ([] if return_geometry else None)

    rows = []
    geoms = [] if return_geometry else None

    for i in range(0, len(object_ids), chunk_size):
        chunk = object_ids[i:i+chunk_size]
        params = {
            "f": "pjson",
            "objectIds": ",".join(str(x) for x in chunk),
            "outFields": out_fields,
            "returnGeometry": "true" if return_geometry else "false",
        }
        if out_sr:
            params["outSR"] = str(out_sr)

        j = arcgis_get_json(query_url, params)
        feats = j.get("features") or []
        for f in feats:
            attrs = f.get("attributes") or {}
            rows.append(attrs)
            if return_geometry:
                geoms.append(f.get("geometry") or {})

    df = pd.DataFrame(rows)
    return df, geoms


def fetch_with_geometry_by_ids(layer_url: str, object_ids: list[int], out_sr: int | None = None):
    """
    Re-fetch a known set of records by OBJECTID and include geometry.
    This enables spatial join for Henderson SignPlans even when the initial query returnedGeometry=false.
    """
    q = layer_query_url(layer_url)
    df, geoms = fetch_by_objectids(
        q,
        object_ids,
        out_fields="*",
        chunk_size=200,
        return_geometry=True,
        out_sr=out_sr
    )
    return df, geoms


# ----------------------
# Generic searches
# ----------------------

def objectid_exact(layer_url: str, object_id: str):
    oid = digits_only(object_id)
    if not oid:
        raise ValueError("Enter an ObjectID (digits).")
    q = layer_query_url(layer_url)
    return fetch_by_objectids(q, [int(oid)], out_fields="*", chunk_size=200)[0]

def objectid_range(layer_url: str, start_id: str, end_id: str, oid_field: str = "OBJECTID"):
    s = digits_only(start_id)
    e = digits_only(end_id)
    if not s or not e:
        raise ValueError("Enter Start and End ObjectID (digits).")
    s_i, e_i = int(s), int(e)
    if e_i < s_i:
        s_i, e_i = e_i, s_i

    q = layer_query_url(layer_url)

    where = f"{oid_field} >= {s_i} AND {oid_field} <= {e_i}"
    oids = fetch_ids_where(q, where)
    df, _ = fetch_by_objectids(q, oids, out_fields="*", chunk_size=200)
    return df

def fetch_all(layer_url: str, where: str = "1=1"):
    q = layer_query_url(layer_url)
    oids = fetch_ids_where(q, where)
    df, _ = fetch_by_objectids(q, oids, out_fields="*", chunk_size=200)
    return df

def fetch_all_with_geometry(layer_url: str, where: str = "1=1", out_sr: int | None = None):
    q = layer_query_url(layer_url)
    oids = fetch_ids_where(q, where)
    df, geoms = fetch_by_objectids(q, oids, out_fields="*", chunk_size=200, return_geometry=True, out_sr=out_sr)
    return df, geoms

def apn_partial(layer_url: str, apn_field: str, apn: str):
    apn_digits = digits_only(apn)
    if not apn_digits:
        raise ValueError("Enter an APN/PARCEL (digits).")
    q = layer_query_url(layer_url)
    where = f"{apn_field} LIKE '%{safe_sql(apn_digits)}%'"
    oids = fetch_ids_where(q, where)
    df, _ = fetch_by_objectids(q, oids, out_fields="*", chunk_size=200)
    return df

def address_partial_split(layer_url: str, street_num: str, street_dir: str, street_name: str,
                          field_num: str, field_dir: str, field_name: str):
    q = layer_query_url(layer_url)

    clauses = []
    if street_num and str(street_num).strip():
        num = safe_sql(str(street_num).strip())
        clauses.append(f"{field_num} LIKE '%{num}%'")

    if street_dir and str(street_dir).strip():
        d = safe_sql(str(street_dir).strip().upper())
        clauses.append(f"UPPER({field_dir}) LIKE '%{d}%'")

    if street_name and str(street_name).strip():
        nm = safe_sql(str(street_name).strip().upper())
        clauses.append(f"UPPER({field_name}) LIKE '%{nm}%'")

    if not clauses:
        raise ValueError("Enter at least one address part (num/dir/name).")

    where = " AND ".join(clauses)
    oids = fetch_ids_where(q, where)
    df, _ = fetch_by_objectids(q, oids, out_fields="*", chunk_size=200)
    return df

def address_partial_single(layer_url: str, addr_field: str, addr: str):
    q = layer_query_url(layer_url)
    a = safe_sql(addr)
    if not a:
        raise ValueError("Enter an address string.")
    where = f"UPPER({addr_field}) LIKE '%{a.upper()}%'"
    oids = fetch_ids_where(q, where)
    df, _ = fetch_by_objectids(q, oids, out_fields="*", chunk_size=200)
    return df


# ----------------------
# Parcel join (field-based)
# ----------------------

def parcels_by_parcel_ids(parcel_ids: list[str]) -> pd.DataFrame:
    if not parcel_ids:
        return pd.DataFrame()

    uniq = sorted({digits_only(str(x)) for x in parcel_ids if digits_only(str(x))})
    if not uniq:
        return pd.DataFrame()

    # ArcGIS max WHERE length is limited; chunk into OR groups
    out = []
    for i in range(0, len(uniq), 150):
        chunk = uniq[i:i+150]
        or_list = " OR ".join([f"PARCEL='{safe_sql(x)}'" for x in chunk])
        j = arcgis_get_json(PARCELS_QUERY, {
            "f": "pjson",
            "where": or_list,
            "outFields": "PARCEL,OWNER,ADDRESS,STRNO,STRNAME,STRTYPE,STRDIR,ZIP,SALEDATE,SALEPRICE,TAXDIST,LANDUSE,LANDVAL1,IMPVAL",
            "returnGeometry": "false",
        })
        feats = j.get("features") or []
        out.extend([(f.get("attributes") or {}) for f in feats])

    return pd.DataFrame(out)


def join_to_parcels(df: pd.DataFrame, left_field: str) -> pd.DataFrame:
    if df is None or df.empty or left_field not in df.columns:
        return df
    parcels = parcels_by_parcel_ids(df[left_field].astype(str).tolist())
    if parcels.empty or "PARCEL" not in parcels.columns:
        return df
    return df.merge(parcels, left_on=left_field, right_on="PARCEL", how="left", suffixes=("_CITY", "_PARCEL"))


# ----------------------
# Spatial join helpers (Henderson SignPlans)
# ----------------------

def _parcel_intersect_first(sign_geom: dict, in_sr: int) -> dict:
    if not sign_geom:
        return {}

    j = arcgis_get_json(PARCELS_QUERY, {
        "f": "pjson",
        "geometry": json.dumps(sign_geom),
        "geometryType": "esriGeometryPolygon",
        "inSR": str(in_sr),
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "PARCEL,OWNER,ADDRESS,STRNO,STRNAME,STRTYPE,STRDIR,ZIP,SALEDATE,SALEPRICE,TAXDIST,LANDUSE,LANDVAL1,IMPVAL",
        "returnGeometry": "false",
        "resultRecordCount": "1",
    })
    feats = j.get("features") or []
    if not feats:
        return {}
    return (feats[0].get("attributes") or {})

def spatial_join_signplans_to_parcels(signplans_df: pd.DataFrame, signplans_geoms: list[dict], in_sr: int) -> pd.DataFrame:
    if signplans_df is None or signplans_df.empty or not signplans_geoms:
        return signplans_df

    joined_rows = []
    for geom in signplans_geoms:
        joined_rows.append(_parcel_intersect_first(geom, in_sr=in_sr))

    parcels_df = pd.DataFrame(joined_rows)
    # Align row counts; if mismatch, just return original
    if len(parcels_df) != len(signplans_df):
        return signplans_df

    out = pd.concat([signplans_df.reset_index(drop=True), parcels_df.reset_index(drop=True)], axis=1)
    return out


# ----------------------
# Lat/Lon + KML export helpers
# ----------------------

def _geom_to_lonlat(geom: dict):
    """
    Convert an ArcGIS geometry dict (already in outSR=4326) into (lon, lat).
    Supports points, polygons, and polylines (uses a simple centroid/average).
    """
    if not geom or not isinstance(geom, dict):
        return None, None

    # point
    if "x" in geom and "y" in geom:
        return float(geom["x"]), float(geom["y"])

    # polygon
    if "rings" in geom and geom["rings"]:
        ring = geom["rings"][0] or []
        if not ring:
            return None, None
        xs = [p[0] for p in ring if isinstance(p, (list, tuple)) and len(p) >= 2]
        ys = [p[1] for p in ring if isinstance(p, (list, tuple)) and len(p) >= 2]
        if not xs or not ys:
            return None, None
        return float(sum(xs) / len(xs)), float(sum(ys) / len(ys))

    # polyline
    if "paths" in geom and geom["paths"]:
        path = geom["paths"][0] or []
        xs = [p[0] for p in path if isinstance(p, (list, tuple)) and len(p) >= 2]
        ys = [p[1] for p in path if isinstance(p, (list, tuple)) and len(p) >= 2]
        if not xs or not ys:
            return None, None
        return float(sum(xs) / len(xs)), float(sum(ys) / len(ys))

    return None, None


def add_latlon_from_geometry(layer_url: str, df: pd.DataFrame, oid_field: str = "OBJECTID") -> pd.DataFrame:
    """
    Ensures df has LON/LAT columns by re-fetching geometry (outSR=4326) by OBJECTID.
    This is crucial because some layers don't expose LON/LAT as attributes, and joins/export
    must keep coordinates no matter how the records were found.
    """
    if df is None or df.empty:
        return df

    # If LON/LAT already exist and have at least some non-null values, keep them.
    if "LON" in df.columns and "LAT" in df.columns:
        try:
            if pd.to_numeric(df["LON"], errors="coerce").notna().any() and pd.to_numeric(df["LAT"], errors="coerce").notna().any():
                return df
        except Exception:
            pass

    if oid_field not in df.columns:
        return df

    # Pull OBJECTIDs
    oids = []
    for v in df[oid_field].tolist():
        s = digits_only(str(v))
        if s:
            oids.append(int(s))
    if not oids:
        return df

    # Re-fetch geometry in WGS84
    _, geoms = fetch_with_geometry_by_ids(layer_url, oids, out_sr=4326)

    # Build mapping oid -> (lon,lat)
    lon_map = {}
    lat_map = {}
    for oid, g in zip(oids, geoms or []):
        lon, lat = _geom_to_lonlat(g)
        if lon is not None and lat is not None:
            lon_map[oid] = lon
            lat_map[oid] = lat

    out = df.copy()
    out["_OID_TMP_"] = pd.to_numeric(out[oid_field], errors="coerce").astype("Int64")
    out["LON"] = out["_OID_TMP_"].map(lon_map)
    out["LAT"] = out["_OID_TMP_"].map(lat_map)
    out.drop(columns=["_OID_TMP_"], inplace=True, errors="ignore")
    return out


def _kml_color_from_code(code):
    """
    Accepts: 'red', '#RRGGBB', 'RRGGBB' and returns KML ABGR 'aabbggrr'
    """
    if code is None or (isinstance(code, float) and pd.isna(code)) or str(code).strip() == "":
        return "ff0000ff"  # opaque red

    c = str(code).strip().lower()
    named = {
        "red": "ff0000ff",
        "blue": "ffff0000",
        "green": "ff00ff00",
        "yellow": "ff00ffff",
        "purple": "ffff00ff",
        "orange": "ff00a5ff",
        "black": "ff000000",
        "white": "ffffffff",
        "gray": "ff808080",
        "grey": "ff808080",
    }
    if c in named:
        return named[c]

    c = c.lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{6}", c):
        rr, gg, bb = c[0:2], c[2:4], c[4:6]
        return f"ff{bb}{gg}{rr}"

    return "ff0000ff"


def _icon_href_from_code(code):
    """
    Use a *different icon image* per color so Google My Maps / other viewers show color reliably.
    """
    ICON_BY_NAME = {
        "red":   "http://maps.google.com/mapfiles/kml/paddle/red-circle.png",
        "blue":  "http://maps.google.com/mapfiles/kml/paddle/blu-circle.png",
        "green": "http://maps.google.com/mapfiles/kml/paddle/grn-circle.png",
        "yellow":"http://maps.google.com/mapfiles/kml/paddle/ylw-circle.png",
        "purple":"http://maps.google.com/mapfiles/kml/paddle/purple-circle.png",
        "orange":"http://maps.google.com/mapfiles/kml/paddle/orange-circle.png",
        "white": "http://maps.google.com/mapfiles/kml/paddle/wht-circle.png",
        "black": "http://maps.google.com/mapfiles/kml/paddle/blk-circle.png",
        "gray":  "http://maps.google.com/mapfiles/kml/paddle/wht-circle.png",
        "grey":  "http://maps.google.com/mapfiles/kml/paddle/wht-circle.png",
    }

    if code is None or (isinstance(code, float) and pd.isna(code)) or str(code).strip() == "":
        return ICON_BY_NAME["red"]

    c = str(code).strip().lower()
    if c in ICON_BY_NAME:
        return ICON_BY_NAME[c]

    # If hex, map roughly by dominant channel
    c2 = c.lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{6}", c2):
        r = int(c2[0:2], 16); g = int(c2[2:4], 16); b = int(c2[4:6], 16)
        if r >= g and r >= b:
            return ICON_BY_NAME["red"]
        if g >= r and g >= b:
            return ICON_BY_NAME["green"]
        return ICON_BY_NAME["blue"]

    return ICON_BY_NAME["red"]


def df_to_kml(
    df: pd.DataFrame,
    out_path: str,
    *,
    lon_field: str = "LON",
    lat_field: str = "LAT",
    name_field: str = "Billboard ID",
    color_field: str = "Pin Color Code",
    balloon_fields: list[str] | None = None,
    fixed_color: str | None = None,
    document_name: str = "Export"
) -> str:
    """
    Export a DataFrame (with lon/lat) to KML using icon-per-color styles.

    - name_field defaults to "Billboard ID" for unique placemark names
    - if fixed_color is provided, all pins use that color (ignores color_field)
    - balloon_fields controls the popup table
    """
    if df is None or df.empty:
        raise ValueError("No rows to export.")

    if lon_field not in df.columns or lat_field not in df.columns:
        raise ValueError(f"Missing {lon_field}/{lat_field} columns. Ensure lat/lon were added before KML export.")

    d = df.copy()
    d[lon_field] = pd.to_numeric(d[lon_field], errors="coerce")
    d[lat_field] = pd.to_numeric(d[lat_field], errors="coerce")
    d = d.dropna(subset=[lon_field, lat_field])

    if d.empty:
        raise ValueError("No valid rows with coordinates (lon/lat).")

    # Determine balloon fields
    if balloon_fields is None:
        balloon_fields = [c for c in [
            name_field,
            "STREET_NUM", "STREET_DIR", "STREET_NAM",
            "PARCEL", "APPLICANT", "APPLY_DATE",
            color_field
        ] if c in d.columns]

    import xml.sax.saxutils as saxutils

    def esc(x):
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return ""
        return saxutils.escape(str(x))

    def placemark_name(row):
        if name_field in row.index and str(row[name_field]).strip() not in ("", "nan", "None"):
            return str(row[name_field]).strip()
        # fallback
        if "LVBOARDS_" in row.index and str(row["LVBOARDS_"]).strip() not in ("", "nan", "None"):
            return f"Billboard {row['LVBOARDS_']}"
        if "OBJECTID" in row.index:
            return f"ID {row['OBJECTID']}"
        return "Placemark"

    def balloon_html(row):
        rows = []
        for col in balloon_fields:
            if col in row.index:
                val = row[col]
                if val is None or (isinstance(val, float) and pd.isna(val)):
                    val = ""
                rows.append(f"<tr><td><b>{esc(col)}</b></td><td>{esc(val)}</td></tr>")
        return "<table border='1' cellpadding='4' cellspacing='0'>" + "".join(rows) + "</table>"

    # Build styles keyed by (kml_color, icon_href)
    styles = {}
    if fixed_color:
        codes = [fixed_color]
    else:
        codes = d[color_field].fillna("").astype(str).tolist() if color_field in d.columns else [""]

    for v in codes:
        kmlc = _kml_color_from_code(v)
        href = _icon_href_from_code(v)
        key = (kmlc, href)
        if key not in styles:
            styles[key] = f"style_{kmlc}_{abs(hash(href)) % 10_000_000}"

    kml_parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        "<Document>",
        f"<name>{esc(document_name)}</name>",
    ]

    for (kmlc, href), sid in styles.items():
        kml_parts += [
            f'<Style id="{sid}">',
            "<IconStyle>",
            f"<color>{kmlc}</color>",
            "<scale>1.1</scale>",
            f"<Icon><href>{esc(href)}</href></Icon>",
            "</IconStyle>",
            "</Style>",
        ]

    for _, row in d.iterrows():
        lon = row[lon_field]; lat = row[lat_field]
        nm = placemark_name(row)
        desc = balloon_html(row)

        if fixed_color:
            v = fixed_color
        else:
            v = row[color_field] if color_field in row.index else ""
        kmlc = _kml_color_from_code(v)
        href = _icon_href_from_code(v)
        sid = styles.get((kmlc, href))

        kml_parts += [
            "<Placemark>",
            f"<name>{esc(nm)}</name>",
            (f"<styleUrl>#{sid}</styleUrl>" if sid else ""),
            f"<description><![CDATA[{desc}]]></description>",
            "<Point>",
            f"<coordinates>{lon},{lat},0</coordinates>",
            "</Point>",
            "</Placemark>",
        ]

    kml_parts += ["</Document>", "</kml>"]

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join([p for p in kml_parts if p != ""]))

    return out_path
