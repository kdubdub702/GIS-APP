# datasets.py
#
# Registry of ArcGIS layers the desktop app can query.
# Add new sources (North Las Vegas, Clark County, etc.) by extending DATASETS.

DATASETS = {
    "Las Vegas – Billboards": {
        "layer_url": "https://services1.arcgis.com/F1v0ufATbBQScMtY/ArcGIS/rest/services/CLV_Billboards/FeatureServer/3",
        "oid_field": "OBJECTID",
        "mode_support": ["address", "apn", "oid_exact", "oid_range", "all"],
        "apn_field": "PARCEL",
        "addr_fields": ("STREET_NUM", "STREET_DIR", "STREET_NAM"),  # split address
        "addr_single_field": None,
        "join": {
            "enabled_default": True,
            "type": "field",
            "left_field": "PARCEL",   # in city layer
        },
        "join_owner_strategy": "tiered",  # APN -> spatial -> address fallback
    },

    # NDOT statewide billboard inventory (separate from City of Las Vegas layer)
    # Service: https://gis.dot.nv.gov/arcgis/rest/services/Billboards_ProdMobile/FeatureServer/0
    "Nevada DOT – Billboards (NDOT)": {
        "layer_url": "https://gis.dot.nv.gov/arcgis/rest/services/Billboards_ProdMobile/FeatureServer/0",
        "oid_field": "OBJECTID",
        "mode_support": ["address", "oid_exact", "oid_range", "all"],
        "apn_field": None,
        "addr_fields": None,
        # NDOT uses a single address field called property_address (per layer metadata)
        "addr_single_field": "property_address",
        # Join disabled by default (Clark County parcels won't reliably cover statewide NDOT layer;
        # also SR differs—NDOT is wkid 26911 in the metadata)
        "join": {
            "enabled_default": False,
            "type": "none",
            "left_field": None,
        },
        "default_where": "property_address IS NOT NULL AND property_address <> ''",
    },

    "Henderson – STVR Licenses": {
        "layer_url": "https://maps.cityofhenderson.com/arcgis/rest/services/public/ComDevServices/MapServer/1",
        "oid_field": "OBJECTID",
        "mode_support": ["address", "apn", "oid_exact", "oid_range", "all"],
        "apn_field": "PARCEL",
        "addr_fields": None,
        "addr_single_field": "REGISTERED_ADDRESS",  # single address field
        "join": {
            "enabled_default": True,
            "type": "field",
            "left_field": "PARCEL",
        },
    },

    # IMPORTANT: This is *not* the same thing as "billboards".
    # It's permit/plan polygons (SignPlans). Treat it as a separate dataset type.
    "Henderson – Sign Plans (Permits)": {
        "layer_url": "https://maps.cityofhenderson.com/arcgis/rest/services/public/ComDevServices/MapServer/5",
        "oid_field": "OBJECTID",
        "mode_support": ["address", "oid_exact", "oid_range", "all"],
        "apn_field": None,  # no PARCEL/APN field
        "addr_fields": None,
        "addr_single_field": "MAIN_ADDRESS_LINE1",
        "join": {
            "enabled_default": False,
            "type": "spatial",          # spatial intersect with parcels
            "left_field": None,
            "spatial_in_sr": 102707,    # Henderson SignPlans SR (from service metadata)
        },
        # Helps reduce blank/placeholder rows when doing "All"
        "default_where": "MAIN_ADDRESS_LINE1 IS NOT NULL AND MAIN_ADDRESS_LINE1 <> ' '",
    },

    "North Las Vegas – (coming next)": {
        "layer_url": None,
        "oid_field": "OBJECTID",
        "mode_support": [],
        "apn_field": None,
        "addr_fields": None,
        "addr_single_field": None,
        "join": {"enabled_default": False, "type": "tbd", "left_field": None},
    },

    
    "Clark County – Billboards": {
    "layer_url": "https://services1.arcgis.com/F1v0ufATbBQScMtY/ArcGIS/rest/services/Clark_County_Billboards/FeatureServer/12",
    "oid_field": "OBJECTID",
    "mode_support": ["oid_exact", "oid_range", "all"],
    "apn_field": None,
    "addr_fields": None,
    "addr_single_field": None,
    "join": {
        "enabled_default": True,
        "type": "spatial",
        "left_field": None,
        "spatial_in_sr": 4326,
    },
    "default_where": "1=1",
    },
}
