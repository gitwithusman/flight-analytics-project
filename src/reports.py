"""Exports and reports: CSV, Excel and PDF that contain the data actually shown.

Every export carries a metadata block (title, generated time, filters applied,
reporting period, data sources, limitations) so a file is interpretable on its
own. SAMPLE-data rows are always marked.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import pandas as pd

from . import config
from .utils import timestamp_for_filename

APP_LINE = "Flight and Airport Analytics (SkyLens)"


def default_path(stem: str, ext: str) -> Path:
    return config.EXPORTS_DIR / f"{stem}_{timestamp_for_filename()}.{ext}"


def metadata(title: str, filters: Dict[str, object], period: str, sources: Sequence[str],
             limitations: Sequence[str], rows: int) -> Dict[str, object]:
    return {"title": title, "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "filters": {k: v for k, v in filters.items() if v not in (None, "", [], "All")} or "none",
            "reporting_period": period, "rows": rows, "sources": list(sources), "limitations": list(limitations)}


def _flat(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for c in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[c]):
            out[c] = out[c].dt.tz_localize(None) if getattr(out[c].dt, "tz", None) is not None else out[c]
    return out


def export_csv(df: pd.DataFrame, path: Path, meta: Optional[Dict] = None) -> Path:
    """CSV of the displayed rows. Metadata is written to a sibling ``.meta.txt`` file
    so the CSV itself stays machine-readable."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _flat(df).to_csv(path, index=False, encoding="utf-8-sig")
    if meta:
        path.with_suffix(".meta.txt").write_text(_meta_text(meta), encoding="utf-8")
    return path


def _meta_text(meta: Dict) -> str:
    lines = [f"{APP_LINE} - export", f"Title: {meta['title']}", f"Generated (UTC): {meta['generated_utc']}",
             f"Rows: {meta['rows']}", f"Reporting period: {meta['reporting_period']}", f"Filters: {meta['filters']}",
             "Sources: " + "; ".join(meta["sources"]), "Limitations:"]
    lines += [f"  - {x}" for x in meta["limitations"]]
    return "\n".join(lines) + "\n"


def export_excel(sheets: Dict[str, pd.DataFrame], path: Path, meta: Optional[Dict] = None) -> Path:
    """Excel workbook: a 'Report info' sheet plus one sheet per DataFrame."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        if meta:
            info = [("Title", meta["title"]), ("Generated (UTC)", meta["generated_utc"]), ("Rows", meta["rows"]),
                    ("Reporting period", meta["reporting_period"]), ("Filters", str(meta["filters"]))]
            info += [("Source", s) for s in meta["sources"]] + [("Limitation", x) for x in meta["limitations"]]
            pd.DataFrame(info, columns=["Item", "Value"]).to_excel(xw, sheet_name="Report info", index=False)
            xw.sheets["Report info"].column_dimensions["A"].width = 18
            xw.sheets["Report info"].column_dimensions["B"].width = 110
        for name, df in sheets.items():
            safe = name[:31]
            _flat(df).to_excel(xw, sheet_name=safe, index=False)
            ws = xw.sheets[safe]
            ws.freeze_panes = "A2"
            for i, col in enumerate(df.columns, start=1):
                lengths = [len(str(v)) for v in df[col].head(500) if v is not None and not (isinstance(v, float) and v != v)
                           and str(v) not in ("<NA>", "nan", "NaT", "None")]
                typical = sorted(lengths)[int(0.9 * (len(lengths) - 1))] if lengths else 0
                width = min(48, max(10, typical + 2, len(str(col)) + 2))
                ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = width
    return path


def export_pdf(path: Path, meta: Dict, metrics: Dict[str, object], figures: Sequence = (),
               tables: Optional[Dict[str, pd.DataFrame]] = None) -> Path:
    """Multi-page PDF: summary page (filters, metrics, sources, limitations), charts, tables."""
    import matplotlib
    matplotlib.use("Agg", force=False)
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(path) as pdf:
        fig = plt.figure(figsize=(8.27, 11.69))
        fig.text(0.07, 0.95, meta["title"], fontsize=18, fontweight="bold", va="top")
        fig.text(0.07, 0.92, f"{APP_LINE}  |  generated {meta['generated_utc']} UTC", fontsize=9, color="#555", va="top")
        y = 0.87
        def block(head: str, lines: List[str]):
            nonlocal y
            fig.text(0.07, y, head, fontsize=11, fontweight="bold", va="top"); y -= 0.027
            for ln in lines:
                wrapped = _wrap(ln, 105)
                for w in wrapped:
                    fig.text(0.09, y, w, fontsize=8.5, va="top"); y -= 0.0195
            y -= 0.012
        block("Report scope", [f"Reporting period: {meta['reporting_period']}", f"Rows: {meta['rows']}",
                                f"Filters: {meta['filters']}"])
        block("Key metrics", [f"{k}: {v}" for k, v in metrics.items()] or ["(none)"])
        block("Data sources", meta["sources"])
        block("Limitations", ["- " + x for x in meta["limitations"]])
        pdf.savefig(fig); plt.close(fig)
        for f in figures:
            pdf.savefig(f, bbox_inches="tight")
        for name, df in (tables or {}).items():
            if df is None or df.empty:
                continue
            fig, ax = plt.subplots(figsize=(11.69, 8.27)); ax.axis("off")
            ax.set_title(name, loc="left", fontweight="bold")
            shown = df.head(35).copy()
            shown = shown.round(2).astype(str)
            tb = ax.table(cellText=shown.values, colLabels=list(shown.columns), loc="upper left", cellLoc="left")
            tb.auto_set_font_size(False); tb.set_fontsize(6.5); tb.scale(1, 1.15)
            for i in range(len(shown.columns)):
                tb.auto_set_column_width(i)
            if len(df) > 35:
                ax.text(0, -0.02, f"(first 35 of {len(df)} rows - export CSV/Excel for the full data)", fontsize=7, transform=ax.transAxes)
            pdf.savefig(fig); plt.close(fig)
    return path


def _wrap(text: str, width: int) -> List[str]:
    import textwrap
    return textwrap.wrap(str(text), width) or [""]
