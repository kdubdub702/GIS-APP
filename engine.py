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
    r = requests.get(query_url, params=params, headers=UA, timeout=90)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}\nURL: {r.url}\nBody: {r.text[:600]}")
    j = r.json()
    if "error" in j:
        raise RuntimeError(j["error"])
    return j


# ----------------------
# Core ArcGIS fetchers
# ----------------------

def fetch_ids_where(query_url: str, where: str) -> list[int]:
    j = arcgis_get_json(query_url, {
        "f": "pjson",
        "where": where,
        "returnIdsOnly": "true",
        "returnGeometry": "false",
    })
    return j.get("objectIds") or []

def fetch_by_objectids(
    query_url: str,
    object_ids: list[int],
    out_fields="*",
    chunk_size=200,
    return_geometry: bool = False,
    out_sr: int | None = None,
):
    rows = []
    geoms = [] if return_geometry else None

    for i in range(0, len(object_ids), chunk_size):
        chunk = object_ids[i:i + chunk_size]
        params = {
            "f": "pjson",
            "objectIds": ",".join(str(x) for x in chunk),
            "outFields": out_fields,
            "returnGeometry": "true" if return_geometry else "false",
        }
        if out_sr is not None:
            params["outSR"] = str(out_sr)

        j = arcgis_get_json(query_url, params)
        feats = j.get("features", [])
        for f in feats:
            rows.append(f.get("attributes", {}) or {})
            if return_geometry:
                geoms.append(f.get("geometry"))

    df = pd.DataFrame(rows)
    return (df, geoms) if return_geometry else df

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
    return fetch_by_objectids(q, [int(oid)], out_fields="*", chunk_size=200)

def objectid_range(layer_url: str, start_id: str, end_id: str, oid_field: str = "OBJECTID"):
    s = digits_only(start_id)
    e = digits_only(end_id)
    if not s or not e:
        raise ValueError("Enter Start and End ObjectID (digits).")
    s_i, e_i = int(s), int(e)
    if e_i < s_i:
        s_i, e_i = e_i, s_i

    q = layer_query_url(layer_url)
    ids = fetch_ids_where(q, f"{oid_field} >= {s_i} AND {oid_field} <= {e_i}")
    if not ids and oid_field != "OID":
        ids = fetch_ids_where(q, f"OID >= {s_i} AND OID <= {e_i}")
    if not ids:
        return pd.DataFrame()
    return fetch_by_objectids(q, ids, out_fields="*", chunk_size=200)

def fetch_all(layer_url: str, where: str = "1=1"):
    q = layer_query_url(layer_url)
    ids = fetch_ids_where(q, where)
    if not ids:
        return pd.DataFrame()
    return fetch_by_objectids(q, ids, out_fields="*", chunk_size=200)

def fetch_all_with_geometry(layer_url: str, where: str = "1=1", out_sr: int | None = None):
    q = layer_query_url(layer_url)
    ids = fetch_ids_where(q, where)
    if not ids:
        return pd.DataFrame(), []
    return fetch_by_objectids(q, ids, out_fields="*", chunk_size=200, return_geometry=True, out_sr=out_sr)

def apn_partial(layer_url: str, apn_field: str, apn_prefix: str):
    apn = digits_only(apn_prefix)
    if not apn:
        raise ValueError("Enter an APN/PARCEL prefix (digits).")
    q = layer_query_url(layer_url)
    ids = fetch_ids_where(q, f"{apn_field} LIKE '{apn}%'")
    if not ids:
        return pd.DataFrame()
    return fetch_by_objectids(q, ids, out_fields="*", chunk_size=200)

def address_partial_split(
    layer_url: str,
    street_num: str,
    street_dir: str,
    street_name: str,
    field_num: str,
    field_dir: str,
    field_name: str,
):
    n = digits_only(street_num)
    d = (street_dir or "").strip().upper()
    nm = safe_sql(street_name)

    if not (n or nm):
        raise ValueError("Enter street name (partial) and/or street number.")

    parts = []
    if n:
        parts.append(f"({field_num}={n} OR {field_num}='{n}')")
    if d:
        parts.append(f"{field_dir}='{safe_sql(d)}'")
    if nm:
        parts.append(f"{field_name} LIKE '%{nm}%'")

    where = " AND ".join(parts)
    q = layer_query_url(layer_url)
    ids = fetch_ids_where(q, where)
    if not ids:
        return pd.DataFrame()
    return fetch_by_objectids(q, ids, out_fields="*", chunk_size=200)

def address_partial_single(layer_url: str, address_field: str, address_text: str):
    txt = safe_sql(address_text)
    if not txt:
        raise ValueError("Enter an address (partial).")
    q = layer_query_url(layer_url)
    ids = fetch_ids_where(q, f"{address_field} LIKE '%{txt}%'")
    if not ids:
        return pd.DataFrame()
    return fetch_by_objectids(q, ids, out_fields="*", chunk_size=200)


# ----------------------
# Parcel join helpers (field join)
# ----------------------

def parcels_by_parcel_ids(parcel_ids: list[str]) -> pd.DataFrame:
    vals = sorted(set(digits_only(x) for x in parcel_ids if digits_only(x)))
    if not vals:
        return pd.DataFrame()

    CHUNK = 200
    dfs = []
    for i in range(0, len(vals), CHUNK):
        chunk = vals[i:i + CHUNK]
        in_list = ",".join(f"'{c}'" for c in chunk)
        ids = fetch_ids_where(PARCELS_QUERY, f"PARCEL IN ({in_list})")
        if ids:
            dfs.append(fetch_by_objectids(PARCELS_QUERY, ids, out_fields="*", chunk_size=200))
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

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

    parcel_rows = []
    for g in signplans_geoms:
        parcel_rows.append(_parcel_intersect_first(g, in_sr=in_sr))
    parcels_df = pd.DataFrame(parcel_rows)

    # Avoid column collisions by suffixing parcel fields if needed
    for c in list(parcels_df.columns):
        if c in signplans_df.columns:
            parcels_df.rename(columns={c: f"{c}_PARCEL"}, inplace=True)

    return pd.concat([signplans_df.reset_index(drop=True), parcels_df.reset_index(drop=True)], axis=1)
