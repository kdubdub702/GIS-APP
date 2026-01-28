import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from datasets import DATASETS
from engine import (
    objectid_exact, objectid_range, fetch_all, fetch_all_with_geometry,
    fetch_with_geometry_by_ids,
    apn_partial,
    address_partial_split, address_partial_single,
    join_to_parcels, spatial_join_signplans_to_parcels
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

    if mode == "Address (partial)":
        ds = DATASETS.get(source_var.get())
        if ds and ds.get("addr_single_field"):
            addr_single_frame.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        else:
            addr_split_frame.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(4, 0))

    elif mode == "APN/PARCEL (partial)":
        apn_frame.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(4, 0))

    elif mode == "ObjectID (exact)":
        oid_exact_frame.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(4, 0))

    elif mode == "ObjectID (range)":
        oid_range_frame.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(4, 0))

def set_source_ui(*_):
    ds = DATASETS.get(source_var.get())
    if not ds or not ds.get("layer_url"):
        messagebox.showinfo("Not wired yet", "This data source is staged but not wired yet.")
        return

    # Update search-type options based on dataset support
    supported = ds.get("mode_support", [])
    options = []
    if "address" in supported: options.append("Address (partial)")
    if "apn" in supported: options.append("APN/PARCEL (partial)")
    if "oid_exact" in supported: options.append("ObjectID (exact)")
    if "oid_range" in supported: options.append("ObjectID (range)")
    if "all" in supported: options.append("All (Export)")

    mode_combo["values"] = options

    # keep current mode if still valid, else set first
    if mode_var.get() not in options:
        mode_var.set(options[0] if options else "")

    # Join checkbox defaults per dataset
    jcfg = ds.get("join") or {}
    join_enabled_var.set(bool(jcfg.get("enabled_default", False)))

    # If join is not supported at all, disable checkbox
    join_type = (jcfg.get("type") or "tbd").lower()
    if join_type in ("tbd", "none") or (not jcfg):
        join_check.configure(state="disabled")
    else:
        join_check.configure(state="normal")

    set_mode_ui()

def _dataset_where(ds: dict) -> str:
    # Optional dataset-level filter (used for Henderson SignPlans to avoid blank rows,
    # and NDOT to avoid null/blank addresses)
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

    # Build list in current order
    obj_ids = []
    for v in df["OBJECTID"].tolist():
        try:
            obj_ids.append(int(str(v)))
        except:
            pass

    if not obj_ids:
        return df, None

    # Re-fetch with geometry
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

    path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
    if not path:
        return
    joined.to_csv(path, index=False)
    messagebox.showinfo("Saved", f"Saved:\n{path}")

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

ttk.Label(main, text="Search Type").grid(row=1, column=0, sticky="w")
mode_combo = ttk.Combobox(main, textvariable=mode_var, values=[], state="readonly")
mode_combo.grid(row=1, column=1, sticky="ew", padx=6)
mode_combo.bind("<<ComboboxSelected>>", set_mode_ui)

# Join toggle
join_enabled_var = tk.BooleanVar(value=True)
join_row = ttk.Frame(main)
join_row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
join_check = ttk.Checkbutton(join_row, text="Join to parcels (owner/tax/sales where available)", variable=join_enabled_var)
join_check.pack(side="left")

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
btns.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(10, 6))
ttk.Button(btns, text="Search / Load", command=on_search).pack(side="left")
ttk.Button(btns, text="Export CSV", command=on_export_csv).pack(side="left", padx=8)
ttk.Label(btns, textvariable=results_var).pack(side="right")

# Treeview + scrollbars
grid_frame = ttk.Frame(main)
grid_frame.grid(row=7, column=0, columnspan=2, sticky="nsew")
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
