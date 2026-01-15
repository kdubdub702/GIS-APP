import re
import requests
import pandas as pd

UA = {"User-Agent": "Mozilla/5.0"}

# Reuse your existing Clark County parcel layer (you already validated this works)
PARCELS_QUERY = "https://services1.arcgis.com/F1v0ufATbBQScMtY/arcgis/rest/services/CC_PARCELS_SHP/FeatureServer/257/query"

def digits_only(s: str) -> str:
    return re.sub(r"\D+", "", s or "")

def safe_sql(s: str) -> str:
    return (s or "").replace("'", "''").strip()

def layer_query_url(layer_url: str) -> str:
    # Accept ".../FeatureServer/3" OR ".../MapServer/1"
    base = layer_url.rstrip("/")
    if base.lower().endswith("/query"):
        return base
    return base + "/query"

def arcgis_get_json(query_url: str, params: dict) -> dict:
    r = requests.get(query_url, params=params, headers=UA, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}\nURL: {r.url}\nBody: {r.text[:300]}")
    j = r.json()
    if "error" in j:
        raise RuntimeError(j["error"])
    return j

def fetch_ids_where(query_url: str, where: str) -> list[int]:
    params = {
        "f": "pjson",
        "where": where,
        "returnIdsOnly": "true",
        "returnGeometry": "false",
    }
    j = arcgis_get_json(query_url, params)
    return j.get("objectIds") or []

def fetch_by_objectids(query_url: str, object_ids: list[int], out_fields="*", chunk_size=200) -> pd.DataFrame:
    rows = []
    for i in range(0, len(object_ids), chunk_size):
        chunk = object_ids[i:i+chunk_size]
        params = {
            "f": "pjson",
            "objectIds": ",".join(str(x) for x in chunk),
            "outFields": out_fields,
            "returnGeometry": "false",
        }
        j = arcgis_get_json(query_url, params)
        feats = j.get("features", [])
        rows.extend([f.get("attributes", {}) for f in feats])
    return pd.DataFrame(rows)

# ----------------------
# Generic searches (any layer)
# ----------------------

def objectid_exact(layer_url: str, object_id: str) -> pd.DataFrame:
    oid = digits_only(object_id)
    if not oid:
        raise ValueError("Enter an ObjectID (digits).")
    q = layer_query_url(layer_url)
    return fetch_by_objectids(q, [int(oid)], out_fields="*", chunk_size=200)

def objectid_range(layer_url: str, start_id: str, end_id: str, oid_field: str = "OBJECTID") -> pd.DataFrame:
    s = digits_only(start_id)
    e = digits_only(end_id)
    if not s or not e:
        raise ValueError("Enter Start and End ObjectID (digits).")
    s_i, e_i = int(s), int(e)
    if e_i < s_i:
        s_i, e_i = e_i, s_i

    q = layer_query_url(layer_url)
    ids = fetch_ids_where(q, f"{oid_field} >= {s_i} AND {oid_field} <= {e_i}")
    if not ids:
        # Some layers might use OID
        if oid_field != "OID":
            ids = fetch_ids_where(q, f"OID >= {s_i} AND OID <= {e_i}")
        if not ids:
            return pd.DataFrame()
    return fetch_by_objectids(q, ids, out_fields="*", chunk_size=200)

def fetch_all(layer_url: str) -> pd.DataFrame:
    q = layer_query_url(layer_url)
    ids = fetch_ids_where(q, "1=1")
    if not ids:
        return pd.DataFrame()
    return fetch_by_objectids(q, ids, out_fields="*", chunk_size=200)

def apn_partial(layer_url: str, apn_field: str, apn_prefix: str) -> pd.DataFrame:
    apn = digits_only(apn_prefix)
    if not apn:
        raise ValueError("Enter an APN/PARCEL prefix (digits).")
    q = layer_query_url(layer_url)
    ids = fetch_ids_where(q, f"{apn_field} LIKE '{apn}%'")
    if not ids:
        return pd.DataFrame()
    return fetch_by_objectids(q, ids, out_fields="*", chunk_size=200)

def address_partial_split(layer_url: str, street_num: str, street_dir: str, street_name: str,
                          field_num: str, field_dir: str, field_name: str) -> pd.DataFrame:
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

def address_partial_single(layer_url: str, address_field: str, address_text: str) -> pd.DataFrame:
    txt = safe_sql(address_text)
    if not txt:
        raise ValueError("Enter an address (partial).")
    q = layer_query_url(layer_url)
    ids = fetch_ids_where(q, f"{address_field} LIKE '%{txt}%'")
    if not ids:
        return pd.DataFrame()
    return fetch_by_objectids(q, ids, out_fields="*", chunk_size=200)

# ----------------------
# Parcel join (same as you had, generalized)
# ----------------------

def parcels_by_parcel_ids(parcel_ids: list[str]) -> pd.DataFrame:
    vals = sorted(set(digits_only(x) for x in parcel_ids if digits_only(x)))
    if not vals:
        return pd.DataFrame()

    CHUNK = 200
    dfs = []
    for i in range(0, len(vals), CHUNK):
        chunk = vals[i:i+CHUNK]
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
