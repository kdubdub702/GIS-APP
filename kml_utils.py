"""kml_utils.py

Lightweight KML/KMZ generation helpers for Google Earth / Google My Maps.

- Generates a single Document with an optional Style and optional Folder grouping.
- Expects lon/lat in WGS84 (EPSG:4326).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Iterable
from xml.sax.saxutils import escape
from pathlib import Path
import zipfile
import io

import pandas as pd


GOOGLE_DEFAULT_ICON = "http://maps.google.com/mapfiles/kml/shapes/target.png"


@dataclass(frozen=True)
class KmlStyle:
    """Simple icon style."""
    style_id: str = "pin"
    icon_href: str = GOOGLE_DEFAULT_ICON


def _cdata(html: str) -> str:
    # CDATA is safest for rich descriptions in Earth/Maps.
    return f"<![CDATA[{html}]]>"


def _row_description_html(row: pd.Series, include_cols: Optional[Iterable[str]] = None) -> str:
    cols = list(include_cols) if include_cols is not None else list(row.index)
    parts = []
    for col in cols:
        val = row.get(col)
        if pd.isna(val) or val is None:
            continue
        parts.append(f"<b>{escape(str(col))}</b>: {escape(str(val))}")
    return "<br/>".join(parts)


def dataframe_to_kml(
    df: pd.DataFrame,
    output_path: str,
    *,
    lat_col: str = "LATITUDE",
    lon_col: str = "LONGITUDE",
    name_col: Optional[str] = None,
    description_cols: Optional[Iterable[str]] = None,
    folder_by: Optional[str] = None,
    style: Optional[KmlStyle] = KmlStyle(),
) -> str:
    """Write a .kml file from a DataFrame of point features.

    Parameters
    ----------
    df : DataFrame
        Must include lon/lat columns (EPSG:4326).
    output_path : str
        Destination .kml file path.
    lat_col, lon_col : str
        Latitude/Longitude columns.
    name_col : str | None
        Placemark name/label column. If None, tries a few common fields.
    description_cols : iterable[str] | None
        Columns to include in the popup description. None = all columns.
    folder_by : str | None
        If provided and exists in df, Placemarks will be grouped into <Folder>s.
    style : KmlStyle | None
        Adds a single icon style and applies it to all placemarks.
    """
    if df is None or df.empty:
        raise ValueError("No rows to export.")

    if lat_col not in df.columns or lon_col not in df.columns:
        raise ValueError(f"Missing required columns: {lat_col}, {lon_col}")

    if name_col is None:
        for cand in ("TAG_NUM", "OBJECTID_BILLBOARD", "OBJECTID", "PARCEL", "STREET_NAM"):
            if cand in df.columns:
                name_col = cand
                break
        if name_col is None:
            name_col = df.columns[0]

    use_folders = folder_by is not None and folder_by in df.columns

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        '<Document>',
        f'<name>{escape(Path(output_path).stem)}</name>',
    ]

    if style is not None:
        lines += [
            f'<Style id="{escape(style.style_id)}">',
            '  <IconStyle>',
            '    <scale>1.1</scale>',
            '    <Icon>',
            f'      <href>{escape(style.icon_href)}</href>',
            '    </Icon>',
            '  </IconStyle>',
            '</Style>',
        ]

    def placemark_block(row: pd.Series) -> str:
        lat = row.get(lat_col)
        lon = row.get(lon_col)
        if pd.isna(lat) or pd.isna(lon):
            return ""
        nm = escape(str(row.get(name_col, "Location")))
        desc_html = _row_description_html(row, include_cols=description_cols)
        style_url = f"<styleUrl>#{escape(style.style_id)}</styleUrl>" if style is not None else ""
        return (
            "<Placemark>\n"
            f"  <name>{nm}</name>\n"
            f"  {style_url}\n"
            f"  <description>{_cdata(desc_html)}</description>\n"
            "  <Point>\n"
            f"    <coordinates>{lon},{lat},0</coordinates>\n"
            "  </Point>\n"
            "</Placemark>"
        )

    if use_folders:
        for key, g in df.groupby(folder_by, dropna=False):
            folder_name = "(blank)" if pd.isna(key) else str(key)
            lines.append(f"<Folder><name>{escape(folder_name)}</name>")
            for _, row in g.iterrows():
                pm = placemark_block(row)
                if pm:
                    lines.append(pm)
            lines.append("</Folder>")
    else:
        for _, row in df.iterrows():
            pm = placemark_block(row)
            if pm:
                lines.append(pm)

    lines.append("</Document></kml>")

    Path(output_path).write_text("\n".join(lines), encoding="utf-8")
    return output_path


def dataframe_to_kmz(*args, kmz_path: str, **kwargs) -> str:
    """Create a .kmz (zipped KML) from the same arguments as dataframe_to_kml."""
    # Build KML in-memory
    buf = io.BytesIO()
    # We'll write to a temp string, then zip it
    tmp_kml_name = "doc.kml"
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        kml_path = str(Path(td) / tmp_kml_name)
        dataframe_to_kml(*args, output_path=kml_path, **kwargs)
        kml_bytes = Path(kml_path).read_bytes()
    with zipfile.ZipFile(kmz_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(tmp_kml_name, kml_bytes)
    return kmz_path
