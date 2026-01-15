# datasets.py

DATASETS = {
    "Las Vegas – Billboards": {
        "layer_url": "https://services1.arcgis.com/F1v0ufATbBQScMtY/ArcGIS/rest/services/CLV_Billboards/FeatureServer/3",
        "oid_field": "OBJECTID",
        "search": {
            "apn_field": "PARCEL",
            "address_field": ("STREET_NUM", "STREET_DIR", "STREET_NAM"),
        },
        "join": {"type": "field", "left": "PARCEL", "right": "PARCEL"},
        "notes": "Direct parcel join via PARCEL",
    },

    "Henderson – STVR Licenses": {
        "layer_url": "https://maps.cityofhenderson.com/arcgis/rest/services/public/ComDevServices/MapServer/1",
        "oid_field": "OBJECTID",
        "search": {
            "apn_field": "PARCEL",
            "address_field_single": "REGISTERED_ADDRESS",
        },
        "join": {"type": "field", "left": "PARCEL", "right": "PARCEL"},
        "notes": "Direct parcel join via PARCEL",
    },

    "Henderson – Sign Plans": {
        "layer_url": "https://maps.cityofhenderson.com/arcgis/rest/services/public/ComDevServices/MapServer/5",
        "oid_field": "OBJECTID",
        "search": {
            "address_field_single": "MAIN_ADDRESS_LINE1",
            "spatial_fields": ("SPATIALTYPE", "SPATIALID"),
        },
        # Join is TBD: may be SPATIALID if it represents a parcel, otherwise spatial/address join later
        "join": {"type": "tbd"},
        "notes": "No PARCEL field; join needs SPATIALID/SPATIALTYPE validation or spatial intersect.",
    },

    "North Las Vegas – (coming next)": {
        "layer_url": None,
        "oid_field": "OBJECTID",
        "search": {},
        "join": {"type": "tbd"},
        "notes": "Staged; will wire when we locate NLV sign/billboard layer.",
    },

    "Clark County – (coming next)": {
        "layer_url": None,
        "oid_field": "OBJECTID",
        "search": {},
        "join": {"type": "tbd"},
        "notes": "Staged; will wire additional county layers later.",
    },
}
