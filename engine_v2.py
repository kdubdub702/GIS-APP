import re
import requests
import pandas as pd

UA = {"User-Agent": "Mozilla/5.0"}

# Use the EXACT working query endpoint you validated
BILLBOARDS_QUERY = "https://services1.arcgis.com/F1v0ufATbBQScMtY/ArcGIS/rest/services/CLV_Billboards/FeatureServer/3/query"
PARCELS_QUERY    = "https://services1.arcgis.com/F1v0ufATbBQScMtY/arcgis/rest/services/CC_PARCELS_SHP/FeatureServer/257/query"

DEFAULT_OUT_SR = 4326  # WGS84 (lon/lat) so KML works directly


def digits_only(s: str) -> str:
    return re.sub(r"\D+", "", s or "")


def safe_sql(s: str) -> str:
    return (s or "").replace("'", "''").strip()


def arcgis_get_json(url: str, params: dict) -> dict:
    r = requests.get(url, params=params, headers=UA, timeout=60)
    r.raise_for_status()
    j = r.json()
    if "error" in j:
        raise RuntimeError(j["error"])
    return j


def _extract_lon_lat_from_geometry(geom: dict):
    """Extract lon/lat from ArcGIS point geometry (after requesting outSR=4326)."""
    if not geom or not isinstance(geom, dict):
        return None, None
    # Point geometry
    x = geom.get("x")
    y = geom.get("y")
    if x is not None and y is not None:
        return float(x), float(y)
    # If a future layer returns {"longitude":...,"latitude":...}
    lon = geom.get("longitude") or geom.get("lon")
    lat = geom.get("latitude") or geom.get("lat")
    if lon is not None and lat is not None:
        return float(lon), float(lat)
    return None, None


def fetch_by_objectids(
    query_url: str,
    object_ids: list[int],
    out_fields="*",
    chunk_size=200,
    *,
    include_geometry: bool = False,
    out_sr: int = DEFAULT_OUT_SR,
) -> pd.DataFrame:
    rows = []
    for i in range(0, len(object_ids), chunk_size):
        chunk = object_ids[i:i + chunk_size]
        params = {
            "f": "pjson",
            "objectIds": ",".join(str(x) for x in chunk),
            "outFields": out_fields,
            "returnGeometry": "true" if include_geometry else "false",
        }
        if include_geometry:
            params["outSR"] = str(out_sr)

        j = arcgis_get_json(query_url, params)
        feats = j.get("features", [])
        for f in feats:
            attrs = f.get("attributes", {}) or {}
            if include_geometry:
                lon, lat = _extract_lon_lat_from_geometry(f.get("geometry") or {})
                if lon is not None and lat is not None:
                    attrs["LONGITUDE"] = lon
                    attrs["LATITUDE"] = lat
            rows.append(attrs)
    return pd.DataFrame(rows)


def fetch_ids_where(query_url: str, where: str) -> list[int]:
    params = {
        "f": "pjson",
        "where": where,
        "returnIdsOnly": "true",
        "returnGeometry": "false",
    }
    j = arcgis_get_json(query_url, params)
    return j.get("objectIds") or []


# ----------------------
# Billboards searches
# ----------------------

def billboards_objectid_exact(object_id: str, *, include_geometry: bool = True) -> pd.DataFrame:
    oid = digits_only(object_id)
    if not oid:
        raise ValueError("Enter an ObjectID (digits).")
    return fetch_by_objectids(
        BILLBOARDS_QUERY,
        [int(oid)],
        out_fields="*",
        chunk_size=200,
        include_geometry=include_geometry,
    )


def billboards_objectid_range(start_id: str, end_id: str, oid_field: str = "OBJECTID", *, include_geometry: bool = True) -> pd.DataFrame:
    s = digits_only(start_id)
    e = digits_only(end_id)
    if not s or not e:
        raise ValueError("Enter Start and End ObjectID (digits).")
    s_i, e_i = int(s), int(e)
    if e_i < s_i:
        s_i, e_i = e_i, s_i

    ids = fetch_ids_where(BILLBOARDS_QUERY, f"{oid_field} >= {s_i} AND {oid_field} <= {e_i}")
    if not ids:
        if oid_field != "OID":
            ids = fetch_ids_where(BILLBOARDS_QUERY, f"OID >= {s_i} AND OID <= {e_i}")
        if not ids:
            return pd.DataFrame()
    return fetch_by_objectids(
        BILLBOARDS_QUERY,
        ids,
        out_fields="*",
        chunk_size=200,
        include_geometry=include_geometry,
    )


def billboards_all(*, include_geometry: bool = True) -> pd.DataFrame:
    ids = fetch_ids_where(BILLBOARDS_QUERY, "1=1")
    if not ids:
        return pd.DataFrame()
    return fetch_by_objectids(
        BILLBOARDS_QUERY,
        ids,
        out_fields="*",
        chunk_size=200,
        include_geometry=include_geometry,
    )


def billboards_by_apn_partial(apn_prefix: str, *, include_geometry: bool = True) -> pd.DataFrame:
    apn = digits_only(apn_prefix)
    if not apn:
        raise ValueError("Enter an APN/PARCEL prefix (digits).")
    ids = fetch_ids_where(BILLBOARDS_QUERY, f"PARCEL LIKE '{apn}%'")
    if not ids:
        return pd.DataFrame()
    return fetch_by_objectids(BILLBOARDS_QUERY, ids, include_geometry=include_geometry)


def billboards_by_address_partial(street_num: str, street_dir: str, street_name: str, *, include_geometry: bool = True) -> pd.DataFrame:
    n = digits_only(street_num)
    d = (street_dir or "").strip().upper()
    nm = safe_sql(street_name)

    if not (n or nm):
        raise ValueError("Enter street name (partial) and/or street number.")

    parts = []
    if n:
        parts.append(f"(STREET_NUM={n} OR STREET_NUM='{n}')")
    if d:
        parts.append(f"STREET_DIR='{safe_sql(d)}'")
    if nm:
        parts.append(f"STREET_NAM LIKE '%{nm}%'")

    where = " AND ".join(parts)
    ids = fetch_ids_where(BILLBOARDS_QUERY, where)
    if not ids:
        return pd.DataFrame()
    return fetch_by_objectids(BILLBOARDS_QUERY, ids, include_geometry=include_geometry)


# ----------------------
# Parcel join
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
            dfs.append(fetch_by_objectids(PARCELS_QUERY, ids, out_fields="*", chunk_size=200, include_geometry=False))

    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()


def join_billboards_to_parcels(bb: pd.DataFrame) -> pd.DataFrame:
    if bb is None or bb.empty or "PARCEL" not in bb.columns:
        return bb
    parcels = parcels_by_parcel_ids(bb["PARCEL"].astype(str).tolist())
    if parcels.empty or "PARCEL" not in parcels.columns:
        return bb
    return bb.merge(parcels, on="PARCEL", how="left", suffixes=("_BILLBOARD", "_PARCEL"))
