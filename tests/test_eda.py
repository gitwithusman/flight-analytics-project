"""EDA functions on a database produced by the real pipeline code."""

import json

import numpy as np
import pandas as pd
import pytest

from src import config, eda, pipeline


@pytest.fixture()
def loaded_db(tmp_path, tmp_db, sample_raw_records):
    path = tmp_path / "flights_raw_20261009_101516.json"
    path.write_text(json.dumps({"data": sample_raw_records}), encoding="utf-8")
    pipeline.run_pipeline(raw_file=path, db_path=tmp_db, save_artifacts=False)
    return tmp_db


def test_eda_reads_from_the_database(loaded_db):
    df = eda.load_dataset(loaded_db)
    assert len(df) == 3 and "dep_hour_local" in df
    prof = eda.dataset_profile(df)
    assert prof["rows"] == 3 and prof["capture_dates"] == 1
    assert {"column", "dtype", "non_null"} <= set(prof["dtype_table"].columns)


def test_quality_checks(loaded_db):
    df = eda.load_dataset(loaded_db)
    assert eda.duplicate_checks(df)["natural_key_duplicates"] == 0
    miss = eda.missing_values_table(df)
    assert miss["missing"].is_monotonic_decreasing
    cov = eda.delay_coverage(df)
    assert cov["delay_reported"] == 2 and cov["delayed"] == 2


def test_iqr_outliers_detect_planted_value():
    df = pd.DataFrame({"x": [10, 11, 12, 11, 10, 12, 11, 300.0]})
    out = eda.iqr_outliers(df, "x")
    assert out["outliers"] == 1 and out["rows"]["x"].iloc[0] == 300


def test_iqr_positive_only_ignores_zeros():
    df = pd.DataFrame({"d": [0] * 50 + [5, 6, 7, 8, 90]})
    assert eda.iqr_outliers(df, "d")["outliers"] == 5          # degenerate: IQR = 0
    assert eda.iqr_outliers(df, "d", positive_only=True)["outliers"] == 1


def test_two_proportion_ztest_known_value():
    out = eda.two_proportion_ztest(40, 100, 20, 100)
    # pooled p = 0.3, se = sqrt(0.3*0.7*(1/100+1/100)) = 0.06481 -> z = 0.2/0.06481
    assert out["z"] == pytest.approx(3.086, abs=1e-3)
    assert out["p_value"] == pytest.approx(0.0020, abs=1e-4)
    assert eda.two_proportion_ztest(0, 0, 1, 2)["p_value"] is None


def test_findings_are_generated_from_data(loaded_db):
    text = " ".join(eda.key_findings(eda.load_dataset(loaded_db)))
    assert "3 validated flights" in text
    assert eda.key_findings(pd.DataFrame())[0].startswith("The database is empty")


def test_run_eda_writes_figures_and_summary(loaded_db, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EDA_DIR", tmp_path / "eda")
    monkeypatch.setattr(config, "EDA_FIGURES_DIR", tmp_path / "figs")
    (tmp_path / "eda").mkdir()
    summary = eda.run_eda(loaded_db)
    assert len(summary["figures"]) >= 10
    assert all((tmp_path / "figs" / name).exists() for name in summary["figures"])
    saved = json.loads((tmp_path / "eda" / "eda_summary.json").read_text())
    assert saved["profile"]["rows"] == 3 and (tmp_path / "eda" / "EDA_Findings.md").exists()


def test_run_eda_on_empty_database_is_a_clear_error(tmp_db):
    with pytest.raises(ValueError, match="no flights"):
        eda.run_eda(tmp_db, save=False, charts=False)
