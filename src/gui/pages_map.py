"""Interactive flight route map (offline Matplotlib map, real airport coordinates only).

No external map service is used: the land outline is Natural Earth 1:110m data
shipped in ``data/reference`` and airport positions come from OurAirports
reference data. Routes are great-circle arcs between those real coordinates.
"""

from __future__ import annotations

import json
from typing import List, Optional

import numpy as np
import pandas as pd
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QCheckBox, QComboBox, QLineEdit, QSizePolicy, QSpinBox, QToolTip

from src import palette as P, reference, route_data

from .components import info_label
from .pages import _kpis, _plain_button
from .tables import DataTable
from .perf import render_queue
from .widgets import Card, EmptyState, FlowRow, PageBase, ResponsiveGrid, labelled

_LAND: Optional[List[np.ndarray]] = None


def land_polygons() -> List[np.ndarray]:
    """Exterior rings of the Natural Earth land polygons (cached)."""
    global _LAND
    if _LAND is None:
        rings: List[np.ndarray] = []
        try:
            data = json.loads(reference.LAND_GEOJSON.read_text(encoding="utf-8"))
            for feat in data.get("features", []):
                geom = feat.get("geometry") or {}
                polys = geom.get("coordinates", [])
                if geom.get("type") == "Polygon":
                    polys = [polys]
                elif geom.get("type") != "MultiPolygon":
                    continue
                for poly in polys:
                    if poly:
                        rings.append(np.asarray(poly[0], dtype=float)[:, :2])
        except (OSError, ValueError):
            rings = []       # no basemap file: routes and airports are still drawn
        _LAND = rings
    return _LAND


class RouteMapPage(PageBase):
    title = "Flight Route Map"
    subtitle = "Routes between airports in the stored dataset - hover for details, click to filter"
    MAX_ROUTES = 600

    def __init__(self, main):
        super().__init__(main)
        self._routes = pd.DataFrame()
        self._view = pd.DataFrame()
        self._points = pd.DataFrame()
        self._ref = pd.DataFrame()
        self._sel: Optional[int] = None
        self._xy: Optional[np.ndarray] = None
        self.ax = None

        self.empty_state = EmptyState("No routes to draw yet", "Retrieve flights first (ETL Monitoring > Refresh). Routes are drawn between "
                                      "airports that have verified coordinates.", "Go to ETL Monitoring", lambda: self.main.navigate("etl"))
        self.body.addWidget(self.empty_state)
        grid, cards = _kpis([("Routes shown", P.COBALT), ("Airports shown", P.TEAL), ("Flights on routes", "#C48A1B"), ("Longest route", P.NAVY_SOFT)], 170)
        self.k_r, self.k_a, self.k_f, self.k_l = cards
        self.body.addWidget(grid)

        ctl = Card()
        ctl.add_title("Filters")
        row = ResponsiveGrid(min_item_width=170, max_columns=6)
        self.f_origin, self.f_dest = QComboBox(), QComboBox()
        self.f_airline = QLineEdit()
        self.f_airline.setPlaceholderText("Airline name contains\u2026")
        self.f_min = QSpinBox()
        self.f_min.setRange(1, 200)
        self.f_labels = QCheckBox("Airport labels")
        self.f_labels.setChecked(True)
        reset = _plain_button("Reset filters")
        reset.clicked.connect(self._reset)
        for cap, w in (("Origin", self.f_origin), ("Destination", self.f_dest), ("Airline", self.f_airline), ("Min flights", self.f_min)):
            row.add(labelled(cap, w))
        extras = FlowRow()
        extras.addWidget(self.f_labels)
        extras.addWidget(reset)
        row.add(extras)
        ctl.body.addWidget(row)
        for w in (self.f_origin, self.f_dest):
            w.currentIndexChanged.connect(self._apply)
        self.f_airline.textChanged.connect(self._apply)
        self.f_min.valueChanged.connect(self._apply)
        self.f_labels.toggled.connect(self._draw)
        self.body.addWidget(ctl)

        self.map_card = Card()
        self.fig = Figure(figsize=(9, 5), facecolor=P.SURFACE, layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.canvas.setMinimumHeight(430)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.canvas.mpl_connect("button_press_event", self._on_click)
        self.map_card.body.addWidget(self.canvas)
        self.map_note = info_label("")
        self.map_card.body.addWidget(self.map_note)
        self.body.addWidget(self.map_card)

        det = Card()
        det.add_title("Route details", "Select a route in the table (or click airports on the map).")
        self.detail = info_label("No route selected.")
        self.detail.setTextFormat(Qt.TextFormat.RichText)
        det.body.addWidget(self.detail)
        self.table = DataTable("No routes match the filters.")
        self.table.setMinimumHeight(240)
        det.body.addWidget(self.table)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._select_row())
        self.body.addWidget(det)
        self.body.addStretch(1)

    # ---------------------------------------------------------------- data
    def reload(self) -> None:
        fl = self.main.store.flights()
        self._ref = reference.airport_reference()
        self._routes = self.main.store.memo("route_table", lambda: route_data.route_table(fl, self._ref))
        has = not self._routes.empty
        self.empty_state.setVisible(not has)
        for w in (self.map_card, self.table.parentWidget()):
            if w is not None:
                w.setVisible(has)
        if not has:
            return
        origins = sorted(self._routes["origin"].unique())
        dests = sorted(self._routes["destination"].unique())
        for box, vals, first in ((self.f_origin, origins, "All origins"), (self.f_dest, dests, "All destinations")):
            cur = box.currentData()
            box.blockSignals(True)
            box.clear()
            box.addItem(first, None)
            for v in vals:
                box.addItem(v, v)
            box.setCurrentIndex(max(box.findData(cur), 0))
            box.blockSignals(False)
        pre = self.main.shared.pop("map_origin", None)
        if pre and self.f_origin.findData(pre) >= 0:
            self.f_origin.setCurrentIndex(self.f_origin.findData(pre))
        self._apply()

    def _reset(self) -> None:
        for b in (self.f_origin, self.f_dest):
            b.setCurrentIndex(0)
        self.f_airline.clear()
        self.f_min.setValue(1)
        self._sel = None
        self._apply()

    def _apply(self) -> None:
        r = route_data.filter_routes(self._routes, self.f_origin.currentData(), self.f_dest.currentData(),
                                     self.f_min.value(), self.f_airline.text().strip() or None)
        self._view = r.head(self.MAX_ROUTES).reset_index(drop=True)
        self._points = route_data.airport_points(self._view)
        self._sel = None
        self.k_r.set_value(f"{len(self._view):,}", f"of {len(self._routes):,} with coordinates")
        self.k_a.set_value(f"{len(self._points):,}", "with verified coordinates")
        self.k_f.set_value(f"{int(self._view['flights'].sum()):,}" if len(self._view) else "0", "flight records")
        if len(self._view):
            lg = self._view.sort_values("distance_km").iloc[-1]
            self.k_l.set_value(f"{int(lg['distance_km']):,} km", f"{lg['origin']} \u2192 {lg['destination']}")
        else:
            self.k_l.set_value("\u2013", "no routes")
        cols = ["origin", "destination", "flights", "airlines", "airline_list", "distance_km"]
        self.table.set_frame(self._view, cols)
        dropped = self._routes.attrs.get("dropped_no_coords", 0)
        note = ("Land outline: Natural Earth (public domain); airport coordinates: OurAirports (public domain); routes are great-circle "
                "arcs between those coordinates, not actual flight paths. Line width and point size scale with flight records in this dataset. ")
        if dropped:
            note += f"{dropped} route(s) were skipped because an airport has no verified coordinates. "
        if len(self._routes) > self.MAX_ROUTES and len(self._view) == self.MAX_ROUTES:
            note += f"Showing the {self.MAX_ROUTES} busiest routes - use the filters to narrow down. "
        self.map_note.setText(note)
        self.detail.setText("No route selected.")
        self._draw_pending = True
        render_queue.submit(self, self._draw_job)   # the basemap and arcs are drawn from the event loop, not the click

    # ---------------------------------------------------------------- drawing
    def _draw_job(self) -> None:
        if self._draw_pending and self.isVisible():
            self._draw_pending = False
            self._draw()

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if getattr(self, "_draw_pending", False):
            render_queue.submit(self, self._draw_job)

    def _draw(self) -> None:
        self.fig.clear()
        ax = self.ax = self.fig.add_subplot(111)
        ax.set_facecolor("#DCE8F5")
        v, pts = self._view, self._points
        if v.empty:
            ax.text(0.5, 0.5, "No routes match the current filters.", ha="center", va="center", transform=ax.transAxes, color=P.TEXT_MUTED)
            ax.set_axis_off()
            self.canvas.draw_idle()
            self._xy = None
            return
        lon_all = np.concatenate([v["o_lon"].to_numpy(), v["d_lon"].to_numpy()])
        lat_all = np.concatenate([v["o_lat"].to_numpy(), v["d_lat"].to_numpy()])
        for shift in (-360, 0, 360):
            polys = [np.column_stack([r[:, 0] + shift, r[:, 1]]) for r in land_polygons()]
            if polys:
                ax.add_collection(PolyCollection(polys, facecolors="#FFFFFF", edgecolors="#B3C1D4", linewidths=0.5, zorder=1))
        segs, widths = [], []
        mx = max(v["flights"].max(), 1)
        arcs = {}
        for i, r in v.iterrows():
            lons, lats = reference.great_circle_points(r.o_lat, r.o_lon, r.d_lat, r.d_lon, 40)
            arcs[i] = (lons, lats)
            segs.append(np.column_stack([lons, lats]))
            widths.append(0.6 + 2.0 * np.log1p(r.flights) / np.log1p(mx))
        ax.add_collection(LineCollection(segs, linewidths=widths, colors=P.COBALT, alpha=0.45, zorder=2))
        if self._sel is not None and self._sel in arcs:
            lo, la = arcs[self._sel]
            ax.plot(lo, la, color=P.WARNING, lw=3.2, zorder=4, solid_capstyle="round")
        allx = np.concatenate([np.asarray(a[0]) for a in arcs.values()] + [lon_all])
        sizes = 22 + 90 * (pts["flights"].to_numpy() / max(pts["flights"].max(), 1))
        ax.scatter(pts["lon"], pts["lat"], s=sizes, c=P.TEAL, edgecolors="white", linewidths=0.8, zorder=5)
        if self.f_labels.isChecked():
            for r in pts.head(14).itertuples():
                ax.annotate(r.iata, (r.lon, r.lat), xytext=(4, 4), textcoords="offset points", fontsize=7.5, color=P.TEXT, zorder=6)
        pad = 6
        x0, x1 = float(allx.min()) - pad, float(allx.max()) + pad
        y0, y1 = max(float(lat_all.min()) - pad, -85), min(float(lat_all.max()) + pad, 85)
        if x1 - x0 < 30:
            c = (x0 + x1) / 2; x0, x1 = c - 15, c + 15
        if y1 - y0 < 18:
            c = (y0 + y1) / 2; y0, y1 = c - 9, c + 9
        ax.set_xlim(x0, x1)
        ax.set_ylim(y0, y1)
        ax.set_title(f"Flight routes in the stored dataset ({len(v)} routes, {len(pts)} airports)", loc="left", fontsize=11, fontweight="bold", color=P.TEXT)
        ax.set_xlabel("Longitude (\u00b0)", fontsize=9, color=P.TEXT_MUTED)
        ax.set_ylabel("Latitude (\u00b0)", fontsize=9, color=P.TEXT_MUTED)
        ax.tick_params(labelsize=8, colors=P.TEXT_MUTED, length=0)
        ax.grid(color="#D5DEEA", lw=0.5)
        self._xy = pts[["lon", "lat"]].to_numpy()
        self.canvas.draw_idle()

    # ---------------------------------------------------------------- interaction
    def airport_at(self, px: float, py: float, radius: float = 12.0) -> Optional[str]:
        """IATA of the airport within ``radius`` pixels of display point (px, py)."""
        if self.ax is None or self._xy is None or len(self._xy) == 0:
            return None
        disp = self.ax.transData.transform(self._xy)
        d = np.hypot(disp[:, 0] - px, disp[:, 1] - py)
        i = int(np.argmin(d))
        return str(self._points.iloc[i]["iata"]) if d[i] <= radius else None

    def tooltip_for(self, iata: str) -> str:
        info = reference.lookup(iata) or {}
        out = self._view[self._view["origin"] == iata]
        inn = self._view[self._view["destination"] == iata]
        lines = [f"{iata} \u2013 {info.get('name', 'unknown airport')}", f"{info.get('city') or ''} {info.get('country') or ''}".strip(),
                 f"{int(out['flights'].sum())} departing / {int(inn['flights'].sum())} arriving flight records (shown routes)",
                 f"{len(out)} outbound, {len(inn)} inbound route(s)"]
        return "\n".join(l for l in lines if l)

    def _on_motion(self, event) -> None:
        if event.inaxes is None or event.x is None:
            QToolTip.hideText()
            return
        code = self.airport_at(event.x, event.y)
        if code:
            QToolTip.showText(QCursor.pos(), self.tooltip_for(code), self.canvas)
        else:
            QToolTip.hideText()

    def _on_click(self, event) -> None:
        if event.inaxes is None:
            return
        code = self.airport_at(event.x, event.y)
        if code:
            self.pick_airport(code)

    def pick_airport(self, code: str) -> None:
        """Click behaviour: first pick sets the origin, the next one the destination."""
        if self.f_origin.currentData() is None and self.f_origin.findData(code) >= 0:
            self.f_origin.setCurrentIndex(self.f_origin.findData(code))
        elif self.f_dest.currentData() is None and self.f_dest.findData(code) >= 0:
            self.f_dest.setCurrentIndex(self.f_dest.findData(code))
        elif self.f_origin.findData(code) >= 0:
            self.f_dest.setCurrentIndex(0)
            self.f_origin.setCurrentIndex(self.f_origin.findData(code))
        self.detail.setText(self.tooltip_for(code).replace("\n", "<br>"))

    def _select_row(self) -> None:
        rows = self.table.selected_rows()
        if not rows or self._view.empty:
            return
        self.select_route(rows[0])

    def select_route(self, i: int) -> None:
        r = self._view.iloc[i]
        self._sel = i
        o, d = reference.lookup(r["origin"]) or {}, reference.lookup(r["destination"]) or {}
        self.detail.setText(
            f"<b>{r['origin']} \u2192 {r['destination']}</b> &nbsp; {o.get('city', '')} \u2192 {d.get('city', '')}<br>"
            f"{int(r['flights'])} flight record(s) \u2022 {int(r['airlines'])} airline(s): {r['airline_list'] or 'not provided'}<br>"
            f"Great-circle distance {int(r['distance_km']):,} km")
        self._draw()
