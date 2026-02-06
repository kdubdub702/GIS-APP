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

def digits_only(s) -> str:
    """
    Return digits from any input type (str / int / float / None).
    Prevents regex crashes when pandas columns are numeric.
    """
    if s is None:
        return ""

    if isinstance(s, int):
        return str(s)

    if isinstance(s, float):
        if s.is_integer():
            return str(int(s))
        return re.sub(r"\D+", "", str(s))

    return re.sub(r"\D+", "", str(s))


def safe_sql(s) -> str:
    """
    SQL-safe string conversion tolerant of non-string inputs.
    """
    if s is None:
        return ""
    return str(s).replace("'", "''").strip()


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


# ----------------------
# Tiered owner enrichment (Billboards)
# ----------------------

OWNER_OUTFIELDS = "PARCEL,OWNER,ADDRESS,STRNO,STRNAME,STRTYPE,STRDIR,ZIP,SALEDATE,SALEPRICE,TAXDIST,LANDUSE,LANDVAL1,IMPVAL"

def _is_blank(v) -> bool:
    if v is None:
        return True
    s = str(v).strip()
    return (s == "" or s.lower() == "nan" or s.lower() == "none")

def _init_owner_meta(df: pd.DataFrame) -> None:
    for c in ("OWNER_MATCH_TYPE", "OWNER_MATCH_CONFIDENCE", "OWNER_MATCH_NOTES"):
        if c not in df.columns:
            df[c] = ""

def _mark_owner_meta(df: pd.DataFrame, mask, match_type: str, confidence: str, notes: str):
    if mask is None:
        return
    df.loc[mask, "OWNER_MATCH_TYPE"] = match_type
    df.loc[mask, "OWNER_MATCH_CONFIDENCE"] = confidence
    df.loc[mask, "OWNER_MATCH_NOTES"] = notes

def _parcel_intersect_point(point_geom: dict, in_sr: int, distance_ft: int = 15) -> dict:
    """Intersect a point against Clark County parcels with a small buffer distance."""
    if not point_geom or "x" not in point_geom or "y" not in point_geom:
        return {}

    j = arcgis_get_json(PARCELS_QUERY, {
        "f": "pjson",
        "geometry": json.dumps(point_geom),
        "geometryType": "esriGeometryPoint",
        "inSR": str(in_sr),
        "spatialRel": "esriSpatialRelIntersects",
        "distance": str(distance_ft),
        "units": "esriSRUnit_Foot",
        "outFields": OWNER_OUTFIELDS,
        "returnGeometry": "false",
        "resultRecordCount": "1",
    })
    feats = j.get("features") or []
    if not feats:
        return {}
    return (feats[0].get("attributes") or {})

def _parcel_intersect_polygon(poly_geom: dict, in_sr: int) -> dict:
    """Intersect a polygon against Clark County parcels."""
    if not poly_geom:
        return {}
    j = arcgis_get_json(PARCELS_QUERY, {
        "f": "pjson",
        "geometry": json.dumps(poly_geom),
        "geometryType": "esriGeometryPolygon",
        "inSR": str(in_sr),
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": OWNER_OUTFIELDS,
        "returnGeometry": "false",
        "resultRecordCount": "1",
    })
    feats = j.get("features") or []
    if not feats:
        return {}
    return (feats[0].get("attributes") or {})

def _parcel_by_address(street_num: str, street_dir: str, street_name: str) -> dict:
    """Best-effort address lookup in Clark County parcels."""
    n = digits_only(street_num)
    d = (street_dir or "").strip().upper()
    nm = safe_sql(street_name).upper()

    if not (n and nm):
        return {}

    parts = [f"(STRNO={n} OR STRNO='{n}')", f"UPPER(STRNAME) LIKE '%{nm}%'"]
    if d:
        parts.append(f"UPPER(STRDIR)='{safe_sql(d)}'")
    where = " AND ".join(parts)

    ids = fetch_ids_where(PARCELS_QUERY, where)
    if not ids:
        return {}

    # Fetch first match only to keep it fast
    df = fetch_by_objectids(PARCELS_QUERY, [ids[0]], out_fields=OWNER_OUTFIELDS, chunk_size=200)
    if df is None or df.empty:
        return {}
    return (df.iloc[0].to_dict() if hasattr(df, "iloc") else {})

def enrich_billboards_with_owner(
    billboards_df: pd.DataFrame,
    billboards_geoms: list[dict] | None,
    *,
    parcel_field: str = "PARCEL",
    in_sr: int = 3421,
    use_spatial_fallback: bool = True,
    use_address_fallback: bool = True,
) -> pd.DataFrame:
    """Tiered owner enrichment:
    1) APN/PARCEL field join (HIGH)
    2) Spatial intersect fallback (MEDIUM)
    3) Address fallback (LOW)
    """
    if billboards_df is None or billboards_df.empty:
        return billboards_df

    df = billboards_df.copy()
    _init_owner_meta(df)

    # --- Tier 1: APN exact join (field join) ---
    df = join_to_parcels(df, left_field=parcel_field)

    if "OWNER" in df.columns:
        has_owner = ~df["OWNER"].apply(_is_blank)
    else:
        df["OWNER"] = ""
        has_owner = pd.Series([False] * len(df))

    _mark_owner_meta(df, has_owner, "APN", "HIGH", "Matched via APN/PARCEL exact join")

    # --- Tier 2: Spatial fallback for missing owners ---
    if use_spatial_fallback and billboards_geoms:
        missing_mask = df["OWNER"].apply(_is_blank).reset_index(drop=True)
        if missing_mask.any():
            spatial_rows = []
            for i, is_missing in enumerate(missing_mask.tolist()):
                if not is_missing:
                    spatial_rows.append({})
                    continue
                g = billboards_geoms[i] if i < len(billboards_geoms) else None
                if not g:
                    spatial_rows.append({})
                    continue
                if isinstance(g, dict) and ("x" in g and "y" in g):
                    spatial_rows.append(_parcel_intersect_point(g, in_sr=in_sr, distance_ft=15))
                else:
                    spatial_rows.append(_parcel_intersect_polygon(g, in_sr=in_sr))
            spatial_df = pd.DataFrame(spatial_rows)

            # Fill missing columns from spatial results (do not clobber existing non-blank values)
            for col in ["PARCEL", "OWNER", "ADDRESS", "STRNO", "STRNAME", "STRTYPE", "STRDIR", "ZIP",
                        "SALEDATE", "SALEPRICE", "TAXDIST", "LANDUSE", "LANDVAL1", "IMPVAL"]:
                if col in spatial_df.columns:
                    if col not in df.columns:
                        df[col] = None
                    fill_mask = missing_mask & spatial_df[col].apply(lambda v: not _is_blank(v))
                    df.loc[fill_mask, col] = spatial_df.loc[fill_mask, col].values

            updated = missing_mask & (~df["OWNER"].apply(_is_blank)).reset_index(drop=True)
            _mark_owner_meta(df, updated, "SPATIAL", "MEDIUM", "Matched via spatial intersect (buffered point)")

    # --- Tier 3: Address fallback for still-missing owners ---
    if use_address_fallback:
        still_missing = df["OWNER"].apply(_is_blank)
        needed = {"STREET_NUM", "STREET_DIR", "STREET_NAM"}
        if still_missing.any() and needed.issubset(set(df.columns)):
            addr_rows = []
            for _, row in df.iterrows():
                if still_missing.loc[row.name]:
                    addr_rows.append(_parcel_by_address(row.get("STREET_NUM", ""), row.get("STREET_DIR", ""), row.get("STREET_NAM", "")))
                else:
                    addr_rows.append({})
            addr_df = pd.DataFrame(addr_rows)

            for col in ["PARCEL", "OWNER", "ADDRESS", "STRNO", "STRNAME", "STRTYPE", "STRDIR", "ZIP",
                        "SALEDATE", "SALEPRICE", "TAXDIST", "LANDUSE", "LANDVAL1", "IMPVAL"]:
                if col in addr_df.columns:
                    if col not in df.columns:
                        df[col] = None
                    fill_mask = still_missing.reset_index(drop=True) & addr_df[col].apply(lambda v: not _is_blank(v))
                    df.loc[fill_mask, col] = addr_df.loc[fill_mask, col].values

            updated = still_missing & (~df["OWNER"].apply(_is_blank))
            _mark_owner_meta(df, updated, "ADDRESS", "LOW", "Matched via address best-effort (may be approximate)")

    # --- Final: label remaining as NONE ---
    final_missing = df["OWNER"].apply(_is_blank)
    _mark_owner_meta(df, final_missing, "NONE", "NONE", "No parcel match (ROW/easement/geometry mismatch or missing APN/address)")

    return df
