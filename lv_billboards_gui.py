import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from datasets import DATASETS
from engine import (
    objectid_exact, objectid_range, fetch_all, fetch_all_with_geometry,
    fetch_with_geometry_by_ids,
    apn_partial,
    address_partial_split, address_partial_single,
    join_to_parcels, spatial_join_signplans_to_parcels,
    add_latlon_from_geometry, df_to_kml
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
        # IMPORTANT: fixed width per column (keeps GUI snappy)
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

    ds = DATASETS.get(source_var.get()) or {}
    supports = ds.get("mode_support") or []

    if mode == "Address (partial)":
        if "address" not in supports:
            messagebox.showinfo("Not supported", "This dataset does not support address searching.")
            mode_var.set("ObjectID (exact)")
            return
        if ds.get("addr_single_field"):
            addr_single_frame.grid()
        else:
            addr_split_frame.grid()

    elif mode == "APN/PARCEL (partial)":
        if "apn" not in supports:
            messagebox.showinfo("Not supported", "This dataset does not support APN/PARCEL searching.")
            mode_var.set("ObjectID (exact)")
            return
        apn_frame.grid()

    elif mode == "ObjectID (exact)":
        if "oid_exact" not in supports:
            messagebox.showinfo("Not supported", "This dataset does not support exact ObjectID searching.")
            mode_var.set("Address (partial)")
            return
        oid_exact_frame.grid()

    elif mode == "ObjectID (range)":
        if "oid_range" not in supports:
            messagebox.showinfo("Not supported", "This dataset does not support ObjectID ranges.")
            mode_var.set("ObjectID (exact)")
            return
        oid_range_frame.grid()

    elif mode == "All (Export)":
        if "all" not in supports:
            messagebox.showinfo("Not supported", "This dataset does not support bulk export.")
            mode_var.set("ObjectID (exact)")
            return

def set_source_ui(*_):
    ds = DATASETS.get(source_var.get()) or {}
    jcfg = ds.get("join") or {}
    join_enabled_var.set(bool(jcfg.get("enabled_default", False)))
    set_mode_ui()

def _dataset_where(ds: dict) -> str:
    w = (ds or {}).get("default_where")
    return w if w else "1=1"

def _ensure_geometry_for_df(layer_url: str, df):
    """
    Returns (df_with_geom_attrs, geoms) by refetching by OBJECTID
    """
    if df is None or df.empty:
        return df, None
    if "OBJECTID" not in df.columns:
        return df, None
    oids = []
    for v in df["OBJECTID"].tolist():
        try:
            oids.append(int(str(v)))
        except Exception:
            pass
    if not oids:
        return df, None
    return fetch_with_geometry_by_ids(layer_url, oids, out_sr=None)

def on_search():
    try:
        ds = DATASETS.get(source_var.get())
        if not ds or not ds.get("layer_url"):
            raise ValueError("Selected data source is not wired yet.")

        layer_url = ds["layer_url"]
        oid_field = ds.get("oid_field", "OBJECTID")
        mode = mode_var.get()

        df = None
        geoms = None  # only used for spatial join datasets

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
            # For spatial joins, we need geometry (Henderson SignPlans)
            jcfg = ds.get("join") or {}
            join_type = (jcfg.get("type") or "").lower()
            if join_enabled_var.get() and join_type == "spatial":
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
                df = join_to_parcels(df, left_field)

            elif join_type == "spatial":
                # Henderson SignPlans: spatial intersect polygons against parcels
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

        # Ensure LON/LAT are present for export (especially after joins)
        try:
            df = add_latlon_from_geometry(layer_url, df, oid_field=oid_field)
        except Exception:
            pass

        app.joined = df
        results_var.set(f"{len(df)} row(s)")
        load_df_into_tree(tree, df)

    except Exception as e:
        messagebox.showerror("Error", str(e))

def on_export_csv():
    joined = getattr(app, "joined", None)
    ds = DATASETS.get(source_var.get()) or {}
    layer_url = ds.get("layer_url")
    oid_field = ds.get("oid_field", "OBJECTID")
    # Ensure LON/LAT exist for CSV export too
    try:
        if layer_url:
            joined = add_latlon_from_geometry(layer_url, joined, oid_field=oid_field)
    except Exception:
        pass
    app.joined = joined

    if joined is None or joined.empty:
        messagebox.showwarning("Nothing to export", "Run a search first.")
        return

    path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
    if not path:
        return
    joined.to_csv(path, index=False)
    messagebox.showinfo("Saved", f"Saved:\n{path}")

def on_export_kml():
    joined = getattr(app, "joined", None)
    if joined is None or joined.empty:
        messagebox.showwarning("Nothing to export", "Run a search first.")
        return

    ds = DATASETS.get(source_var.get()) or {}
    layer_url = ds.get("layer_url")
    oid_field = ds.get("oid_field", "OBJECTID")

    # Always ensure we have LON/LAT before exporting
    try:
        joined2 = add_latlon_from_geometry(layer_url, joined, oid_field=oid_field) if layer_url else joined
    except Exception:
        joined2 = joined

    if "LON" not in joined2.columns or "LAT" not in joined2.columns:
        messagebox.showerror("KML export error", "Missing LON/LAT columns. Try running the search again.")
        return

    # Default placemark title = unique ID
    if "Billboard ID" in joined2.columns:
        name_field = "Billboard ID"
    elif "LVBOARDS_" in joined2.columns:
        name_field = "LVBOARDS_"
    else:
        name_field = oid_field

    # Color handling
    use_fixed = fixed_color_mode_var.get()
    fixed_color = fixed_color_var.get().strip() if use_fixed else None

    # Balloon/popup fields
    balloon_fields = []
    for c in [
        name_field,
        "STREET_NUM", "STREET_DIR", "STREET_NAM",
        "PARCEL", "APPLICANT", "APPLY_DATE",
        "Pin Title", "Pin Color Code"
    ]:
        if c in joined2.columns and c not in balloon_fields:
            balloon_fields.append(c)

    path = filedialog.asksaveasfilename(defaultextension=".kml", filetypes=[("KML files", "*.kml")])
    if not path:
        return

    df_to_kml(
        joined2,
        path,
        name_field=name_field,
        color_field="Pin Color Code",
        fixed_color=fixed_color,
        balloon_fields=balloon_fields,
        document_name=f"{source_var.get()} Export"
    )
    messagebox.showinfo("Saved", f"Saved:\n{path}")

def on_apply_pin_color():
    joined = getattr(app, "joined", None)
    if joined is None or joined.empty:
        messagebox.showwarning("No data", "Run a search first.")
        return
    color = fixed_color_var.get().strip()
    if not color:
        messagebox.showwarning("Missing color", "Enter a color name (red/blue/green/...) or hex (#RRGGBB).")
        return
    out = joined.copy()
    out["Pin Color Code"] = color
    app.joined = out
    load_df_into_tree(tree, out)
    results_var.set(f"{len(out)} row(s)")

def block_resize(e=None):
    # lock column stretching
    for c in tree["columns"]:
        tree.column(c, stretch=False)

# ---------------- UI ----------------
app = tk.Tk()
app.title("SNV GIS Tool – Multi-City / Multi-Agency (Billboards / Permits / Parcels)")

main = ttk.Frame(app, padding=12)
main.grid(row=0, column=0, sticky="nsew")
app.columnconfigure(0, weight=1)
app.rowconfigure(0, weight=1)
main.columnconfigure(1, weight=1)
main.rowconfigure(7, weight=1)

# Data Source selector
source_var = tk.StringVar(value=list(DATASETS.keys())[0])
ttk.Label(main, text="Data Source").grid(row=0, column=0, sticky="w")
source_combo = ttk.Combobox(main, textvariable=source_var, values=list(DATASETS.keys()), state="readonly")
source_combo.grid(row=0, column=1, sticky="ew", padx=6)
source_combo.bind("<<ComboboxSelected>>", set_source_ui)

# Search Type selector
mode_var = tk.StringVar(value="ObjectID (exact)")
results_var = tk.StringVar(value="0 row(s)")

# KML export options
fixed_color_mode_var = tk.BooleanVar(value=False)
fixed_color_var = tk.StringVar(value='red')  # name (red/blue/...) or hex (#RRGGBB)

ttk.Label(main, text="Search Type").grid(row=1, column=0, sticky="w", pady=(8, 0))
mode_combo = ttk.Combobox(
    main,
    textvariable=mode_var,
    state="readonly",
    values=["Address (partial)", "APN/PARCEL (partial)", "ObjectID (exact)", "ObjectID (range)", "All (Export)"]
)
mode_combo.grid(row=1, column=1, sticky="ew", padx=6, pady=(8, 0))
mode_combo.bind("<<ComboboxSelected>>", set_mode_ui)

# Join checkbox
join_enabled_var = tk.BooleanVar(value=True)
ttk.Checkbutton(main, text="Join to Parcels (Owner/Tax)", variable=join_enabled_var).grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))

# Address split inputs
street_num_var = tk.StringVar()
street_dir_var = tk.StringVar()
street_name_var = tk.StringVar()

addr_split_frame = ttk.LabelFrame(main, text="Address Parts (partial)")
addr_split_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
addr_split_frame.columnconfigure(1, weight=1)

ttk.Label(addr_split_frame, text="Street #").grid(row=0, column=0, sticky="w")
ttk.Entry(addr_split_frame, textvariable=street_num_var, width=12).grid(row=0, column=1, sticky="w", padx=6)
ttk.Label(addr_split_frame, text="Dir").grid(row=0, column=2, sticky="w")
ttk.Entry(addr_split_frame, textvariable=street_dir_var, width=6).grid(row=0, column=3, sticky="w", padx=6)
ttk.Label(addr_split_frame, text="Name").grid(row=0, column=4, sticky="w")
ttk.Entry(addr_split_frame, textvariable=street_name_var).grid(row=0, column=5, sticky="ew", padx=6)

# Address single input
addr_single_var = tk.StringVar()
addr_single_frame = ttk.LabelFrame(main, text="Address (partial)")
addr_single_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
addr_single_frame.columnconfigure(1, weight=1)
ttk.Label(addr_single_frame, text="Address").grid(row=0, column=0, sticky="w")
ttk.Entry(addr_single_frame, textvariable=addr_single_var).grid(row=0, column=1, sticky="ew", padx=6)

# APN input
apn_var = tk.StringVar()
apn_frame = ttk.LabelFrame(main, text="APN/PARCEL (partial)")
apn_frame.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))
apn_frame.columnconfigure(1, weight=1)
ttk.Label(apn_frame, text="APN/PARCEL").grid(row=0, column=0, sticky="w")
ttk.Entry(apn_frame, textvariable=apn_var).grid(row=0, column=1, sticky="ew", padx=6)

# OID exact
oid_exact_var = tk.StringVar()
oid_exact_frame = ttk.LabelFrame(main, text="ObjectID (exact)")
oid_exact_frame.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(8, 0))
oid_exact_frame.columnconfigure(1, weight=1)
ttk.Label(oid_exact_frame, text="ObjectID").grid(row=0, column=0, sticky="w")
ttk.Entry(oid_exact_frame, textvariable=oid_exact_var).grid(row=0, column=1, sticky="ew", padx=6)

# OID range
oid_start_var = tk.StringVar()
oid_end_var = tk.StringVar()
oid_range_frame = ttk.LabelFrame(main, text="ObjectID (range)")
oid_range_frame.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(8, 0))
oid_range_frame.columnconfigure(1, weight=1)
ttk.Label(oid_range_frame, text="Start").grid(row=0, column=0, sticky="w")
ttk.Entry(oid_range_frame, textvariable=oid_start_var, width=10).grid(row=0, column=1, sticky="w", padx=6)
ttk.Label(oid_range_frame, text="End").grid(row=0, column=2, sticky="w")
ttk.Entry(oid_range_frame, textvariable=oid_end_var, width=10).grid(row=0, column=3, sticky="w", padx=6)

# Buttons row
btns = ttk.Frame(main)
btns.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(10, 0))
ttk.Button(btns, text="Search / Load", command=on_search).pack(side="left")
ttk.Button(btns, text="Export CSV", command=on_export_csv).pack(side="left", padx=8)
ttk.Button(btns, text="Export KML", command=on_export_kml).pack(side="left")
ttk.Label(btns, textvariable=results_var).pack(side="right")

# KML pin styling (optional)
kml_opts = ttk.Frame(main)
kml_opts.grid(row=6, column=0, columnspan=2, sticky="w", pady=(4, 0))
ttk.Checkbutton(kml_opts, text="KML: use fixed pin color", variable=fixed_color_mode_var).pack(side="left")
ttk.Label(kml_opts, text="Color").pack(side="left", padx=(10, 4))
ttk.Entry(kml_opts, textvariable=fixed_color_var, width=12).pack(side="left")
ttk.Button(kml_opts, text="Apply color to all rows", command=on_apply_pin_color).pack(side="left", padx=(10, 0))

# Treeview + scrollbars
grid_frame = ttk.Frame(main)
grid_frame.grid(row=7, column=0, columnspan=2, sticky="nsew")
grid_frame.columnconfigure(0, weight=1)
grid_frame.rowconfigure(0, weight=1)

tree = ttk.Treeview(grid_frame, show="headings")
vsb = ttk.Scrollbar(grid_frame, orient="vertical", command=tree.yview)
hsb = ttk.Scrollbar(grid_frame, orient="horizontal", command=tree.xview)
tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

tree.grid(row=0, column=0, sticky="nsew")
vsb.grid(row=0, column=1, sticky="ns")
hsb.grid(row=1, column=0, sticky="ew")

tree.bind("<Configure>", block_resize)

# Initialize UI state
addr_single_frame.grid_remove()
apn_frame.grid_remove()
oid_range_frame.grid_remove()
set_source_ui()

app.mainloop()
