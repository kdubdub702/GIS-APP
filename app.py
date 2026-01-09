import re
import requests
import pandas as pd
import streamlit as st

# ----------------------------
# Endpoints (your known sources)
# ----------------------------
LV_ADDR_LOCATOR = "https://mapdata.lasvegasnevada.gov/clvgis/rest/services/CCPARCELS_Address_Locator/GeocodeServer/findAddressCandidates"
LV_PARCEL_LOCATOR = "https://mapdata.lasvegasnevada.gov/clvgis/rest/services/CCPARCELS_ParcelNumber_Locator/GeocodeServer/findAddressCandidates"

SIGNS_QUERY = "https://mapdata.lasvegasnevada.gov/clvgis/rest/services/DevelopmentServices/Zoning/MapServer/2/query"
ASSESSOR_PARCELS_QUERY = "https://maps.clarkcountynv.gov/arcgis/rest/services/GISMO/AssessorMapv2/FeatureServer/1/query"


def _clean_apn(text: str) -> str:
    """Keep digits only; many APNs are numeric strings."""
    if not text:
        return ""
    return re.sub(r"\D+", "", text)


def geocode_address_to_candidates(single_line: str, max_locations: int = 5) -> dict:
    params = {
        "SingleLine": single_line,
        "outFields": "*",
        "maxLocations": max_locations,
        "f": "pjson",
    }
    r = requests.get(LV_ADDR_LOCATOR, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def locate_apn_candidates(apn: str, max_locations: int = 5) -> dict:
    params = {
        "SingleKey": apn,
        "outFields": "*",
        "maxLocations": max_locations,
        "f": "pjson",
    }
    r = requests.get(LV_PARCEL_LOCATOR, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def query_feature_service(url: str, where: str, out_fields: str = "*", return_geometry: bool = False) -> pd.DataFrame:
    params = {
        "where": where,
        "outFields": out_fields,
        "returnGeometry": "true" if return_geometry else "false",
        "f": "pjson",
    }
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    data = r.json()

    feats = data.get("features", [])
    rows = [f.get("attributes", {}) for f in feats]
    return pd.DataFrame(rows)


def pick_apn_from_candidates(candidates_json: dict) -> str:
    """
    The locator candidate attributes can vary. We try common keys.
    If you see a different key in your JSON, add it here.
    """
    candidates = candidates_json.get("candidates", [])
    if not candidates:
        return ""

    attr = candidates[0].get("attributes", {})  # take best match
    for key in ["APN", "PARCEL", "Parcel", "parcel", "apn", "Apn"]:
        if key in attr and attr[key]:
            return _clean_apn(str(attr[key]))

    # fallback: sometimes locator returns address only; no APN
    return ""


st.set_page_config(page_title="LV Signs + Assessor Join", layout="wide")
st.title("Las Vegas Off-Premise Signs + Assessor Parcel Join")

st.markdown(
    "Enter an **Address** or an **APN/Parcel**. The app resolves an APN, "
    "pulls **Off-Premise Signs** + **Assessor Parcels** data, joins by APN, and exports CSV."
)

col1, col2 = st.columns(2)
with col1:
    address = st.text_input("Address (single line)", value="2234 W Mesquite Ave, Las Vegas, NV")
with col2:
    apn_input = st.text_input("APN / Parcel (digits only preferred)", value="13929801009")

run = st.button("Search")

if run:
    try:
        apn = _clean_apn(apn_input)

        # 1) Resolve APN from address if APN not provided
        if not apn and address.strip():
            cand = geocode_address_to_candidates(address.strip())
            apn = pick_apn_from_candidates(cand)
            st.subheader("Address candidates (top match)")
            st.json(cand.get("candidates", [])[:1])

        # 2) If still no APN, try parcel locator if user gave something
        if not apn and apn_input.strip():
            cand2 = locate_apn_candidates(_clean_apn(apn_input))
            apn = pick_apn_from_candidates(cand2)
            st.subheader("Parcel locator candidates (top match)")
            st.json(cand2.get("candidates", [])[:1])

        if not apn:
            st.error("Could not resolve an APN. Try adding ZIP (e.g., 89106) or enter a known APN.")
            st.stop()

        st.success(f"Using APN/PARCEL: {apn}")

        # 3) Query Off-Premise Signs by PARCEL
        signs_df = query_feature_service(SIGNS_QUERY, where=f"PARCEL='{apn}'", out_fields="*")
        st.subheader("Off-Premise Signs results")
        st.write(signs_df)

        # 4) Query Assessor Parcels by APN
        assessor_df = query_feature_service(ASSESSOR_PARCELS_QUERY, where=f"APN='{apn}'", out_fields="*")
        st.subheader("Assessor Parcels results")
        st.write(assessor_df)

        # 5) Join (one parcel -> many signs)
        # If either is empty, still produce something useful.
        if assessor_df.empty and signs_df.empty:
            st.warning("No parcel and no sign records found for that APN.")
            st.stop()

        if assessor_df.empty:
            joined = signs_df.copy()
            joined["APN_JOIN_KEY"] = apn
        elif signs_df.empty:
            joined = assessor_df.copy()
            joined["APN_JOIN_KEY"] = apn
        else:
            # Repeat parcel fields per sign row
            parcel_row = assessor_df.iloc[0].to_dict()
            parcel_df = pd.DataFrame([parcel_row] * len(signs_df))
            joined = pd.concat([parcel_df.reset_index(drop=True), signs_df.reset_index(drop=True)], axis=1)
            joined["APN_JOIN_KEY"] = apn

        st.subheader("Joined output (parcel fields repeated per sign row)")
        st.write(joined)

        csv_bytes = joined.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="Download CSV",
            data=csv_bytes,
            file_name=f"lv_signs_assessor_join_{apn}.csv",
            mime="text/csv",
        )

    except requests.HTTPError as e:
        st.error(f"HTTP error: {e}")
    except Exception as e:
        st.error(f"Unexpected error: {e}")
