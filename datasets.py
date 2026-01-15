# datasets.py

DATASETS = {
    "Las Vegas – Billboards": {
        "layer_url": "https://services1.arcgis.com/F1v0ufATbBQScMtY/ArcGIS/rest/services/CLV_Billboards/FeatureServer/3",
        "oid_field": "OBJECTID",
        "mode_support": ["address", "apn", "oid_exact", "oid_range", "all"],
        "apn_field": "PARCEL",
        # LV address is split into 3 fields
        "addr_fields": ("STREET_NUM", "STREET_DIR", "STREET_NAM"),
        "addr_single_field": None,
        "join_enabled": True,
        "join_left_field": "PARCEL",
    },

    "Henderson – STVR Licenses": {
        "layer_url": "https://maps.cityofhenderson.com/arcgis/rest/services/public/ComDevServices/MapServer/1",
        "oid_field": "OBJECTID",
        "mode_support": ["address", "apn", "oid_exact", "oid_range", "all"],
        "apn_field": "PARCEL",
        # STVR address is a single string field
        "addr_fields": None,
        "addr_single_field": "REGISTERED_ADDRESS",
        "join_enabled": True,
        "join_left_field": "PARCEL",
    },

    "Henderson – Sign Plans": {
        "layer_url": "https://maps.cityofhenderson.com/arcgis/rest/services/public/ComDevServices/MapServer/5",
        "oid_field": "OBJECTID",
        "mode_support": ["address", "oid_exact", "oid_range", "all"],
        "apn_field": None,  # no PARCEL/APN field in this layer
        "addr_fields": None,
        "addr_single_field": "MAIN_ADDRESS_LINE1",
        "join_enabled": False,  # v1: search + export only
        "join_left_field": None,
    },

    "North Las Vegas – (coming next)": {
        "layer_url": None,
        "oid_field": "OBJECTID",
        "mode_support": [],
        "apn_field": None,
        "addr_fields": None,
        "addr_single_field": None,
        "join_enabled": False,
        "join_left_field": None,
    },

    "Clark County – (coming next)": {
        "layer_url": None,
        "oid_field": "OBJECTID",
        "mode_support": [],
        "apn_field": None,
        "addr_fields": None,
        "addr_single_field": None,
        "join_enabled": False,
        "join_left_field": None,
    },
}
