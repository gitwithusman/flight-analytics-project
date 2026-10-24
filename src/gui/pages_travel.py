"""Flight Search page: route / date / passengers / cabin search, filters, details, saved searches."""

from __future__ import annotations

from typing import Optional

import pandas as pd
from PySide6.QtCore import QDate, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QLineEdit, QSpinBox,
    QVBoxLayout, QWidget,
)

from src import config, database_travel, flight_search, options_view as ov, reports
from src.providers.base import DATA_ORIGIN_LABELS, FlightQuery, FlightQueryError, validate_query

from .components import AirportEdit, ExportBar, OriginBadge, date_edit, info_label, notice_box
from .pages import _plain_button, _primary_button
from .tables import DataTable
from .theme import SP_MD
from .widgets import Card, FlowRow, PageBase, ResponsiveGrid, labelled

CABINS = [("Economy", "economy"), ("Premium economy", "premium_economy"), ("Business", "business"), ("First", "first")]
BOOKING_PREFIX = "https://www.aviasales.com"


# =========================================================================== Flight Search
class FlightSearchPage(PageBase):
    volatile = True
    title = "Flight Search"
    subtitle = "Find flights for a route and date - every result is labelled with its data source"
    accent = "search"

    def __init__(self, main):
        super().__init__(main)
        self._query: Optional[FlightQuery] = None
        self._options = pd.DataFrame()    # transformed flight options from the last search
        self._shown = pd.DataFrame()      # after filters / sorting (same order as the table)
        self._names = {}
        self._searching = False

        # ---- source notice (updated on every visit: settings can change it)
        self.source_row = QVBoxLayout()
        self.body.addLayout(self.source_row)

        # ---- search form
        form = Card()
        form.add_title("Search", "Type an airport code, city or name and pick from the list.")
        self.origin = AirportEdit("From (e.g. LHE)")
        self.dest = AirportEdit("To (e.g. DXB)")
        swap = _plain_button("\u21c4")
        swap.setToolTip("Swap origin and destination")
        swap.setFixedWidth(44)
        swap.clicked.connect(self._swap)
        self.dep_date = date_edit(14)
        self.round_trip = QCheckBox("Return trip")
        self.ret_date = date_edit(21)
        self.ret_date.setEnabled(False)
        self.round_trip.toggled.connect(self.ret_date.setEnabled)
        self.pax = QSpinBox()
        self.pax.setRange(1, 9)
        self.cabin = QComboBox()
        for label, value in CABINS:
            self.cabin.addItem(label, value)
        self.cabin.setToolTip("Applied only when the data source supports cabin classes.")
        self.direct = QCheckBox("Direct flights only")
        fields = ResponsiveGrid(min_item_width=190, max_columns=4)
        od = QWidget()
        odl = QHBoxLayout(od)
        odl.setContentsMargins(0, 0, 0, 0)
        odl.setSpacing(SP_MD)
        odl.addWidget(labelled("From", self.origin), 1)
        odl.addWidget(swap, 0, Qt.AlignmentFlag.AlignBottom)
        fields.add(od)
        fields.add(labelled("To", self.dest))
        fields.add(labelled("Departure date", self.dep_date))
        fields.add(labelled("Return date (optional)", self.ret_date))
        fields.add(labelled("Passengers", self.pax))
        fields.add(labelled("Cabin class", self.cabin, "Not offered by every source"))
        opts = QWidget()
        ol = QVBoxLayout(opts)
        ol.setContentsMargins(0, 18, 0, 0)
        ol.addWidget(self.round_trip)
        ol.addWidget(self.direct)
        fields.add(opts)
        form.body.addWidget(fields)
        self.form_msg = QLabel("")
        self.form_msg.setWordWrap(True)
        self.form_msg.setStyleSheet("color: #B42318;")
        self.form_msg.hide()
        form.body.addWidget(self.form_msg)
        buttons = FlowRow()
        self.search_btn = _primary_button("Search flights", "explorer")
        self.search_btn.clicked.connect(self.search)
        self.repeat_btn = _plain_button("Repeat last search", "refresh")
        self.repeat_btn.setEnabled(False)
        self.repeat_btn.clicked.connect(self.repeat_search)
        self.save_btn = _plain_button("Save this search")
        self.save_btn.setToolTip("Keep this route, dates and options in the Saved searches list below")
        self.save_btn.clicked.connect(self._save_search)
        buttons.addWidget(self.search_btn)
        buttons.addWidget(self.repeat_btn)
        buttons.addWidget(self.save_btn)
        buttons.addStretch(1)
        form.body.addWidget(buttons)
        self.body.addWidget(form)

        # ---- results header + filters
        self.results_card = Card()
        head = QHBoxLayout()
        self.origin_badge = OriginBadge("historical")
        self.origin_badge.hide()
        self.result_title = QLabel("Results")
        self.result_title.setObjectName("cardTitle")
        head.addWidget(self.result_title)
        head.addWidget(self.origin_badge)
        head.addStretch(1)
        self.results_card.body.addLayout(head)
        self.result_note = info_label("Run a search to see flights.")
        self.results_card.body.addWidget(self.result_note)

        flt = ResponsiveGrid(min_item_width=150, max_columns=5)
        self.f_airline = QComboBox()
        self.f_stops = QComboBox()
        for label, v in (("Any number", None), ("Direct only", 0), ("Up to 1 stop", 1), ("Up to 2 stops", 2)):
            self.f_stops.addItem(label, v)
        self.f_time = QComboBox()
        self.f_time.addItems(list(ov.TIME_BUCKETS))
        self.f_dur = QDoubleSpinBox()
        self.f_dur.setRange(0, 72)
        self.f_dur.setSpecialValueText("No limit")
        self.f_dur.setSuffix(" h")
        self.f_dur.setDecimals(0)
        self.f_sort = QComboBox()
        self.f_sort.addItems(list(ov.SORTS))
        for cap, wdg in (("Airline", self.f_airline), ("Stops", self.f_stops), ("Departure time", self.f_time),
                         ("Max duration", self.f_dur), ("Sort by", self.f_sort)):
            flt.add(labelled(cap, wdg))
        self.results_card.body.addWidget(flt)
        for w_ in (self.f_airline, self.f_stops, self.f_time, self.f_sort):
            w_.currentIndexChanged.connect(self._apply)
        self.f_dur.valueChanged.connect(self._apply)

        self.table = DataTable("Search for a route to see flights here.")
        self.table.setMinimumHeight(280)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setSortingEnabled(True)
        self.results_card.body.addWidget(self.table)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._show_detail())
        self.footnote = info_label("")
        self.results_card.body.addWidget(self.footnote)
        actions = FlowRow()
        self.export = ExportBar(self._export_data, "flight_search_results", pdf=False)
        actions.addWidget(self.export)
        actions.addStretch(1)
        self.results_card.body.addWidget(actions)
        self.body.addWidget(self.results_card)

        # ---- flight detail
        self.detail_card = Card()
        self.detail_card.add_title("Flight details", "Select a row above to inspect the flight.")
        self.detail_text = QLabel("No flight selected.")
        self.detail_text.setObjectName("muted")
        self.detail_text.setWordWrap(True)
        self.detail_text.setTextFormat(Qt.TextFormat.RichText)
        self.detail_card.body.addWidget(self.detail_text)
        self.book_btn = _plain_button("Open provider's website")
        self.book_btn.setEnabled(False)
        self.book_btn.clicked.connect(self._open_booking)
        self.detail_card.body.addWidget(self.book_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        self.body.addWidget(self.detail_card)

        # ---- saved searches
        saved = Card()
        saved.add_title("Saved searches", "Keep the routes you look up often. 'Run selected' loads one into the form and searches again.")
        self.saved_name = QLineEdit()
        self.saved_name.setPlaceholderText("Optional name for the next saved search")
        self.saved_name.setMaximumWidth(360)
        saved.body.addWidget(labelled("Name", self.saved_name))
        self.saved_table = DataTable("No saved searches yet. Run a search and choose 'Save this search'.")
        self.saved_table.setMinimumHeight(150)
        saved.body.addWidget(self.saved_table)
        srow = FlowRow()
        self.run_saved_btn = _primary_button("Run selected")
        self.run_saved_btn.clicked.connect(self._run_saved)
        self.del_saved_btn = _plain_button("Delete selected")
        self.del_saved_btn.clicked.connect(self._delete_saved)
        srow.addWidget(self.run_saved_btn)
        srow.addWidget(self.del_saved_btn)
        srow.addStretch(1)
        saved.body.addWidget(srow)
        self.body.addWidget(saved)
        self.body.addStretch(1)

    # ---------------------------------------------------------------- source notice
    def _refresh_source_notice(self) -> None:
        while self.source_row.count():
            it = self.source_row.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        if config.search_mode() == "sample":
            self.source_row.addWidget(notice_box(
                "SAMPLE DATA MODE - no FlightAPI key is configured. Searches return generated demonstration flights "
                "(fictional carriers), NOT real flights. Add your FlightAPI key in Settings to retrieve real "
                "flight options.", "warning"))
        else:
            self.source_row.addWidget(notice_box(
                "Flight options come from FlightAPI.io. Schedules and availability can change - confirm them with "
                "the airline or booking agent before you travel.", "info"))

    def reload(self) -> None:
        self._refresh_source_notice()
        self._names = ov.airline_names()
        self._reload_saved()

    # ---------------------------------------------------------------- search
    def _swap(self) -> None:
        a, b = self.origin.text(), self.dest.text()
        self.origin.setText(b)
        self.dest.setText(a)

    def _build_query(self) -> Optional[FlightQuery]:
        self.form_msg.hide()
        self.origin.mark_invalid(False)
        self.dest.mark_invalid(False)
        for label, edit in (("Origin", self.origin), ("Destination", self.dest)):
            if edit.text().strip() and not edit.iata():
                edit.mark_invalid(True)
                self.form_msg.setText(f"{label}: '{edit.text().strip()}' is not recognised - pick an airport from the "
                                      "suggestions or type its 3-letter IATA code (e.g. LHE).")
                self.form_msg.show()
                return None
        try:
            q = FlightQuery(self.origin.iata(), self.dest.iata(), self.dep_date.date().toPython(),
                            self.ret_date.date().toPython() if self.round_trip.isChecked() else None,
                            self.pax.value(), self.cabin.currentData(), self.direct.isChecked())
            return validate_query(q, known_iata=AirportEdit.known_codes())
        except FlightQueryError as exc:
            text = str(exc)
            self.form_msg.setText(text)
            self.form_msg.show()
            self.origin.mark_invalid(text.startswith("Origin"))
            self.dest.mark_invalid(text.startswith("Destination"))
            return None

    def search(self) -> None:
        if self._searching:
            return
        q = self._build_query()
        if q is None:
            return
        if self.main._refreshing:
            self.main.notify("Another data operation is running - please wait for it to finish.", "warning")
            return
        self._query = q
        self._set_searching(True)
        self.main.tasks.submit(flight_search.run_flight_search, query=q, on_done=self._done, on_error=self._failed,
                               owner=self)

    def repeat_search(self) -> None:
        if self._query is not None and not self._searching:
            self.search()

    def _set_searching(self, on: bool) -> None:
        self._searching = on
        self.search_btn.setEnabled(not on)
        self.repeat_btn.setEnabled(not on and self._query is not None)
        self.search_btn.setText("Searching\u2026" if on else "Search flights")
        self.main.busy_bar.setVisible(on)
        self.main.status_bar.set_message("Searching flights\u2026" if on else "Ready")

    def _failed(self, message: str) -> None:
        self._set_searching(False)
        self.form_msg.setText(message)
        self.form_msg.show()
        self.main.notify(message, "error")

    def _done(self, rep: flight_search.SearchRunReport) -> None:
        self._set_searching(False)
        self._options = rep.options if rep.options is not None else pd.DataFrame()
        self.main.shared["options"] = self._options
        self.main.shared["query"] = self._query
        self.origin_badge.set_origin(rep.data_origin)
        self.origin_badge.show()
        q = self._query
        self.result_title.setText(f"{q.origin} \u2192 {q.destination} \u2022 {q.departure_date:%d %b %Y}")
        parts = [f"{rep.extracted} flight(s) retrieved; {rep.accepted} accepted, {rep.rejected} rejected by validation."]
        parts += rep.notes
        self.result_note.setText(" ".join(parts) + " Schedules and availability can change between searches.")
        airlines = sorted(self._options["airline_iata"].dropna().unique()) if not self._options.empty else []
        self.f_airline.blockSignals(True)
        self.f_airline.clear()
        self.f_airline.addItem("All airlines", None)
        for a in airlines:
            self.f_airline.addItem(self._names.get(a, a), a)
        self.f_airline.blockSignals(False)
        self._apply()
        if rep.rejected:
            self.main.notify(f"{rep.rejected} flight(s) were rejected by validation (see ETL Monitoring).", "warning")
        self.main.store.bump_runs()          # the search was logged: ETL Monitoring has a new run to show
        self.main.refresh_status_bar()

    # ---------------------------------------------------------------- filters & table
    def _filtered(self) -> pd.DataFrame:
        if self._options.empty:
            return self._options
        out = ov.apply_filters(self._options, self.f_airline.currentData(), self.f_stops.currentData(),
                               self.f_time.currentText(), self.f_dur.value() or None)
        return ov.sort_options(out, self.f_sort.currentText())

    def _apply(self) -> None:
        self._shown = self._filtered()
        disp = ov.display_frame(self._shown, self._names)
        self.table.set_frame(disp.reset_index(drop=True))
        if self._options.empty and self._query is not None:
            self.table.set_empty_text(
                f"No flights found for {self._query.origin} \u2192 {self._query.destination} on {self._query.departure_date}. "
                "Try nearby dates or a busier route.")
        elif self._shown.empty and not self._options.empty:
            self.table.set_empty_text("No flights match the current filters - relax a filter to see results.")
        n = len(self._shown)
        self.footnote.setText("" if self._options.empty else
                              f"Showing {n} of {len(self._options)} flights. "
                              "* = arrival time derived from departure + duration (not supplied by the source).")
        self._show_detail()

    def _selected_options(self) -> pd.DataFrame:
        rows = self.table.selected_rows()
        return self._shown.iloc[rows] if rows and not self._shown.empty else self._shown.iloc[0:0]

    def _show_detail(self) -> None:
        sel = self._selected_options()
        self.book_btn.setEnabled(False)
        self.book_btn.setProperty("url", None)
        if sel.empty:
            self.detail_text.setText("No flight selected.")
            return
        r = sel.iloc[0]
        names = self._names
        dur = ov.fmt_duration(r["duration_min"])
        arr = r["arrival_at"] if isinstance(r["arrival_at"], str) else "not provided"
        lines = [
            f"<b>{names.get(r['airline_iata'], r['airline_iata'] or 'Airline not provided')}</b> &nbsp; {r['flight_number'] or 'flight number not provided'}",
            f"{r['origin_iata']} \u2192 {r['destination_iata']} &nbsp;|&nbsp; departs {str(r['departure_at'])[:16].replace('T', ' ')} UTC"
            f" &nbsp;|&nbsp; arrives {str(arr)[:16].replace('T', ' ')}{' UTC (derived)' if r['arrival_derived'] else ' UTC' if arr != 'not provided' else ''}",
            f"Duration: {dur} &nbsp;|&nbsp; {ov.fmt_stops(r['stops'])} &nbsp;|&nbsp; Cabin: {r['cabin'] or 'not provided by this source'}",
            f"Baggage: {r['baggage'] if isinstance(r['baggage'], str) and r['baggage'] else 'not provided by this source'}",
            f"Data: {DATA_ORIGIN_LABELS.get(r['data_origin'], r['data_origin'])} &nbsp;|&nbsp; provider: {r['source']} "
            f"&nbsp;|&nbsp; retrieved {str(r['retrieved_at'])[:16].replace('T', ' ')} UTC",
        ]
        if r["data_origin"] == "sample":
            lines.append("<b>SAMPLE DATA - not a real flight.</b>")
        else:
            lines.append("Confirm schedule and availability on the provider's website.")
        self.detail_text.setText("<br>".join(lines))
        url = r["booking_url"]
        if isinstance(url, str) and url.startswith(BOOKING_PREFIX):
            self.book_btn.setEnabled(True)
            self.book_btn.setProperty("url", url)
            self.book_btn.setToolTip(url)
        else:
            self.book_btn.setToolTip("No verified booking link was returned for this flight.")

    def _open_booking(self) -> None:
        url = self.book_btn.property("url")
        if url and url.startswith(BOOKING_PREFIX):
            QDesktopServices.openUrl(QUrl(url))

    # ---------------------------------------------------------------- saved searches
    def _save_search(self) -> None:
        q = self._query or self._build_query()
        if q is None:
            return
        name = self.saved_name.text().strip() or f"{q.origin}-{q.destination} {q.departure_date}"
        try:
            database_travel.save_search(name, q.origin, q.destination, q.departure_date.isoformat(),
                                        q.return_date.isoformat() if q.return_date else None, q.adults, q.cabin)
        except Exception as exc:
            self.main.notify(f"Could not save the search: {exc}", "error")
            return
        self.saved_name.clear()
        self._reload_saved()
        self.main.notify("Search saved.", "success")

    def _reload_saved(self) -> None:
        s = database_travel.list_saved_searches().rename(columns={"name": "search_name"})
        cols = [c for c in ("id", "search_name", "origin_iata", "destination_iata", "departure_date", "return_date",
                            "adults", "cabin", "created_at") if c in s.columns]
        self.saved_table.set_frame(s, cols)

    def _selected_saved(self):
        rows = self.saved_table.selected_rows()
        if not rows:
            self.main.notify("Select a saved search first.", "info")
            return None
        return self.saved_table.table_model.frame().iloc[rows[0]]

    def _run_saved(self) -> None:
        r = self._selected_saved()
        if r is None:
            return
        self.origin.set_iata(str(r["origin_iata"]))
        self.dest.set_iata(str(r["destination_iata"]))
        dep = QDate.fromString(str(r["departure_date"]), "yyyy-MM-dd")
        if not dep.isValid() or dep < QDate.currentDate():
            dep = QDate.currentDate().addDays(14)
            self.main.notify("The saved departure date has passed - a new date was suggested; check it and search.", "info")
        self.dep_date.setDate(dep)
        ret = QDate.fromString(str(r["return_date"] or ""), "yyyy-MM-dd")
        self.round_trip.setChecked(bool(ret.isValid() and ret >= dep))
        if ret.isValid() and ret >= dep:
            self.ret_date.setDate(ret)
        self.pax.setValue(int(r["adults"]))
        idx = self.cabin.findData(r["cabin"])
        self.cabin.setCurrentIndex(max(idx, 0))
        self.search()

    def _delete_saved(self) -> None:
        rows = self.saved_table.selected_rows()
        if not rows:
            self.main.notify("Select a saved search first.", "info")
            return
        frame = self.saved_table.table_model.frame()
        for r in rows:
            database_travel.delete_saved_search(int(frame.iloc[r]["id"]))
        self._reload_saved()

    # ---------------------------------------------------------------- export
    def _export_data(self):
        df = self._shown.drop(columns=[c for c in ("dep_dt", "arr_dt", "dep_hour") if c in self._shown], errors="ignore")
        q = self._query
        meta = reports.metadata("Flight search results", {
            "route": f"{q.origin}-{q.destination}" if q else None, "departure": str(q.departure_date) if q else None,
            "airline": self.f_airline.currentText() if self.f_airline.currentData() else None,
            "sort": self.f_sort.currentText()},
            f"retrieved {df['retrieved_at'].max() if not df.empty else '-'}",
            [f"{df['source'].iloc[0]} ({DATA_ORIGIN_LABELS.get(df['data_origin'].iloc[0])})"] if not df.empty else [],
            ["Schedules and availability can change between searches.",
             "Fields a source does not provide (baggage, cabin) are left empty, never invented."]
            + (["SAMPLE DATA - not real flights."] if not df.empty and (df["data_origin"] == "sample").any() else []), len(df))
        return df, meta
