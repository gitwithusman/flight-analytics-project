"""Flight Status & Delays, Airports, Airlines, ETL Monitoring, Reports, Destination Weather."""

from __future__ import annotations

from typing import Optional

import pandas as pd
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QSpinBox,
)

from src import (airline_analytics as aa, airport_analytics as ap, config, database, database_travel,
                 delay_analytics as da, etl_monitor, palette as P, pipeline, reference, reports,
                 travel_charts as tc, utils)
from src.providers import status as status_provider, weather as wx

from .components import (AirportEdit, ExportBar, FigureCard, OriginBadge, date_edit, info_label, notice_box)
from .pages import WeatherInsightsPage, _kpis, _plain_button, _primary_button
from .tables import DataTable
from .theme import SP_LG
from .widgets import Card, EmptyState, FlowRow, PageBase, ResponsiveGrid, labelled

ALL = "All"


def _combo(items, first: str = ALL) -> QComboBox:
    c = QComboBox()
    c.addItem(first, None)
    for v in items:
        c.addItem(str(v), v)
    return c


def _fill(combo: QComboBox, values, first: str = ALL) -> None:
    cur = combo.currentData()
    combo.blockSignals(True)
    combo.clear()
    combo.addItem(first, None)
    for v in values:
        combo.addItem(str(v), v)
    combo.setCurrentIndex(max(combo.findData(cur), 0))
    combo.blockSignals(False)


# =========================================================================== Flight Status & Delays
class FlightStatusPage(PageBase):
    title = "Flight Status & Delays"
    subtitle = "Live status lookup, plus delay analytics over stored (historical) snapshots"
    SNAP_COLS = ["flight_date", "flight_iata", "airline_name", "display_status", "dep_iata", "arr_iata", "dep_scheduled",
                 "dep_estimated", "arr_scheduled", "arr_estimated", "max_delay_min", "retrieved_at"]
    LIVE_COLS = ["flight_iata", "airline_name", "dep_iata", "arr_iata", "dep_scheduled", "dep_estimated", "dep_actual",
                 "arr_scheduled", "arr_estimated", "status", "dep_delay_min", "arr_delay_min", "api_updated", "observed_at"]

    def __init__(self, main):
        super().__init__(main)
        self._flights = pd.DataFrame()
        self._shown = pd.DataFrame()

        live = Card()
        head = QHBoxLayout()
        t = QLabel("Live flight status")
        t.setObjectName("cardTitle")
        self.live_badge = OriginBadge("live_api")
        self.live_badge.hide()
        head.addWidget(t)
        head.addWidget(self.live_badge)
        head.addStretch(1)
        live.body.addLayout(head)
        live.body.addWidget(info_label("Looks up one flight number with the AviationStack API. Only a successful API response is labelled "
                                       "LIVE; everything lower on this page is stored history."))
        self.flight_no = QLineEdit()
        self.flight_no.setPlaceholderText("Flight number, e.g. PK301")
        self.flight_no.setMaximumWidth(260)
        self.flight_no.returnPressed.connect(self._lookup)
        self.lookup_btn = _primary_button("Look up status", "explorer")
        self.lookup_btn.clicked.connect(self._lookup)
        row = FlowRow()
        row.addWidget(labelled("Flight number", self.flight_no))
        row.addWidget(self.lookup_btn)
        live.body.addWidget(row)
        self.live_msg = info_label("")
        live.body.addWidget(self.live_msg)
        self.live_table = DataTable("No live lookup yet.")
        self.live_table.setMinimumHeight(110)
        self.live_table.setMaximumHeight(170)
        live.body.addWidget(self.live_table)
        self.body.addWidget(live)

        hist = Card()
        hist.add_title("Delay analytics - stored snapshots", "")
        self.hist_badge = OriginBadge("historical", "HISTORICAL SNAPSHOTS")
        hist.body.addWidget(self.hist_badge, alignment=Qt.AlignmentFlag.AlignLeft)
        g = ResponsiveGrid(min_item_width=150, max_columns=5)
        self.f_airline, self.f_airport, self.f_status = _combo([]), _combo([]), _combo([])
        self.f_from, self.f_to = _combo([], "Any date"), _combo([], "Any date")
        for i, (cap, w_) in enumerate((("Airline", self.f_airline), ("Airport", self.f_airport), ("Status", self.f_status),
                                       ("From date", self.f_from), ("To date", self.f_to))):
            g.add(labelled(cap, w_))
            if isinstance(w_, QComboBox):
                w_.currentIndexChanged.connect(self._apply)
        hist.body.addWidget(g)
        self.scope = info_label("")
        hist.body.addWidget(self.scope)
        self.export = ExportBar(self._export_data, "flight_status_delays", figures=self._figures, metrics=self._metrics)
        hist.body.addWidget(self.export)
        self.body.addWidget(hist)

        grid, cards = _kpis([("Flights shown", P.COBALT), ("With delay data", P.TEAL), ("Delayed share", "#C48A1B"),
                             ("Average delay", P.NAVY_SOFT), ("Cancelled", "#B8483D")], 170)
        self.k_n, self.k_dv, self.k_share, self.k_avg, self.k_cx = cards
        self.body.addWidget(grid)
        self.empty_state = EmptyState("No stored flights yet", "Retrieve flights first (ETL Monitoring > Refresh, or Data Management).")
        self.body.addWidget(self.empty_state)
        self.charts = {k: FigureCard(t_, 230) for k, t_ in (("airline", "Delay by airline"), ("dist", "Delay distribution"),
                                                             ("airport", "Delay by departure airport"), ("hour", "Delay by hour"))}
        g2 = ResponsiveGrid(min_item_width=360, max_columns=2, spacing=SP_LG)
        for c in self.charts.values():
            g2.add(c)
        self.body.addWidget(g2)
        self.cx_note = info_label("")
        self.body.addWidget(self.cx_note)
        card = Card()
        card.add_title("Stored flights (historical snapshots)")
        self.table = DataTable("No flights match the filters.")
        self.table.setMinimumHeight(300)
        card.body.addWidget(self.table)
        self.body.addWidget(card)
        self.body.addStretch(1)

    # ------------------------------------------------------------ live lookup
    def _lookup(self) -> None:
        code = self.flight_no.text().strip()
        if not code:
            self.live_msg.setText("Enter a flight number first.")
            return
        if self.main._refreshing:
            self.main.notify("Another data operation is running - please wait.", "warning")
            return
        self.lookup_btn.setEnabled(False)
        self.live_msg.setText("Looking up\u2026")
        self.main.tasks.submit(status_provider.lookup_live_status, flight_iata=code, on_done=self._lookup_done,
                               on_error=self._lookup_failed, owner=self)

    def _lookup_failed(self, msg: str) -> None:
        self.lookup_btn.setEnabled(True)
        self.live_badge.hide()
        self.live_msg.setText(msg)
        self.live_table.set_frame(pd.DataFrame())

    def _lookup_done(self, df: pd.DataFrame) -> None:
        self.lookup_btn.setEnabled(True)
        if df.empty:
            self.live_badge.hide()
            self.live_msg.setText("The API returned no matching flight. Flight numbers are only returned while the flight is in the "
                                  "provider's current data window.")
            self.live_table.set_frame(df)
            return
        database_travel.insert_status_observations(df)
        self.live_badge.set_origin("live_api")
        self.live_badge.show()
        self.live_msg.setText(f"{len(df)} record(s) returned by the API at {df['observed_at'].iloc[0][:19].replace('T', ' ')} UTC. "
                              "Statuses and delays are exactly as reported by the provider.")
        self.live_table.set_frame(df, self.LIVE_COLS)

    # ------------------------------------------------------------ analytics
    def reload(self) -> None:
        df = self.main.store.flights()
        if df.empty:
            self._flights = df
        else:
            self._flights = df.copy()
            self._flights["display_status"] = self._flights.apply(da.display_status, axis=1)
        d = self._flights
        has = not d.empty
        _fill(self.f_airline, sorted(d["airline_iata"].dropna().unique()) if has else [], "All airlines")
        _fill(self.f_airport, sorted(set(d["dep_iata"]) | set(d["arr_iata"]) - {""}) if has else [], "All airports")
        _fill(self.f_status, sorted(d["flight_status"].dropna().unique()) if has else [], "All statuses")
        dates = sorted(d["flight_date"].astype(str).unique()) if has else []
        _fill(self.f_from, dates, "Any date")
        _fill(self.f_to, dates, "Any date")
        self.empty_state.setVisible(not has)
        self._apply()

    def _apply(self) -> None:
        d = self._flights
        if d.empty:
            self._shown = d
            for c in self.charts.values():
                c.empty("No flight data stored yet.")
            self.table.set_frame(d)
            for k in (self.k_n, self.k_dv, self.k_share, self.k_avg, self.k_cx):
                k.set_value("\u2013", "no data")
            self.scope.setText("")
            return
        out = da.filter_flights(d, self.f_airline.currentData(), self.f_airport.currentData(), self.f_from.currentData(),
                                self.f_to.currentData(), self.f_status.currentData())
        self._shown = out
        dv = out["max_delay_min"].dropna()
        self.k_n.set_value(f"{len(out):,}", f"of {len(d):,} stored")
        self.k_dv.set_value(f"{len(dv):,}", f"{100 * len(dv) / len(out):.0f}% of shown" if len(out) else "")
        self.k_share.set_value(f"{100 * (dv > 0).mean():.1f}%" if len(dv) else "\u2013", "of flights with delay data")
        self.k_avg.set_value(f"{dv.mean():.1f} min" if len(dv) else "\u2013", f"median {dv.median():.0f} min" if len(dv) else "")
        cx = da.cancellation_stats(out)
        self.k_cx.set_value(str(cx["cancelled"]), f"{cx['rate_pct']}% of shown" if cx["rate_pct"] is not None else "")
        dates = pd.to_datetime(out["flight_date"], errors="coerce").dropna()
        self.scope.setText(
            (f"{len(out)} stored flight records, flight dates {dates.min().date()} to {dates.max().date()}; last retrieved "
             f"{out['retrieved_at'].max()}. " if len(dates) else "") +
            "These are historical snapshots retrieved earlier - not live status. A missing delay value is not treated as on time.")
        self.charts["airline"].render(lambda f: tc.delay_by_group(f, da.by_airline(out), "airline_name", "Mean delay by airline"))
        self.charts["dist"].render(lambda f: tc.delay_distribution(f, out["max_delay_min"]))
        self.charts["airport"].render(lambda f: tc.delay_by_group(f, da.by_airport(out), "dep_iata", "Mean delay by departure airport"))
        self.charts["hour"].render(lambda f: tc.delay_by_hour(f, da.by_departure_hour(out)))
        self.cx_note.setText("Cancellation statistics: " + (
            f"{cx['cancelled']} of {cx['flights']} shown flights have status 'cancelled'."
            if cx["flights"] else "no flights shown.") + " (The free API plan reports few cancellations; zero here means none were stored.)")
        self.table.set_frame(out, self.SNAP_COLS)

    def _export_data(self):
        df = self._shown.drop(columns=["display_status"], errors="ignore") if not self._shown.empty else self._shown
        meta = reports.metadata("Flight status & delays", {"airline": self.f_airline.currentData(), "airport": self.f_airport.currentData(),
                                                            "status": self.f_status.currentData(), "from": self.f_from.currentData(),
                                                            "to": self.f_to.currentData()},
                                f"flight dates {df['flight_date'].min()} to {df['flight_date'].max()}" if not df.empty else "-",
                                ["AviationStack /v1/flights snapshots stored by the ETL pipeline (HISTORICAL)"],
                                ["Snapshots are not live status.", "Flights without a delay value are excluded from delay statistics."], len(df))
        return df, meta

    def _metrics(self) -> dict:
        dv = self._shown["max_delay_min"].dropna() if not self._shown.empty else pd.Series(dtype=float)
        return {"flights shown": len(self._shown), "with delay data": len(dv),
                "delayed share %": round(100 * float((dv > 0).mean()), 1) if len(dv) else "n/a",
                "average delay (min)": round(float(dv.mean()), 2) if len(dv) else "n/a"}

    def _figures(self):
        from matplotlib.figure import Figure
        out = self._shown
        figs = []
        for fn in (lambda f: tc.delay_by_group(f, da.by_airline(out), "airline_name", "Mean delay by airline"),
                   lambda f: tc.delay_distribution(f, out["max_delay_min"]),
                   lambda f: tc.delay_by_hour(f, da.by_departure_hour(out))):
            fig = Figure(figsize=(8.27, 5), layout="constrained")
            fn(fig)
            figs.append(fig)
        return figs


# =========================================================================== Airports
class AirportDashboardPage(PageBase):
    title = "Airport Analytics"
    subtitle = "Traffic, routes and airlines for the airports in the stored dataset"
    COLS = ["iata", "name", "city", "country", "latitude", "longitude", "departures", "arrivals", "total", "destinations", "airlines"]

    def __init__(self, main):
        super().__init__(main)
        self._table = pd.DataFrame()
        self._flights = pd.DataFrame()
        grid, cards = _kpis([("Airports observed", P.COBALT), ("Busiest in dataset", P.TEAL), ("Flight records", "#C48A1B"),
                             ("Distinct routes", P.NAVY_SOFT)], 200)
        self.k_air, self.k_busy, self.k_fl, self.k_rt = cards
        self.body.addWidget(grid)
        self.scope = info_label("")
        self.body.addWidget(self.scope)
        self.empty_state = EmptyState("No airport data yet", "Retrieve flights first (ETL Monitoring > Refresh).")
        self.body.addWidget(self.empty_state)
        self.chart = FigureCard("Busiest airports", 300)
        self.body.addWidget(self.chart)

        card = Card()
        card.add_title("Airports", "Search by code, name, city or country; select a row for details. Coordinates come from OurAirports reference data.")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search airports\u2026")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        card.body.addWidget(self.search)
        self.table = DataTable("No airports match your search.")
        self.table.setMinimumHeight(260)
        card.body.addWidget(self.table)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._select())
        self.export = ExportBar(self._export_data, "airport_analytics", pdf=False)
        card.body.addWidget(self.export)
        self.body.addWidget(card)

        self.detail = Card()
        self.detail_title = QLabel("Airport details")
        self.detail_title.setObjectName("cardTitle")
        self.detail.body.addWidget(self.detail_title)
        self.detail_text = info_label("Select an airport above.")
        self.detail_text.setTextFormat(Qt.TextFormat.RichText)
        self.detail.body.addWidget(self.detail_text)
        self.map_btn = _plain_button("Show routes on the map")
        self.map_btn.setEnabled(False)
        self.map_btn.clicked.connect(self._show_map)
        self.detail.body.addWidget(self.map_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        drow = ResponsiveGrid(min_item_width=320, max_columns=2, spacing=SP_LG)
        self.dest_chart = FigureCard("Popular destinations", 220)
        self.air_chart = FigureCard("Airlines at this airport", 220)
        drow.add(self.dest_chart)
        drow.add(self.air_chart)
        self.detail.body.addWidget(drow)
        self.dest_table = DataTable("No outbound routes in the dataset.")
        self.dest_table.setMinimumHeight(150)
        self.orig_table = DataTable("No inbound routes in the dataset.")
        self.orig_table.setMinimumHeight(150)
        tr = ResponsiveGrid(min_item_width=320, max_columns=2, spacing=SP_LG)
        a, b = Card(), Card()
        a.add_title("Routes departing")
        a.body.addWidget(self.dest_table)
        b.add_title("Routes arriving")
        b.body.addWidget(self.orig_table)
        tr.add(a)
        tr.add(b)
        self.detail.body.addWidget(tr)
        self.body.addWidget(self.detail)
        self.body.addStretch(1)
        self._sel: Optional[str] = None

    def reload(self) -> None:
        fl = self.main.store.flights()
        self._flights = fl
        ref = reference.airport_reference()
        self._table = self.main.store.memo("airport_traffic", lambda: ap.traffic_table(fl, ref))
        has = not self._table.empty
        self.empty_state.setVisible(not has)
        self.detail.setVisible(has)
        self.chart.setVisible(has)
        if not has:
            for k in (self.k_air, self.k_busy, self.k_fl, self.k_rt):
                k.set_value("\u2013", "no data")
            self.table.set_frame(self._table)
            self.scope.setText("")
            return
        top = self._table.iloc[0]
        self.k_air.set_value(f"{len(self._table):,}", "in this dataset")
        self.k_busy.set_value(top["iata"], f"{int(top['total'])} records (dataset only)")
        self.k_fl.set_value(f"{len(fl):,}", "stored flights")
        self.k_rt.set_value(f"{fl[['dep_iata', 'arr_iata']].drop_duplicates().shape[0]:,}", "origin-destination pairs")
        self.scope.setText(ap.scope_note(fl, self._table))
        self.chart.render(lambda f: tc.airport_traffic(f, self._table))
        self._filter()

    def _filter(self) -> None:
        t = self._table
        text = self.search.text().strip().lower()
        if text and not t.empty:
            hay = (t["iata"].fillna("") + " " + t["name"].fillna("") + " " + t["city"].fillna("") + " " + t["country"].fillna("")).str.lower()
            t = t[hay.str.contains(text, regex=False)]
        self._view = t.reset_index(drop=True)
        self.table.set_frame(self._view, self.COLS)

    def _select(self) -> None:
        rows = self.table.selected_rows()
        if not rows:
            return
        r = self._view.iloc[rows[0]]
        self._sel = r["iata"]
        d = ap.detail(self._flights, r["iata"])
        loc = f"{r['city'] or 'city not provided'}, {r['country'] or 'country not provided'}"
        coords = f"{r['latitude']:.4f}, {r['longitude']:.4f}" if pd.notna(r["latitude"]) else "coordinates not available"
        self.detail_title.setText(f"{r['iata']} \u2013 {r['name'] or 'name not provided'}")
        st = ", ".join(f"{k}: {v}" for k, v in d["status"].items()) or "none"
        self.detail_text.setText(
            f"{loc} &nbsp;|&nbsp; {coords} &nbsp;|&nbsp; departures {d['departures']}, arrivals {d['arrivals']} (in this dataset)<br>"
            f"Status mix: {st}<br>" +
            (f"Delays: {d['delay_values']} flights report a delay value; {d['delayed_pct']}% of them delayed, mean {d['avg_delay_min']} min."
             if d["delay_values"] else "Delays: no departing flight here reports a delay value."))
        self.dest_table.set_frame(d["destinations"])
        self.orig_table.set_frame(d["origins"])
        dst = d["destinations"].head(8)
        self.dest_chart.render(lambda f: tc.bar_counts(f, list(dst["destination"]), list(dst["flights"]), "Departing flights by destination", "Flights"),
                               has_data=not dst.empty)
        al = d["airlines"].head(8)
        self.air_chart.render(lambda f: tc.bar_counts(f, [str(n or c) for c, n in zip(al["airline_iata"], al["airline_name"])], list(al["flights"]),
                                                      "Flights by airline", "Flights", color=P.TEAL), has_data=not al.empty)
        if dst.empty:
            self.dest_chart.empty("No departing flights from this airport in the dataset.")
        self.map_btn.setEnabled(True)

    def _show_map(self) -> None:
        if self._sel:
            self.main.shared["map_origin"] = self._sel
            self.main.navigate("map")

    def _export_data(self):
        df = self._view if hasattr(self, "_view") else self._table
        meta = reports.metadata("Airport analytics", {"search": self.search.text()}, "stored flight snapshots",
                                ["Flight counts: AviationStack snapshots (HISTORICAL)", "Coordinates, names: OurAirports (public domain)"],
                                [ap.scope_note(self._flights, self._table)], len(df))
        return df, meta


# =========================================================================== Airlines
class AirlinePerformancePage(PageBase):
    title = "Airline Performance"
    subtitle = "Compare airlines using the records actually stored - sample sizes shown"
    COLS = ["airline_iata", "airline_name", "flights", "routes", "delay_values", "avg_delay_min", "delayed_pct", "cancel_rate_pct",
            "small_sample"]

    def __init__(self, main):
        super().__init__(main)
        self._tbl = pd.DataFrame()
        self._flights = pd.DataFrame()
        self.period = info_label("")
        self.body.addWidget(self.period)
        self.body.addWidget(notice_box("Flight count is not a quality score. Rows marked small sample (fewer than "
                                       f"{aa.MIN_FLIGHTS} flights or {aa.MIN_DELAY_VALUES} delay values) are shown but never ranked "
                                       "on delay metrics.", "info"))
        card = Card()
        card.add_title("Airline table")
        row = ResponsiveGrid(min_item_width=170, max_columns=3)
        self.rank = QComboBox()
        self.rank.addItems(["Flights (most first)", "Mean delay (lowest first)", "Delayed share (lowest first)"])
        self.rank.currentIndexChanged.connect(self._rebuild)
        self.min_flights = QSpinBox()
        self.min_flights.setRange(1, 500)
        self.min_flights.setValue(1)
        self.min_flights.valueChanged.connect(self._rebuild)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search airline\u2026")
        self.search.textChanged.connect(self._rebuild)
        row.add(labelled("Rank by", self.rank))
        row.add(labelled("Minimum flights", self.min_flights))
        row.add(labelled("Search", self.search))
        card.body.addWidget(row)
        self.rank_note = info_label("")
        card.body.addWidget(self.rank_note)
        self.table = DataTable("No airlines match.")
        self.table.setMinimumHeight(300)
        card.body.addWidget(self.table)
        self.export = ExportBar(self._export_data, "airline_performance", pdf=False)
        card.body.addWidget(self.export)
        self.body.addWidget(card)

        cmp_card = Card()
        cmp_card.add_title("Side-by-side comparison", "Tick two or more airlines.")
        self.pick = QListWidget()
        self.pick.setMaximumHeight(170)
        self.pick.itemChanged.connect(self._compare)
        cmp_card.body.addWidget(self.pick)
        self.cmp_chart = FigureCard("Comparison", 240)
        cmp_card.body.addWidget(self.cmp_chart)
        self.cmp_table = DataTable("Select airlines to compare.")
        self.cmp_table.setMinimumHeight(220)
        cmp_card.body.addWidget(self.cmp_table)
        self.body.addWidget(cmp_card)

        defs = Card()
        defs.add_title("How each metric is calculated")
        for k, v in aa.METRIC_DEFINITIONS.items():
            defs.body.addWidget(info_label(f"<b>{k}</b>: {v}"))
        self.body.addWidget(defs)
        self.body.addStretch(1)

    def reload(self) -> None:
        self._flights = self.main.store.flights()
        self._tbl = self.main.store.memo("airline_table", lambda: aa.table(self._flights))
        self.period.setText("Reporting period: " + aa.reporting_period(self._flights) + ". Averages use only records that report the value.")
        self.pick.blockSignals(True)
        self.pick.clear()
        for r in self._tbl.itertuples(index=False):
            it = QListWidgetItem(f"{r.airline_name} ({r.airline_iata}) \u2013 {r.flights} flights")
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Unchecked)
            it.setData(Qt.ItemDataRole.UserRole, r.airline_iata)
            self.pick.addItem(it)
        self.pick.blockSignals(False)
        self._rebuild()
        self._compare()

    def _rebuild(self) -> None:
        t = self._tbl
        if t.empty:
            self.table.set_frame(t)
            return
        t = t[t["flights"] >= self.min_flights.value()]
        s = self.search.text().strip().lower()
        if s:
            t = t[(t["airline_name"].fillna("") + " " + t["airline_iata"]).str.lower().str.contains(s, regex=False)]
        i = self.rank.currentIndex()
        if i == 0:
            t = t.sort_values("flights", ascending=False)
            self.rank_note.setText("Ordered by number of stored flight records. This is activity in the dataset, not quality.")
        else:
            key, label = [("avg_delay_min", "mean delay"), ("delayed_pct", "delayed share")][i - 1]
            ok = t[~t["small_sample"]]
            small = t.drop(ok.index)
            t = pd.concat([ok.sort_values(key, na_position="last"), small])
            self.rank_note.setText(f"Ranked by {label}: only airlines with enough data are ranked ({len(ok)} of {len(ok) + len(small)}); "
                                   "the rest follow unranked.")
        self._view = t.reset_index(drop=True)
        self.table.set_frame(self._view, self.COLS)

    def _compare(self) -> None:
        sel = [self.pick.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.pick.count())
               if self.pick.item(i).checkState() == Qt.CheckState.Checked]
        comp = aa.compare(self._tbl, sel) if len(sel) >= 2 else pd.DataFrame()
        self.cmp_chart.render(lambda f: tc.airline_compare(f, comp), has_data=not comp.empty)
        if comp.empty:
            self.cmp_chart.empty("Select two or more airlines to compare.")
        self.cmp_table.set_frame(comp.reset_index().rename(columns={"index": "metric"}) if not comp.empty else comp)

    def _export_data(self):
        df = self._view if hasattr(self, "_view") else self._tbl
        meta = reports.metadata("Airline performance", {"rank": self.rank.currentText(), "min flights": self.min_flights.value(),
                                                         "search": self.search.text()}, aa.reporting_period(self._flights),
                                ["AviationStack flight snapshots (HISTORICAL)"],
                                ["Flight count is not a quality measure.", "Small-sample rows are flagged and not ranked on delay."], len(df))
        return df, meta


# =========================================================================== ETL monitoring
class EtlMonitorPage(PageBase):
    uses_runs = True
    title = "ETL Pipeline Monitoring"
    subtitle = "Run history, data quality, rejected records and logs"

    def __init__(self, main):
        super().__init__(main)
        grid, cards = _kpis([("Pipelines run", P.COBALT), ("Last successful run", P.TEAL), ("Records loaded", "#C48A1B"),
                             ("Records rejected", "#B8483D"), ("Database integrity", P.NAVY_SOFT)], 180)
        self.k_p, self.k_last, self.k_load, self.k_rej, self.k_int = cards
        self.body.addWidget(grid)
        act = Card()
        act.add_title("Operations", "Refreshes use the configured sources only and cannot overlap with another running operation.")
        row = FlowRow()
        self.refresh_btn = _primary_button("Refresh all sources", "refresh")
        self.refresh_btn.clicked.connect(self.refresh_all)
        self.replay_btn = _plain_button("Re-run ETL on raw archive")
        self.replay_btn.clicked.connect(self._replay)
        self.reload_btn = _plain_button("Reload monitor", "refresh")
        self.reload_btn.clicked.connect(lambda: (self.invalidate_view(), self.reload(force=True)))
        row.addWidget(self.refresh_btn)
        row.addWidget(self.replay_btn)
        row.addWidget(self.reload_btn)
        row.addStretch(1)
        act.body.addWidget(row)
        self.op_msg = info_label("Refresh all sources: flights (AviationStack, needs a key). Each step validates, "
                                 "loads into SQLite and is logged below.")
        act.body.addWidget(self.op_msg)
        self.body.addWidget(act)

        c1 = Card()
        c1.add_title("Pipelines")
        self.overview = DataTable("No pipeline has run yet.")
        self.overview.setMinimumHeight(110)
        c1.body.addWidget(self.overview)
        self.body.addWidget(c1)
        g = ResponsiveGrid(min_item_width=360, max_columns=2, spacing=SP_LG)
        self.rec_chart = FigureCard("Records per run", 240)
        self.q_chart = FigureCard("Data quality", 240)
        g.add(self.rec_chart)
        g.add(self.q_chart)
        self.body.addWidget(g)
        self.quality_text = info_label("")
        self.body.addWidget(self.quality_text)
        c2 = Card()
        top = QHBoxLayout()
        t = QLabel("Refresh history")
        t.setObjectName("cardTitle")
        self.pipe_filter = QComboBox()
        self.pipe_filter.addItem("All pipelines", None)
        self.pipe_filter.currentIndexChanged.connect(self._history)
        top.addWidget(t)
        top.addStretch(1)
        top.addWidget(self.pipe_filter)
        c2.body.addLayout(top)
        self.history = DataTable("No runs recorded.")
        self.history.setMinimumHeight(240)
        c2.body.addWidget(self.history)
        self.export = ExportBar(self._export_data, "etl_run_history", pdf=False)
        c2.body.addWidget(self.export)
        self.body.addWidget(c2)
        c3 = Card()
        c3.add_title("Rejected records and reasons", "Records that failed validation are never silently repaired.")
        self.reasons = DataTable("No rejected records.")
        self.reasons.setMinimumHeight(110)
        self.rejected = DataTable("No rejected records.")
        self.rejected.setMinimumHeight(180)
        c3.body.addWidget(self.reasons)
        c3.body.addWidget(self.rejected)
        self.body.addWidget(c3)
        c4 = Card()
        c4.add_title("Application log (latest 150 lines, secrets removed)")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(220)
        self.log.setStyleSheet("font-family: Consolas, 'Courier New', monospace; font-size: 11px;")
        c4.body.addWidget(self.log)
        self.body.addWidget(c4)
        self.body.addStretch(1)

    def reload(self, force: bool = False) -> None:
        ov = etl_monitor.pipeline_overview()
        self.overview.set_frame(ov)
        q = etl_monitor.quality_metrics()
        hist = etl_monitor.run_history(limit=300)
        self.k_p.set_value(str(len(ov)), ", ".join(ov["pipeline"]) if not ov.empty else "none yet")
        ok = hist[hist["status"].isin(["success", "partial", "empty"])]
        self.k_last.set_value(str(ok["refreshed_at"].iloc[0])[:16].replace("T", " ") if len(ok) else "\u2013",
                              f"{ok['pipeline'].iloc[0]} pipeline" if len(ok) else "no successful run")
        self.k_load.set_value(f"{int(hist['records_inserted'].sum() + hist['records_updated'].sum()):,}" if not hist.empty else "0", "inserted + refreshed")
        self.k_rej.set_value(f"{int(hist['records_rejected'].sum()):,}" if not hist.empty else "0", "by validation")
        self.k_int.set_value("Passed" if q["integrity"] else "Check failed", "SQL integrity checks")
        _fill(self.pipe_filter, sorted(hist["pipeline"].unique()) if not hist.empty else [], "All pipelines")
        self._history()
        if hist.empty:
            self.rec_chart.empty("No pipeline runs recorded yet.")
        else:
            self.rec_chart.render(lambda f: tc.etl_records(f, hist))
        self.q_chart.render(lambda f: tc.etl_quality(f, q), has_data=bool(q["flights"]))
        self.quality_text.setText(
            f"Flights stored: {q['flights']:,}  \u2022  duplicate flight keys: "
            f"{q['duplicate_flight_keys']}  \u2022  airports without coordinates: "
            f"{q['airports_without_coordinates']}  \u2022  rejected records archived: {q['rejected_records']}")
        self.reasons.set_frame(etl_monitor.rejection_reasons())
        self.rejected.set_frame(database.fetch_rejected().head(200))
        self.log.setPlainText("\n".join(etl_monitor.log_tail(150)))
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())
        self.mark_loaded()

    def _history(self) -> None:
        self._hist = etl_monitor.run_history(self.pipe_filter.currentData(), 500)
        self.history.set_frame(self._hist, ["id", "refreshed_at", "pipeline", "source", "data_origin", "status", "records_fetched",
                                            "records_valid", "records_rejected", "records_inserted", "records_updated", "duration_s", "message"])

    # ------------------------------------------------------------ operations
    def refresh_all(self) -> None:
        if self.main._refreshing:
            self.main.notify("Another data operation is already running.", "warning")
            return
        self.main._set_busy(True)
        self.op_msg.setText("Refreshing all configured sources\u2026")

        def work():
            """Each source runs independently: one failing source never blocks the others."""
            from src import service
            steps = []
            if config.api_key_configured():
                try:
                    steps.append(f"flights: {service.refresh_data(limit=config.DEFAULT_RECORD_LIMIT).message}")
                except utils.AppError as exc:
                    steps.append(f"flights: FAILED ({exc})")
            else:
                steps.append("flights: skipped (no AviationStack key)")
            return steps
        self.main.tasks.submit(work, on_done=self._refresh_done, on_error=self._refresh_failed, owner=self)

    def _refresh_done(self, steps) -> None:
        self.main._set_busy(False)
        self.main.store.invalidate()
        self.op_msg.setText(" | ".join(steps))
        self.main.notify("Refresh finished: " + "; ".join(steps), "success")
        self.main.refresh_status_bar()
        self.reload(force=True)

    def _refresh_failed(self, msg: str) -> None:
        self.main._set_busy(False)
        self.op_msg.setText(f"Refresh failed: {msg}")
        self.main.notify(f"Refresh failed: {msg}", "error")
        self.reload(force=True)

    def _replay(self) -> None:
        if self.main._refreshing:
            self.main.notify("Another data operation is already running.", "warning")
            return
        files = sorted(config.DATA_RAW_DIR.glob("flights_raw_*.json"))
        if not files:
            self.main.notify("There are no archived raw responses in data/raw/ to replay.", "warning")
            return
        self.main._set_busy(True)
        self.main.tasks.submit(lambda: [r.inserted for r in pipeline.replay_raw_files(files, save_artifacts=False)],
                               on_done=lambda res: (self.main._set_busy(False), self.main.store.invalidate(),
                                                    self.op_msg.setText(f"Replayed {len(files)} raw file(s); newly inserted rows per file: {res}."),
                                                    self.reload(force=True)),
                               on_error=self._refresh_failed, owner=self)

    def _export_data(self):
        df = self._hist
        meta = reports.metadata("ETL run history", {"pipeline": self.pipe_filter.currentData()}, "all recorded runs",
                                ["refresh_log table"], ["Runs before the pipeline column existed are shown as 'flights'."], len(df))
        return df, meta


# =========================================================================== Reports
class ReportsPage(PageBase):
    title = "Reports & Data Export"
    subtitle = "Export what is stored, with the filters and limitations stated in every file"
    DATASETS = ["Flights (stored snapshots)", "Airports (observed)", "Airlines", "Routes",
                "Saved searches", "Live status lookups", "ETL run history"]

    def __init__(self, main):
        super().__init__(main)
        card = Card()
        card.add_title("Export a dataset")
        self.dataset = QComboBox()
        self.dataset.addItems(self.DATASETS)
        self.dataset.currentIndexChanged.connect(self._preview)
        self.d_from = _combo([], "Any date")
        self.d_to = _combo([], "Any date")
        for c in (self.d_from, self.d_to):
            c.currentIndexChanged.connect(self._preview)
        card.body.addWidget(self._r(labelled("Dataset", self.dataset), labelled("Flights from", self.d_from), labelled("Flights to", self.d_to)))
        self.info = info_label("")
        card.body.addWidget(self.info)
        self.export = ExportBar(self._export_data, "export", figures=self._figs, metrics=self._metrics)
        card.body.addWidget(self.export)
        self.body.addWidget(card)
        self.preview = DataTable("Nothing to export for the current selection.")
        self.preview.setMinimumHeight(320)
        pc = Card()
        pc.add_title("Preview (the file contains exactly these rows)")
        pc.body.addWidget(self.preview)
        self.body.addWidget(pc)

        wb = Card()
        wb.add_title("Full analytics workbook", "One Excel file with a sheet per dataset plus a 'Report info' sheet (sources, limitations).")
        b = _primary_button("Export full workbook (Excel)", "download")
        b.clicked.connect(self._workbook)
        wb.body.addWidget(b, alignment=Qt.AlignmentFlag.AlignLeft)
        self.body.addWidget(wb)
        self.body.addStretch(1)
        self._df = pd.DataFrame()
        self._meta = {}

    @staticmethod
    def _r(*widgets):
        grid = ResponsiveGrid(min_item_width=170, max_columns=4)
        for w in widgets:
            grid.add(w)
        return grid

    def reload(self) -> None:
        fl = self.main.store.flights()
        dates = sorted(fl["flight_date"].astype(str).unique()) if not fl.empty else []
        _fill(self.d_from, dates, "Any date")
        _fill(self.d_to, dates, "Any date")
        self._preview()

    def _dataset(self, name: str, flights_filtered: bool = True):
        fl = self.main.store.flights()
        filters, sources, lim = {}, [], ["Snapshots are historical, not live.", "Missing values are left empty, never estimated."]
        if name.startswith("Flights"):
            df = fl
            if self.d_from.currentData():
                df = df[df["flight_date"].astype(str) >= self.d_from.currentData()]
                filters["flights from"] = self.d_from.currentData()
            if self.d_to.currentData():
                df = df[df["flight_date"].astype(str) <= self.d_to.currentData()]
                filters["flights to"] = self.d_to.currentData()
            sources = ["AviationStack /v1/flights snapshots (HISTORICAL)"]
        elif name.startswith("Airports"):
            df = self.main.store.memo("airport_traffic", lambda: ap.traffic_table(fl, reference.airport_reference()))
            sources = ["AviationStack snapshots for counts; OurAirports reference for names/coordinates"]
        elif name == "Airlines":
            df, sources = self.main.store.memo("airline_table", lambda: aa.table(fl)), ["AviationStack snapshots"]
            lim.append("Flight count is not a quality measure.")
        elif name == "Routes":
            from src import route_data
            df, sources = self.main.store.memo("route_table", lambda: route_data.route_table(fl, reference.airport_reference())), ["AviationStack snapshots; OurAirports coordinates"]
        elif name == "Saved searches":
            df, sources = database_travel.list_saved_searches(), ["local database"]
        elif name.startswith("Live status"):
            df, sources = database_travel.fetch_status_observations(), ["AviationStack live lookups (LIVE at retrieval time)"]
        else:
            df, sources = etl_monitor.run_history(limit=100000), ["refresh_log"]
        period = ""
        if "flight_date" in df and not df.empty:
            period = f"flight dates {df['flight_date'].min()} to {df['flight_date'].max()}"
        elif "retrieved_at" in df and not df.empty:
            period = f"retrieved {str(df['retrieved_at'].min())[:10]} to {str(df['retrieved_at'].max())[:10]}"
        return df, reports.metadata(name, filters, period or "n/a", sources, lim, len(df))

    def _preview(self) -> None:
        self._df, self._meta = self._dataset(self.dataset.currentText())
        self.preview.set_frame(self._df.head(500))
        self.info.setText(f"{len(self._df):,} rows selected" + (" (preview shows the first 500)." if len(self._df) > 500 else ".") +
                          f" Filters: {self._meta['filters']}.")

    def _export_data(self):
        return self._df, self._meta

    def _metrics(self) -> dict:
        return {"rows": len(self._df), "dataset": self._meta.get("title")}

    def _figs(self):
        from matplotlib.figure import Figure
        figs = []
        fl = self.main.store.flights()
        if not fl.empty:
            for fn in (lambda f: tc.airport_traffic(f, ap.traffic_table(fl, reference.airport_reference())),
                       lambda f: tc.delay_by_group(f, da.by_airline(fl), "airline_name", "Mean delay by airline")):
                fig = Figure(figsize=(8.27, 5), layout="constrained")
                fn(fig)
                figs.append(fig)
        return figs

    def _workbook(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "Export workbook", str(reports.default_path("skylens_workbook", "xlsx")), "Excel workbook (*.xlsx)")
        if not path:
            return
        try:
            sheets, srcs = {}, set()
            for name in self.DATASETS:
                df, meta = self._dataset(name)
                if not df.empty:
                    sheets[name.split(" (")[0]] = df
                    srcs.update(meta["sources"])
            meta = reports.metadata("SkyLens full workbook", {}, "see each sheet", sorted(srcs),
                                    ["Flight data are historical snapshots, not live status.",
                                     "Sheets contain the complete stored data (no UI filters except the flight dates selected)."],
                                    sum(len(d) for d in sheets.values()))
            reports.export_excel(sheets, path, meta)
        except Exception as exc:
            self.main.notify(f"Workbook export failed: {exc}", "error")
            return
        self.main.notify(f"Workbook with {len(sheets)} sheet(s) saved to {path}", "success")


# =========================================================================== Destination weather
class DestinationWeatherPage(WeatherInsightsPage):
    title = "Destination Weather"
    subtitle = "Forecast or historical weather for a destination and date - plus conditions for your location"

    def __init__(self, main):
        super().__init__(main)
        card = Card()
        card.add_title("Weather at a destination", "Open-Meteo. Pick an airport and a date; the page says whether it shows a forecast, current "
                                                   "conditions or historical weather.")
        self.dest = AirportEdit("Destination airport or city")
        self.when = date_edit(7, minimum_today=False)
        self.when.setMinimumDate(QDate.currentDate().addYears(-30))
        self.go = _primary_button("Get weather", "weather")
        self.go.clicked.connect(self._get)
        use = _plain_button("Use my last searched destination")
        use.clicked.connect(self._use_last)
        r = ResponsiveGrid(min_item_width=190, max_columns=4)
        r.add(labelled("Destination", self.dest))
        r.add(labelled("Date", self.when))
        btns = FlowRow()
        btns.addWidget(self.go)
        btns.addWidget(use)
        r.add(btns)
        card.body.addWidget(r)
        self.kind_badge = OriginBadge("historical")
        self.kind_badge.hide()
        card.body.addWidget(self.kind_badge, alignment=Qt.AlignmentFlag.AlignLeft)
        self.msg = info_label("")
        card.body.addWidget(self.msg)
        grid, cards = _kpis([("Conditions", P.COBALT), ("Temperature", P.TEAL), ("Precipitation", "#C48A1B"), ("Wind (max)", P.NAVY_SOFT)], 170)
        self.k_cond, self.k_temp, self.k_pr, self.k_wind = cards
        card.body.addWidget(grid)
        self.chart = FigureCard("Temperature range", 180)
        self.chart.setMaximumHeight(300)
        card.body.addWidget(self.chart)
        self.attr = info_label("")
        card.body.addWidget(self.attr)
        self.body.insertWidget(0, card)
        self._token = 0

    def _use_last(self) -> None:
        q = self.main.shared.get("query")
        if q is not None:
            self.dest.set_iata(q.destination)
            self.when.setDate(QDate(q.departure_date.year, q.departure_date.month, q.departure_date.day))
        else:
            self.main.notify("No destination has been searched yet.", "info")

    def _get(self) -> None:
        code = self.dest.iata()
        info = reference.lookup(code) if code else None
        if not info:
            self.msg.setText("Choose a destination airport from the list (a valid IATA code is required).")
            return
        target = self.when.date().toPython()
        label = f"{info['name']} ({code}), {info['city'] or ''} {info['country'] or ''}".strip()
        self.go.setEnabled(False)
        self.msg.setText("Fetching weather\u2026")
        self._token += 1
        tok = self._token
        self.main.tasks.submit(wx.get_weather, latitude=info["latitude"], longitude=info["longitude"], target=target, label=label,
                               on_done=lambda r: self._show(tok, r), on_error=lambda m: self._fail(tok, m), owner=self)

    def _fail(self, tok: int, msg: str) -> None:
        if tok != self._token:
            return
        self.go.setEnabled(True)
        self.kind_badge.hide()
        self.msg.setText(f"Weather unavailable: {msg}")

    def _show(self, tok: int, r: wx.WeatherResult) -> None:
        if tok != self._token:
            return
        self.go.setEnabled(True)
        kinds = {"forecast": ("FORECAST", "cached_api"), "current": ("CURRENT + TODAY", "live_api"), "recent": ("RECENT PAST (model)", "historical"),
                 "historical": ("HISTORICAL (what it was)", "historical"), "unavailable": ("UNAVAILABLE", "sample")}
        text, style = kinds[r.kind]
        self.kind_badge.set_origin(style, text)
        self.kind_badge.show()
        self.msg.setText(f"{r.label} \u2022 {r.target_date:%A %d %B %Y}. " + " ".join(r.notes))
        d = r.daily
        if not r.available or not d:
            for k in (self.k_cond, self.k_temp, self.k_pr, self.k_wind):
                k.set_value("\u2013", "no data")
            self.chart.empty("No weather data for this date.")
            self.attr.setText(r.attribution)
            return
        self.k_cond.set_value(wx.describe_code(d.get("weather_code")), "daily summary")
        tmax, tmin = d.get("temperature_2m_max"), d.get("temperature_2m_min")
        self.k_temp.set_value(f"{tmin:.0f}\u2013{tmax:.0f} \u00b0C" if tmax is not None and tmin is not None else "\u2013", "min \u2013 max")
        prob, tot = d.get("precipitation_probability_max"), d.get("precipitation_sum")
        self.k_pr.set_value(f"{prob:.0f}%" if prob is not None else (f"{tot:.1f} mm" if tot is not None else "\u2013"),
                            ("probability" + (f", {tot:.1f} mm expected" if tot is not None else "")) if prob is not None else "total precipitation")
        w = d.get("wind_speed_10m_max")
        self.k_wind.set_value(f"{w:.0f} km/h" if w is not None else "\u2013", "10 m height")
        self.chart.render(lambda f: tc.weather_daily(f, d, r.label.split(",")[0]))
        cur = f" Right now: {r.current.get('temperature_2m')} \u00b0C." if r.current and r.current.get("temperature_2m") is not None else ""
        self.attr.setText(r.attribution + ". Weather forecasts do not guarantee flight operations." + cur)
