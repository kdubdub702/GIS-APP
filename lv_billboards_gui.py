import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from datasets import DATASETS
from engine import (
    objectid_exact, objectid_range, fetch_all,
    apn_partial,
    address_partial_split, address_partial_single,
    join_to_parcels
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
        # show split or single address based on dataset
        ds = DATASETS.get(source_var.get())
        if ds and ds.get("addr_single_field"):
            addr_single_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        else:
            addr_split_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 0))

    elif mode == "APN/PARCEL (partial)":
        apn_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 0))
    elif mode == "ObjectID (exact)":
        oid_exact_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 0))
    elif mode == "ObjectID (range)":
        oid_range_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 0))

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
    set_mode_ui()

def on_search():
    try:
        ds = DATASETS.get(source_var.get())
        if not ds or not ds.get("layer_url"):
            raise ValueError("Selected data source is not wired yet.")

        layer_url = ds["layer_url"]
        oid_field = ds.get("oid_field", "OBJECTID")

        mode = mode_var.get()

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
            df = fetch_all(layer_url)

        else:
            raise ValueError("Unknown search type")

        if df is None or df.empty:
            results_var.set("0 row(s)")
            load_df_into_tree(tree, df)
            messagebox.showinfo("No results", "No records found.")
            return

        # Join if enabled
        if ds.get("join_enabled"):
            df = join_to_parcels(df, ds["join_left_field"])

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
app.title("SNV GIS Tool – Multi-City (Billboards / Licenses / Parcels)")

main = ttk.Frame(app, padding=12)
main.grid(row=0, column=0, sticky="nsew")
app.columnconfigure(0, weight=1)
app.rowconfigure(0, weight=1)
main.columnconfigure(1, weight=1)
main.rowconfigure(6, weight=1)

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
btns.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(10, 6))
ttk.Button(btns, text="Search / Load", command=on_search).pack(side="left")
ttk.Button(btns, text="Export CSV", command=on_export_csv).pack(side="left", padx=8)
ttk.Label(btns, textvariable=results_var).pack(side="right")

# Treeview + scrollbars
grid_frame = ttk.Frame(main)
grid_frame.grid(row=6, column=0, columnspan=2, sticky="nsew")
grid_frame.columnconfigure(0, weight=1)
grid_frame.rowconfigure(0, weight=1)

tree = ttk.Treeview(grid_frame, show="headings")
tree.grid(row=0, column=0, sticky="nsew")

vsb = ttk.Scrollbar(grid_frame, orient="vertical", command=tree.yview)
hsb = ttk.Scrollbar(grid_frame, orient="horizontal", command=tree.xview)
tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

vsb.grid(row=0, column=1, sticky="ns")
hsb.grid(row=1, column=0, sticky="ew")

def block_resize(event):
    region = tree.identify_region(event.x, event.y)
    if region in ("separator", "heading"):
        return "break"

tree.bind("<Button-1>", block_resize, add="+")

# Initialize selector-derived UI
set_source_ui()

app.mainloop()
