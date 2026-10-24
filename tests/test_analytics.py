"""Tests for analytics (src/analytics.py) and chart builders."""

import pandas as pd
import pytest

from src import analytics, visualizations


def test_dataset_overview(flights_df):
    ov = analytics.dataset_overview(flights_df)
    assert ov["rows"] == 3
    assert ov["duplicate_rows"] == 0


def test_status_distribution(flights_df):
    dist = analytics.status_distribution(flights_df)
    counts = dict(zip(dist["flight_status"], dist["flights"]))
    assert counts == {"active": 1, "cancelled": 1, "landed": 1}
    assert dist["share_pct"].sum() == pytest.approx(100.0, abs=0.2)


def test_top_airlines(flights_df):
    top = analytics.top_airlines(flights_df)
    assert top.iloc[0]["airline"] == "Example Air"
    assert top.iloc[0]["flights"] == 2


def test_top_airports(flights_df):
    dep = analytics.top_airports(flights_df, "dep")
    assert dep.iloc[0]["iata"] == "JFK"
    arr = analytics.top_airports(flights_df, "arr")
    assert arr.iloc[0]["iata"] == "LAX"


def test_top_routes(flights_df):
    routes = analytics.top_routes(flights_df)
    assert set(routes["route"]) == {"JFK-LAX", "ORD-LAX", "JFK-MIA"}


def test_delay_statistics(flights_df):
    stats = analytics.delay_statistics(flights_df)
    assert stats["available"]
    assert stats["delayed_flights"] == 2
    assert stats["max_delay_min"] == 45


def test_delay_statistics_empty():
    stats = analytics.delay_statistics(pd.DataFrame())
    assert not stats["available"]
    assert "reason" in stats


def test_departure_hours(flights_df):
    hours = analytics.departure_hour_distribution(flights_df)
    assert not hours.empty
    assert set(hours["hour"]) <= set(range(24))


def test_unique_counts(flights_df):
    counts = analytics.unique_value_counts(flights_df)
    assert counts["airlines"] == 2
    assert counts["routes"] == 3


def test_classify_condition(flights_df):
    rows = flights_df.set_index("flight_iata")
    active = rows.loc["EA100"]
    assert analytics.classify_condition(active)["label"].startswith("Delayed")
    cancelled = rows.loc["MC220"]
    assert analytics.classify_condition(cancelled)["label"] == "Cancelled"
    landed = rows.loc["EA777"]
    assert analytics.classify_condition(landed)["label"].startswith("Delayed")


def test_classify_unknown():
    cond = analytics.classify_condition({"flight_status": "", "max_delay_min": None})
    assert cond["label"] == "Status Unknown"


def test_charts_build(flights_df, monkeypatch, tmp_path):
    """Every registered chart builds and saves a PNG from real data."""
    monkeypatch.setattr(visualizations.config, "VISUALIZATIONS_DIR", tmp_path)
    for key in visualizations.CHART_TYPES:
        fig = visualizations.build_chart(key, flights_df)
        assert fig is not None
        path = visualizations.save_chart(key, flights_df)
        assert path.exists() and path.suffix == ".png"


def test_charts_on_empty_frame_do_not_crash():
    empty = pd.DataFrame()
    for key in visualizations.CHART_TYPES:
        fig = visualizations.build_chart(key, empty)
        assert fig is not None  # explanatory figure, not a crash
