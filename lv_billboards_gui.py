import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from engine import (
    billboards_objectid_exact,
    billboards_objectid_range,
    billboards_by_apn_partial,
    billboards_by_address_partial,
    join_billboards_to_parcels,
)

# ---------- Grid helpers ----------

def clear_tree(tree: ttk.Treeview):
    tree.delete(*tree.get_children())
    tree["columns"] = ()
    tree["show"] = "headings"

def load_df_into_tree(tree: ttk.Treeview, df):
    # Clear rows
    tree.delete(*tree.get_children())

    if df is None or df.empty:
        tree["columns"] = ()
        tree["show"] = "headings"
        return

    cols = list(df.columns)
    tree["columns"] = cols
    tree["show"] = "headings"

    # Fixed-width columns (fast + predictable)
    DEFAULT_W = 120
    for c in cols:
        tree.heading(c, text=c)
        tree.column(c, width=DEFAULT_W, minwidth=DEFAULT_W, stretch=False, anchor="w")

    # Insert all rows
    for row in df.itertuples(index=False, name=None):
        tree.insert("", "end", values=[("" if v is None else str(v)) for v in row])

# ---------- Mode UI ----------

def set_mode_ui(*_):
    mode = mode_var.get()
    addr_frame.grid_remove()
    apn_frame.grid_remove()
    oid_exact_frame.grid_remove()
    oid_range_frame.grid_remove()

    if mode == "Address (partial)":
        addr_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))
    elif mode == "APN/PARCEL (partial)":
        apn_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))
    elif mode == "ObjectID (exact)":
        oid_exact_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))
    elif mode == "ObjectID (range)":
        oid_range_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))

def on_search():
    try:
        mode = mode_var.get()

        if mode == "Address (partial)":
            bb = billboards_by_address_partial(
                street_num_var.get(),
                street_dir_var.get(),
                street_name_var.get()
            )
        elif mode == "APN/PARCEL (partial)":
            bb = billboards_by_apn_partial(apn_var.get())
        elif mode == "ObjectID (exact)":
            bb = billboards_objectid_exact(oid_exact_var.get())
        elif mode == "ObjectID (range)":
            bb = billboards_objectid_range(
                oid_start_var.get(),
                oid_end_var.get(),
                oid_field="OBJECTID"  # engine will fallback if needed
            )
        else:
            raise ValueError("Unknown search type")

        if bb is None or bb.empty:
            results_var.set("0 row(s)")
            load_df_into_tree(tree, bb)
            messagebox.showinfo("No results", "No billboards found.")
            return

        joined = join_billboards_to_parcels(bb)
        app.joined = joined
        results_var.set(f"{len(joined)} row(s)")

        # Load ALL rows
        load_df_into_tree(tree, joined)

    except Exception as e:
        messagebox.showerror("Error", str(e))

def on_export_csv():
    joined = getattr(app, "joined", None)
    if joined is None or joined.empty:
        messagebox.showwarning("Nothing to export", "Run a search first.")
        return

    path = filedialog.asksaveasfilename(
        defaultextension=".csv",
        filetypes=[("CSV files", "*.csv")]
    )
    if not path:
        return

    joined.to_csv(path, index=False)
    messagebox.showinfo("Saved", f"Saved:\n{path}")

# ---------------- UI ----------------
app = tk.Tk()
app.title("LV Billboards + Parcel Join")

main = ttk.Frame(app, padding=12)
main.grid(row=0, column=0, sticky="nsew")
app.columnconfigure(0, weight=1)
app.rowconfigure(0, weight=1)
main.columnconfigure(1, weight=1)
main.rowconfigure(4, weight=1)

mode_var = tk.StringVar(value="ObjectID (exact)")
results_var = tk.StringVar(value="0 row(s)")

ttk.Label(main, text="Search Type").grid(row=0, column=0, sticky="w")
mode_combo = ttk.Combobox(
    main,
    textvariable=mode_var,
    values=["Address (partial)", "APN/PARCEL (partial)", "ObjectID (exact)", "ObjectID (range)"],
    state="readonly"
)
mode_combo.grid(row=0, column=1, sticky="ew", padx=6)
mode_combo.bind("<<ComboboxSelected>>", set_mode_ui)

# Address frame
street_num_var = tk.StringVar()
street_dir_var = tk.StringVar()
street_name_var = tk.StringVar()
addr_frame = ttk.Frame(main)
ttk.Label(addr_frame, text="Street # (optional):").grid(row=0, column=0, sticky="w")
ttk.Entry(addr_frame, textvariable=street_num_var).grid(row=0, column=1, sticky="ew", padx=6)
ttk.Label(addr_frame, text="Dir (optional N/S/E/W):").grid(row=1, column=0, sticky="w")
ttk.Entry(addr_frame, textvariable=street_dir_var).grid(row=1, column=1, sticky="ew", padx=6)
ttk.Label(addr_frame, text="Street Name (partial):").grid(row=2, column=0, sticky="w")
ttk.Entry(addr_frame, textvariable=street_name_var).grid(row=2, column=1, sticky="ew", padx=6)
addr_frame.columnconfigure(1, weight=1)

# APN frame
apn_var = tk.StringVar()
apn_frame = ttk.Frame(main)
ttk.Label(apn_frame, text="APN/PARCEL prefix (digits):").grid(row=0, column=0, sticky="w")
ttk.Entry(apn_frame, textvariable=apn_var).grid(row=0, column=1, sticky="ew", padx=6)
apn_frame.columnconfigure(1, weight=1)

# ObjectID exact frame
oid_exact_var = tk.StringVar()
oid_exact_frame = ttk.Frame(main)
ttk.Label(oid_exact_frame, text="ObjectID (exact):").grid(row=0, column=0, sticky="w")
ttk.Entry(oid_exact_frame, textvariable=oid_exact_var).grid(row=0, column=1, sticky="ew", padx=6)
oid_exact_frame.columnconfigure(1, weight=1)

# ObjectID range frame
oid_start_var = tk.StringVar()
oid_end_var = tk.StringVar()
oid_range_frame = ttk.Frame(main)
ttk.Label(oid_range_frame, text="Start ObjectID:").grid(row=0, column=0, sticky="w")
ttk.Entry(oid_range_frame, textvariable=oid_start_var).grid(row=0, column=1, sticky="ew", padx=6)
ttk.Label(oid_range_frame, text="End ObjectID:").grid(row=1, column=0, sticky="w")
ttk.Entry(oid_range_frame, textvariable=oid_end_var).grid(row=1, column=1, sticky="ew", padx=6)
oid_range_frame.columnconfigure(1, weight=1)

set_mode_ui()

btns = ttk.Frame(main)
btns.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 6))
ttk.Button(btns, text="Search + Join", command=on_search).pack(side="left")
ttk.Button(btns, text="Export CSV", command=on_export_csv).pack(side="left", padx=8)
ttk.Label(btns, textvariable=results_var).pack(side="right")

# --- Treeview + scrollbars (both directions) ---
grid_frame = ttk.Frame(main)
grid_frame.grid(row=4, column=0, columnspan=2, sticky="nsew")
grid_frame.columnconfigure(0, weight=1)
grid_frame.rowconfigure(0, weight=1)

tree = ttk.Treeview(grid_frame, show="headings")
tree.grid(row=0, column=0, sticky="nsew")

vsb = ttk.Scrollbar(grid_frame, orient="vertical", command=tree.yview)
hsb = ttk.Scrollbar(grid_frame, orient="horizontal", command=tree.xview)
tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

vsb.grid(row=0, column=1, sticky="ns")
hsb.grid(row=1, column=0, sticky="ew")

# Prevent column resizing (block header drag)
def block_resize(event):
    region = tree.identify_region(event.x, event.y)
    if region in ("separator", "heading"):
        return "break"

tree.bind("<Button-1>", block_resize, add="+")

app.mainloop()
