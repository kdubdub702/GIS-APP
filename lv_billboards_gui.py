import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from datasets import DATASETS
from engine import (
    objectid_exact, objectid_range, fetch_all, fetch_all_with_geometry,
    fetch_with_geometry_by_ids,
    apn_partial,
    address_partial_split, address_partial_single,
    join_to_parcels, spatial_join_signplans_to_parcels,
    enrich_billboards_with_owner,
    add_lat_lon_from_geoms, df_to_kml
)

# ---------- Grid helpers ----------

def load_df_into_tree(tree: ttk.Treeview, df):
    tree.delete(*tree.get_children())

    if df is None or df.empty:
        tree["columns"] = ()
        tree["show"] = "headings"
        return

    cols = list(df.columns)
    tree["columns"] = cols
    tree["show"] = "headings"

    DEFAULT_W = 120
    for c in cols:
        tree.heading(c, text=c)
        # fixed width per column (keeps GUI snappy)
        tree.column(c, width=DEFAULT_W, minwidth=DEFAULT_W, stretch=False, anchor="w")

    for row in df.itertuples(index=False, name=None):
        tree.insert("", "end", values=[("" if v is None else str(v)) for v in row])

# ---------- UI helpers ----------

def set_mode_ui(*_):
    mode = mode_var.get()

    # hide all input frames
    addr_split_frame.grid_remove()
    addr_single_frame.grid_remove()
    apn_frame.grid_remove()
    oid_exact_frame.grid_remove()
    oid_range_frame.grid_remove()

    if mode == "Address (partial)":
        ds = DATASETS.get(source_var.get())
        if ds and ds.get("addr_single_field"):
            addr_single_frame.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        else:
            addr_split_frame.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(4, 0))

    elif mode == "APN/PARCEL (partial)":
        apn_frame.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(4, 0))

    elif mode == "ObjectID (exact)":
        oid_exact_frame.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(4, 0))

    elif mode == "ObjectID (range)":
        oid_range_frame.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(4, 0))


def _dataset_where(ds: dict) -> str:
    return ds.get("default_where") or "1=1"


def _ensure_geometry_for_df(layer_url: str, df):
    """
    If df has OBJECTID, re-fetch geometry for those rows.
    Returns (df_same, geoms_list) where geoms_list aligns with df row order (best-effort).
    """
    if df is None or df.empty:
        return df, None

    if "OBJECTID" not in df.columns:
        return df, None

    obj_ids = []
    for v in df["OBJECTID"].tolist():
        try:
            obj_ids.append(int(str(v)))
        except:
            pass

    if not obj_ids:
        return df, None

    df_geom, geoms = fetch_with_geometry_by_ids(layer_url, obj_ids, out_sr=None)
    if df_geom is None or df_geom.empty or geoms is None:
        return df, None

    oid_to_geom = {}
    for row, geom in zip(df_geom.itertuples(index=False), geoms):
        try:
            oid = int(getattr(row, "OBJECTID"))
            oid_to_geom[oid] = geom
        except:
            continue

    aligned_geoms = [oid_to_geom.get(oid) for oid in obj_ids]
    return df, aligned_geoms


def _ensure_wgs84_latlon(layer_url: str, df):
    """
    Returns a copy of df with LAT/LON columns (WGS84) when possible.
    Uses a geometry re-fetch (outSR=4326) keyed by OBJECTID so it aligns with df.
    """
    if df is None or df.empty or "OBJECTID" not in df.columns:
        return df

    obj_ids = []
    for v in df["OBJECTID"].tolist():
        try:
            obj_ids.append(int(str(v)))
        except:
            pass
    if not obj_ids:
        return df

    df_geom, geoms = fetch_with_geometry_by_ids(layer_url, obj_ids, out_sr=4326)
    if df_geom is None or df_geom.empty or geoms is None:
        return df

    oid_to_geom = {}
    for row, geom in zip(df_geom.itertuples(index=False), geoms):
        try:
            oid_to_geom[int(getattr(row, "OBJECTID"))] = geom
        except:
            continue

    aligned = [oid_to_geom.get(oid) for oid in obj_ids]
    out = add_lat_lon_from_geoms(df, aligned)
    return out


def _update_join_options_for_dataset(ds: dict):
    """Enable/disable join controls based on dataset join type."""
    jcfg = ds.get("join") or {}
    join_type = (jcfg.get("type") or "none").lower()

    # Join checkbox
    if join_type in ("none", "tbd") or not jcfg:
        join_check.configure(state="disabled")
        join_enabled_var.set(False)
    else:
        join_check.configure(state="normal")
        join_enabled_var.set(bool(jcfg.get("enabled_default", False)))

    # Address fallback checkbox is ONLY relevant for Las Vegas billboards tiered join.
    is_lv_billboards = (source_var.get() == "Las Vegas – Billboards")
    if is_lv_billboards and join_type == "field":
        addr_fallback_check.configure(state="normal")
    else:
        addr_fallback_check.configure(state="disabled")
        address_fallback_var.set(False)


def set_source_ui(*_):
    ds = DATASETS.get(source_var.get())
    if not ds or not ds.get("layer_url"):
        messagebox.showinfo("Not wired yet", "This data source is staged but not wired yet.")
        return

    # Search-type options based on dataset support
    supported = ds.get("mode_support", [])
    options = []
    if "address" in supported: options.append("Address (partial)")
    if "apn" in supported: options.append("APN/PARCEL (partial)")
    if "oid_exact" in supported: options.append("ObjectID (exact)")
    if "oid_range" in supported: options.append("ObjectID (range)")
    if "all" in supported: options.append("All (Export)")

    mode_combo["values"] = options
    if mode_var.get() not in options:
        mode_var.set(options[0] if options else "")

    _update_join_options_for_dataset(ds)
    set_mode_ui()


def on_search():
    try:
        ds = DATASETS.get(source_var.get())
        if not ds or not ds.get("layer_url"):
            raise ValueError("Selected data source is not wired yet.")

        layer_url = ds["layer_url"]
        oid_field = ds.get("oid_field", "OBJECTID")
        mode = mode_var.get()

        df = None
        geoms = None  # used for spatial join datasets & tiered owner join

        if mode == "Address (partial)":
            if ds.get("addr_single_field"):
                df = address_partial_single(layer_url, ds["addr_single_field"], addr_single_var.get())
            else:
                fnum, fdir, fnm = ds["addr_fields"]
                df = address_partial_split(
                    layer_url,
                    street_num_var.get(), street_dir_var.get(), street_name_var.get(),
                    fnum, fdir, fnm
                )

        elif mode == "APN/PARCEL (partial)":
            apn_field = ds.get("apn_field")
            if not apn_field:
                raise ValueError("This dataset does not support APN/PARCEL searching.")
            df = apn_partial(layer_url, apn_field, apn_var.get())

        elif mode == "ObjectID (exact)":
            df = objectid_exact(layer_url, oid_exact_var.get())

        elif mode == "ObjectID (range)":
            df = objectid_range(layer_url, oid_start_var.get(), oid_end_var.get(), oid_field=oid_field)

        elif mode == "All (Export)":
            where = _dataset_where(ds)
            jcfg = ds.get("join") or {}
            join_type = (jcfg.get("type") or "").lower()

            # Spatial joins need geometry (Henderson SignPlans)
            if join_enabled_var.get() and join_type == "spatial":
                df, geoms = fetch_all_with_geometry(layer_url, where=where, out_sr=None)

            # LV billboards tiered owner join also benefits from geometry (spatial fallback)
            elif join_enabled_var.get() and source_var.get() == "Las Vegas – Billboards" and join_type == "field":
                df, geoms = fetch_all_with_geometry(layer_url, where=where, out_sr=None)

            else:
                df = fetch_all(layer_url, where=where)

        else:
            raise ValueError("Unknown search type")

        if df is None or df.empty:
            results_var.set("0 row(s)")
            load_df_into_tree(tree, df)
            messagebox.showinfo("No results", "No records found.")
            return

        # Optional join
        if join_enabled_var.get():
            jcfg = ds.get("join") or {}
            join_type = (jcfg.get("type") or "").lower()

            if join_type == "field":
                left_field = jcfg.get("left_field")
                if not left_field:
                    raise ValueError("Join misconfigured: missing left_field")

                # Las Vegas billboards: tiered join (APN -> spatial -> optional address)
                if source_var.get() == "Las Vegas – Billboards":
                    if geoms is None:
                        df, geoms = _ensure_geometry_for_df(layer_url, df)

                    df = enrich_billboards_with_owner(
                        df,
                        geoms,
                        parcel_field=left_field,
                        in_sr=3421,
                        use_spatial_fallback=True,
                        use_address_fallback=bool(address_fallback_var.get()),
                    )
                else:
                    df = join_to_parcels(df, left_field)

            elif join_type == "spatial":
                in_sr = int(jcfg.get("spatial_in_sr", 102707))

                # Ensure we have geometry even for Address/ObjectID searches
                if geoms is None:
                    df, geoms = _ensure_geometry_for_df(layer_url, df)

                if geoms is None:
                    messagebox.showwarning(
                        "Spatial join skipped",
                        "Could not fetch geometry for these results (missing OBJECTID or geometry fetch failed)."
                    )
                else:
                    df = spatial_join_signplans_to_parcels(df, geoms, in_sr=in_sr)

        app.joined = df
        results_var.set(f"{len(df)} row(s)")
        load_df_into_tree(tree, df)

    except Exception as e:
        messagebox.showerror("Error", str(e))


def on_export_csv():
    joined = getattr(app, "joined", None)
    if joined is None or joined.empty:
        messagebox.showwarning("Nothing to export", "Run a search first.")
        return

    ds = DATASETS.get(source_var.get()) or {}
    layer_url = ds.get("layer_url")

    df_out = joined
    # For LV billboards, add back LAT/LON (WGS84) by re-fetching point geometry.
    if source_var.get() == "Las Vegas – Billboards" and layer_url:
        try:
            df_out = _ensure_wgs84_latlon(layer_url, joined)
        except Exception:
            # Keep CSV export working even if lat/lon enrichment fails
            df_out = joined

    path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
    if not path:
        return
    df_out.to_csv(path, index=False)
    messagebox.showinfo("Saved", f"Saved:\n{path}")


def on_export_kml():
    joined = getattr(app, "joined", None)
    if joined is None or joined.empty:
        messagebox.showwarning("Nothing to export", "Run a search first.")
        return

    ds = DATASETS.get(source_var.get()) or {}
    layer_url = ds.get("layer_url")

    # Need LAT/LON (WGS84) for KML. We'll try to re-fetch WGS84 geometry when possible.
    df_out = joined
    if layer_url and "OBJECTID" in joined.columns:
        df_out = _ensure_wgs84_latlon(layer_url, joined)

    if "LAT" not in df_out.columns or "LON" not in df_out.columns:
        messagebox.showerror("KML export", "LAT/LON not available for these results.")
        return

    # Your desired popup fields for billboards
    balloon_fields = [
        "Billboard ID",
        "STREET_NUM",
        "STREET_DIR",
        "STREET_NAM",
        "PARCEL",
        "APPLICANT",
        "APPLY_DATE",
    ]

    # Ensure "Billboard ID" exists (use OBJECTID if needed)
    if "Billboard ID" not in df_out.columns and "OBJECTID" in df_out.columns:
        df_out = df_out.copy()
        df_out["Billboard ID"] = df_out["OBJECTID"]

    name_field = "Pin Title" if "Pin Title" in df_out.columns else "Billboard ID"
    color_field = "Pin Color Code" if "Pin Color Code" in df_out.columns else None

    try:
        kml_text = df_to_kml(
            df_out,
            name_field=name_field,
            fields_in_balloon=balloon_fields,
            color_field=color_field,
            title=f"{source_var.get()} Export"
        )
    except Exception as e:
        messagebox.showerror("KML export", str(e))
        return

    path = filedialog.asksaveasfilename(defaultextension=".kml", filetypes=[("KML files", "*.kml")])
    if not path:
        return

    with open(path, "w", encoding="utf-8") as f:
        f.write(kml_text)

    messagebox.showinfo("Saved", f"Saved:\n{path}")


# ---------------- UI ----------------
app = tk.Tk()
app.title("SNV GIS Tool – Multi-City / Multi-Agency (Billboards / Permits / Parcels)")

main = ttk.Frame(app, padding=12)
main.grid(row=0, column=0, sticky="nsew")
app.columnconfigure(0, weight=1)
app.rowconfigure(0, weight=1)
main.columnconfigure(1, weight=1)
main.rowconfigure(8, weight=1)

# Data Source selector
source_var = tk.StringVar(value=list(DATASETS.keys())[0])
ttk.Label(main, text="Data Source").grid(row=0, column=0, sticky="w")
source_combo = ttk.Combobox(main, textvariable=source_var, values=list(DATASETS.keys()), state="readonly")
source_combo.grid(row=0, column=1, sticky="ew", padx=6)
source_combo.bind("<<ComboboxSelected>>", set_source_ui)

# Search Type selector
mode_var = tk.StringVar(value="ObjectID (exact)")
results_var = tk.StringVar(value="0 row(s)")

ttk.Label(main, text="Search Type").grid(row=1, column=0, sticky="w")
mode_combo = ttk.Combobox(main, textvariable=mode_var, values=[], state="readonly")
mode_combo.grid(row=1, column=1, sticky="ew", padx=6)
mode_combo.bind("<<ComboboxSelected>>", set_mode_ui)

# Join + fallback toggles
join_enabled_var = tk.BooleanVar(value=True)
address_fallback_var = tk.BooleanVar(value=False)

join_row = ttk.Frame(main)
join_row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))

join_check = ttk.Checkbutton(
    join_row,
    text="Join to parcels (owner/tax/sales where available)",
    variable=join_enabled_var
)
join_check.pack(side="left")

addr_fallback_check = ttk.Checkbutton(
    join_row,
    text="Use address fallback (approximate)",
    variable=address_fallback_var
)
addr_fallback_check.pack(side="left", padx=14)

# --- Address (split fields) ---
street_num_var = tk.StringVar()
street_dir_var = tk.StringVar()
street_name_var = tk.StringVar()

addr_split_frame = ttk.Frame(main)
ttk.Label(addr_split_frame, text="Street # (optional):").grid(row=0, column=0, sticky="w")
ttk.Entry(addr_split_frame, textvariable=street_num_var).grid(row=0, column=1, sticky="ew", padx=6)
ttk.Label(addr_split_frame, text="Dir (optional N/S/E/W):").grid(row=1, column=0, sticky="w")
ttk.Entry(addr_split_frame, textvariable=street_dir_var).grid(row=1, column=1, sticky="ew", padx=6)
ttk.Label(addr_split_frame, text="Street Name (partial):").grid(row=2, column=0, sticky="w")
ttk.Entry(addr_split_frame, textvariable=street_name_var).grid(row=2, column=1, sticky="ew", padx=6)
addr_split_frame.columnconfigure(1, weight=1)

# --- Address (single field) ---
addr_single_var = tk.StringVar()
addr_single_frame = ttk.Frame(main)
ttk.Label(addr_single_frame, text="Address (partial):").grid(row=0, column=0, sticky="w")
ttk.Entry(addr_single_frame, textvariable=addr_single_var).grid(row=0, column=1, sticky="ew", padx=6)
addr_single_frame.columnconfigure(1, weight=1)

# --- APN frame ---
apn_var = tk.StringVar()
apn_frame = ttk.Frame(main)
ttk.Label(apn_frame, text="APN/PARCEL prefix (digits):").grid(row=0, column=0, sticky="w")
ttk.Entry(apn_frame, textvariable=apn_var).grid(row=0, column=1, sticky="ew", padx=6)
apn_frame.columnconfigure(1, weight=1)

# --- ObjectID exact frame ---
oid_exact_var = tk.StringVar()
oid_exact_frame = ttk.Frame(main)
ttk.Label(oid_exact_frame, text="ObjectID (exact):").grid(row=0, column=0, sticky="w")
ttk.Entry(oid_exact_frame, textvariable=oid_exact_var).grid(row=0, column=1, sticky="ew", padx=6)
oid_exact_frame.columnconfigure(1, weight=1)

# --- ObjectID range frame ---
oid_start_var = tk.StringVar()
oid_end_var = tk.StringVar()
oid_range_frame = ttk.Frame(main)
ttk.Label(oid_range_frame, text="Start ObjectID:").grid(row=0, column=0, sticky="w")
ttk.Entry(oid_range_frame, textvariable=oid_start_var).grid(row=0, column=1, sticky="ew", padx=6)
ttk.Label(oid_range_frame, text="End ObjectID:").grid(row=1, column=0, sticky="w")
ttk.Entry(oid_range_frame, textvariable=oid_end_var).grid(row=1, column=1, sticky="ew", padx=6)
oid_range_frame.columnconfigure(1, weight=1)

# Buttons
btns = ttk.Frame(main)
btns.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(10, 6))
ttk.Button(btns, text="Search / Load", command=on_search).pack(side="left")
ttk.Button(btns, text="Export CSV", command=on_export_csv).pack(side="left", padx=8)
ttk.Button(btns, text="Export KML", command=on_export_kml).pack(side="left", padx=8)
ttk.Label(btns, textvariable=results_var).pack(side="right")

# Treeview + scrollbars
grid_frame = ttk.Frame(main)
grid_frame.grid(row=8, column=0, columnspan=2, sticky="nsew")
grid_frame.columnconfigure(0, weight=1)
grid_frame.rowconfigure(0, weight=1)

tree = ttk.Treeview(grid_frame, show="headings")
tree.grid(row=0, column=0, sticky="nsew")

vsb = ttk.Scrollbar(grid_frame, orient="vertical", command=tree.yview)
hsb = ttk.Scrollbar(grid_frame, orient="horizontal", command=tree.xview)
tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

vsb.grid(row=0, column=1, sticky="ns")
hsb.grid(row=1, column=0, sticky="ew")

# Prevent per-column resizing (keeps performance good)
def block_resize(event):
    region = tree.identify_region(event.x, event.y)
    if region in ("separator", "heading"):
        return "break"

tree.bind("<Button-1>", block_resize, add="+")

# Initialize selector-derived UI
set_source_ui()

app.mainloop()
