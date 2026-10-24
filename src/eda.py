"""Structured exploratory data analysis (EDA) over the SQLite database.

The EDA always starts from the **stored** data (``database.fetch_flights``),
never from an in-memory copy of an API response, so what is analysed is exactly
what the ETL pipeline validated and loaded.

Structure (mirrored by ``notebooks/ETL_EDA_Analysis.ipynb`` and the report):

1. Dataset overview        - dimensions, dtypes, date coverage
2. Data quality            - missing values, duplicates, constant columns
3. Descriptive statistics  - numeric summary (with skew), categorical summary
4. Distributions           - status, airlines, airports, routes, durations, delays
5. Trends                  - flights and delays by capture date / departure hour
6. Relationships           - correlation matrix, codeshare vs delay
7. Comparisons             - delay behaviour by airline / departure airport
8. Outliers                - IQR rule on duration, delay and speed
9. Findings                - sentences generated from the numbers above

Every statement of fact in :func:`key_findings` is computed from the data, so
the written findings cannot drift away from the results.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from . import config, database
from .utils import get_logger, save_json

logger = get_logger()

NUMERIC_ANALYSIS_COLUMNS = [
    "dep_delay_min", "arr_delay_min", "max_delay_min",
    "scheduled_duration_min", "live_speed_kmh", "live_altitude",
]
TIME_COLUMNS = ["dep_scheduled", "dep_estimated", "dep_actual",
                "arr_scheduled", "arr_estimated", "arr_actual"]


# ---------------------------------------------------------------------------
# 0. Loading
# ---------------------------------------------------------------------------


def load_dataset(db_path=None) -> pd.DataFrame:
    """Read every flight from SQLite and restore proper dtypes."""
    df = database.fetch_flights(limit=10_000_000, db_path=db_path)
    if df.empty:
        return df
    for col in TIME_COLUMNS:
        if col in df:
            df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)
    for col in ("is_codeshared", "is_delayed"):
        if col in df:
            df[col] = df[col].astype(bool)
    df["flight_date"] = pd.to_datetime(df["flight_date"], errors="coerce")
    df["dep_hour_local"] = pd.to_numeric(df["dep_local_hour"], errors="coerce")
    return df


# ---------------------------------------------------------------------------
# 1. Overview
# ---------------------------------------------------------------------------


def dataset_profile(df: pd.DataFrame) -> Dict:
    """Dimensions, memory, date coverage and a dtype table."""
    if df.empty:
        return {"rows": 0, "columns": 0}
    dtypes = pd.DataFrame({
        "column": df.columns,
        "dtype": [str(t) for t in df.dtypes],
        "non_null": df.notna().sum().values,
        "missing_pct": (df.isna().mean() * 100).round(1).values,
        "unique": [int(df[c].nunique(dropna=True)) for c in df.columns],
    })
    dates = df["flight_date"].dropna()
    return {
        "rows": int(len(df)),
        "columns": int(df.shape[1]),
        "memory_kb": round(df.memory_usage(deep=True).sum() / 1024, 1),
        "date_min": str(dates.min().date()) if len(dates) else None,
        "date_max": str(dates.max().date()) if len(dates) else None,
        "capture_dates": int(dates.nunique()),
        "dtype_table": dtypes,
        "dtype_counts": {k: int(v) for k, v in
                         df.dtypes.astype(str).value_counts().items()},
    }


# ---------------------------------------------------------------------------
# 2. Data quality
# ---------------------------------------------------------------------------


def missing_values_table(df: pd.DataFrame) -> pd.DataFrame:
    """Columns with at least one missing value, worst first."""
    miss = df.isna().sum()
    table = pd.DataFrame({"missing": miss, "missing_pct": (miss / max(len(df), 1) * 100).round(1)})
    return (table[table["missing"] > 0]
            .sort_values("missing", ascending=False)
            .rename_axis("column").reset_index())


def duplicate_checks(df: pd.DataFrame) -> Dict:
    """Exact-row and natural-key duplicates (both should be zero after ETL)."""
    key = ["flight_date", "flight_iata", "dep_iata", "arr_iata"]
    content = df.drop(columns=["id", "first_seen_at", "updated_at"], errors="ignore")
    return {
        "exact_duplicate_rows": int(content.astype(str).duplicated().sum()),
        "natural_key_duplicates": int(df.duplicated(subset=key).sum()),
        "unique_flight_codes": int(df["flight_iata"].nunique()),
    }


def constant_columns(df: pd.DataFrame) -> List[str]:
    return [c for c in df.columns if df[c].nunique(dropna=False) <= 1]


def delay_coverage(df: pd.DataFrame) -> Dict:
    """How many flights actually carry a delay value (not the same as 'on time')."""
    reported = df["max_delay_min"].notna()
    delayed = df["max_delay_min"] > 0
    n = len(df)
    return {
        "flights": n,
        "delay_reported": int(reported.sum()),
        "delay_reported_pct": round(100 * reported.sum() / n, 1) if n else 0.0,
        "delayed": int(delayed.sum()),
        "delayed_pct_of_reported": round(100 * delayed.sum() / reported.sum(), 1)
        if reported.sum() else None,
    }


# ---------------------------------------------------------------------------
# 3. Descriptive statistics
# ---------------------------------------------------------------------------


def numeric_descriptives(df: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in NUMERIC_ANALYSIS_COLUMNS if c in df and df[c].notna().any()]
    desc = df[cols].describe().T
    desc["median"] = df[cols].median()
    desc["skew"] = df[cols].skew()
    out = desc[["count", "mean", "std", "min", "25%", "median", "75%", "max", "skew"]]
    return out.round(2).rename_axis("column").reset_index()


def categorical_summary(df: pd.DataFrame, columns=None, top: int = 5) -> pd.DataFrame:
    columns = columns or ["flight_status", "airline_name", "dep_iata",
                          "arr_iata", "route", "dep_timezone"]
    rows = []
    for col in columns:
        if col not in df:
            continue
        counts = df[col].value_counts()
        rows.append({
            "column": col,
            "unique": int(df[col].nunique()),
            "top_value": str(counts.index[0]) if len(counts) else None,
            "top_count": int(counts.iloc[0]) if len(counts) else 0,
            "top_share_pct": round(100 * counts.iloc[0] / len(df), 1) if len(counts) else 0.0,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 5. Trends
# ---------------------------------------------------------------------------


def trend_by_date(df: pd.DataFrame) -> pd.DataFrame:
    """Flights, delay coverage and delay rate per ``flight_date``."""
    g = df.groupby(df["flight_date"].dt.date)
    out = g.agg(
        flights=("id", "size"),
        delay_reported=("max_delay_min", "count"),
        delayed=("max_delay_min", lambda s: int((s > 0).sum())),
        mean_delay_min=("max_delay_min", "mean"),
    ).reset_index().rename(columns={"flight_date": "date"})
    out["delayed_pct_of_reported"] = (
        100 * out["delayed"] / out["delay_reported"].replace(0, np.nan)).round(1)
    out["mean_delay_min"] = out["mean_delay_min"].round(2)
    return out


def hourly_profile(df: pd.DataFrame) -> pd.DataFrame:
    """Flights and delay behaviour per scheduled-departure hour (airport-local time)."""
    g = df.dropna(subset=["dep_hour_local"]).groupby("dep_hour_local")
    out = g.agg(
        flights=("id", "size"),
        delay_reported=("max_delay_min", "count"),
        delayed=("max_delay_min", lambda s: int((s > 0).sum())),
        mean_delay_min=("max_delay_min", "mean"),
    ).reset_index()
    out["delayed_pct_of_reported"] = (
        100 * out["delayed"] / out["delay_reported"].replace(0, np.nan)).round(1)
    out["mean_delay_min"] = out["mean_delay_min"].round(2)
    return out


# ---------------------------------------------------------------------------
# 6. Relationships
# ---------------------------------------------------------------------------


def correlation_matrix(df: pd.DataFrame, method: str = "spearman") -> pd.DataFrame:
    """Rank correlation between numeric columns (robust to skewed delays)."""
    cols = [c for c in ("dep_delay_min", "arr_delay_min", "scheduled_duration_min",
                        "live_speed_kmh", "live_altitude", "dep_hour_local")
            if c in df and df[c].notna().sum() >= 5]
    return df[cols].corr(method=method).round(2)


def pairwise_counts(df: pd.DataFrame, cols) -> pd.DataFrame:
    """Number of rows that have BOTH values - the n behind each correlation."""
    notna = df[list(cols)].notna().astype(int)
    return (notna.T @ notna).rename_axis(None).rename_axis(None, axis=1)


def two_proportion_ztest(x1: int, n1: int, x2: int, n2: int) -> Dict:
    """Two-sided z-test for a difference between two proportions."""
    if min(n1, n2) == 0:
        return {"p1": None, "p2": None, "z": None, "p_value": None}
    p1, p2 = x1 / n1, x2 / n2
    pooled = (x1 + x2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if se == 0:
        return {"p1": p1, "p2": p2, "z": 0.0, "p_value": 1.0}
    z = (p1 - p2) / se
    return {"p1": round(p1, 4), "p2": round(p2, 4), "z": round(z, 3),
            "p_value": round(math.erfc(abs(z) / math.sqrt(2)), 4)}


def codeshare_vs_delay(df: pd.DataFrame) -> Dict:
    """Compare the share of delayed flights for codeshared vs operated flights.

    Only flights that report a delay value are used; a missing delay is not
    treated as 'on time'.
    """
    rep = df[df["max_delay_min"].notna()]
    groups = {}
    for flag, label in ((False, "operated"), (True, "codeshared")):
        sub = rep[rep["is_codeshared"] == flag]
        groups[label] = {"n": int(len(sub)),
                         "delayed": int((sub["max_delay_min"] > 0).sum())}
    test = two_proportion_ztest(groups["operated"]["delayed"], groups["operated"]["n"],
                                groups["codeshared"]["delayed"], groups["codeshared"]["n"])
    return {"groups": groups, "test": test}


# ---------------------------------------------------------------------------
# 7. Comparisons
# ---------------------------------------------------------------------------


def delay_by_group(df: pd.DataFrame, by: str, min_reported: int = 4,
                   top: int = 10) -> pd.DataFrame:
    """Delay behaviour per group, using only groups with enough delay data."""
    rep = df[df["max_delay_min"].notna()]
    g = rep.groupby(by).agg(
        flights_with_delay_data=("id", "size"),
        delayed=("max_delay_min", lambda s: int((s > 0).sum())),
        mean_delay_min=("max_delay_min", "mean"),
        max_delay_min=("max_delay_min", "max"),
    )
    g = g[g["flights_with_delay_data"] >= min_reported].copy()
    g["delayed_pct"] = (100 * g["delayed"] / g["flights_with_delay_data"]).round(1)
    g["mean_delay_min"] = g["mean_delay_min"].round(2)
    return (g.sort_values(["mean_delay_min", "flights_with_delay_data"], ascending=False)
            .head(top).reset_index())


def status_vs_delay(df: pd.DataFrame) -> pd.DataFrame:
    return df.groupby("flight_status").agg(
        flights=("id", "size"),
        delay_reported=("max_delay_min", "count"),
        delayed=("max_delay_min", lambda s: int((s > 0).sum())),
        mean_delay_min=("max_delay_min", "mean"),
    ).round(2).reset_index()


# ---------------------------------------------------------------------------
# 8. Outliers
# ---------------------------------------------------------------------------


def iqr_outliers(df: pd.DataFrame, column: str, positive_only: bool = False,
                 factor: float = 1.5) -> Dict:
    """Tukey IQR rule. ``positive_only`` restricts to values > 0.

    Delays need ``positive_only=True``: most flights report 0 delay, so the
    IQR of the raw column collapses to 0 and every delayed flight would be
    flagged. Using only flights that *were* delayed gives a meaningful fence.
    """
    series = df[column].dropna()
    if positive_only:
        series = series[series > 0]
    if len(series) < 4:
        return {"column": column, "n": int(len(series)), "outliers": 0}
    q1, q3 = series.quantile(0.25), series.quantile(0.75)
    iqr = q3 - q1
    lower, upper = q1 - factor * iqr, q3 + factor * iqr
    mask = (series < lower) | (series > upper)
    cols = [c for c in ("flight_iata", "airline_name", "route", "flight_date", column)
            if c in df]
    rows = df.loc[series[mask].index, cols].sort_values(column, ascending=False)
    return {
        "column": column, "positive_only": positive_only, "n": int(len(series)),
        "q1": round(float(q1), 2), "q3": round(float(q3), 2), "iqr": round(float(iqr), 2),
        "lower_fence": round(float(lower), 2), "upper_fence": round(float(upper), 2),
        "outliers": int(mask.sum()), "outlier_pct": round(100 * mask.sum() / len(series), 1),
        "median": round(float(series.median()), 2), "max": round(float(series.max()), 2),
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# 9. Findings
# ---------------------------------------------------------------------------


def _fmt_p(p: Optional[float]) -> str:
    return "n/a" if p is None else ("p < 0.001" if p < 0.001 else f"p = {p:.3f}")


def key_findings(df: pd.DataFrame) -> List[str]:
    """Findings written from the computed numbers (no hand-typed statistics)."""
    if df.empty:
        return ["The database is empty - run the pipeline first."]
    f: List[str] = []
    prof = dataset_profile(df)
    cov = delay_coverage(df)
    f.append(
        f"The database holds {prof['rows']} validated flights across "
        f"{prof['capture_dates']} flight dates ({prof['date_min']} to {prof['date_max']}); "
        "it is a snapshot of live data, not a time series.")

    status = df["flight_status"].value_counts()
    f.append(f"{100 * status.iloc[0] / len(df):.1f}% of flights are '{status.index[0]}'; "
             f"only {len(status)} distinct status value(s) occur "
             f"({', '.join(status.index)}), so status carries little discriminating power.")

    f.append(
        f"Only {cov['delay_reported']} of {cov['flights']} flights "
        f"({cov['delay_reported_pct']}%) report a delay value, so delay statistics "
        "describe that subset and not all flights.")
    if cov["delay_reported"]:
        d = df["max_delay_min"].dropna()
        pos = d[d > 0]
        skew = d.skew()
        shape = ("strongly right-skewed" if skew > 1 else
                 "roughly symmetric" if abs(skew) <= 0.5 else "moderately skewed")
        f.append(
            f"Among flights with delay data, {cov['delayed']} "
            f"({cov['delayed_pct_of_reported']}%) were delayed; the median delay is "
            f"{d.median():.0f} min but the mean is {d.mean():.1f} min and the maximum "
            f"{d.max():.0f} min - the distribution is {shape} (skew {skew:.1f}).")
        if len(pos):
            f.append(f"When a delay occurs it is typically {pos.median():.0f} min (median of "
                     f"delayed flights); {int((pos >= 30).sum())} delay(s) reach 30 min or more.")

    dur = iqr_outliers(df, "scheduled_duration_min")
    if "upper_fence" in dur:
        f.append(
            f"Scheduled block time (timezone-corrected) has a median of {dur['median']:.0f} min "
            f"and a maximum of {dur['max']:.0f} min; {dur['outliers']} flights "
            f"({dur['outlier_pct']}%) lie above the IQR upper fence of {dur['upper_fence']:.0f} min. "
            "All are below the 24-hour validity limit, so they were retained and listed for review.")

    cs = codeshare_vs_delay(df)
    g, t = cs["groups"], cs["test"]
    if t["p1"] is not None and min(g["operated"]["n"], g["codeshared"]["n"]) >= 10:
        higher = "Operated flights" if t["p1"] > t["p2"] else "Codeshared listings"
        lower = "codeshared listings" if t["p1"] > t["p2"] else "operated flights"
        verdict = ("a statistically detectable difference" if t["p_value"] is not None and t["p_value"] < 0.05
                   else "no statistically detectable difference")
        f.append(
            f"{higher} were delayed more often than {lower} "
            f"({100 * t['p1']:.0f}% of {g['operated']['n']} operated vs "
            f"{100 * t['p2']:.0f}% of {g['codeshared']['n']} codeshared; two-proportion "
            f"z-test {_fmt_p(t['p_value'])}) - {verdict}. Codeshare rows are marketing "
            "listings of a partner's flight and delay values may not be reported for them "
            "in the same way, so this is an association in a small sample, not a cause.")

    hrs = hourly_profile(df)
    if len(hrs):
        peak = hrs.sort_values("flights", ascending=False).iloc[0]
        f.append(f"Scheduled departures peak at {int(peak['dep_hour_local']):02d}:00 local time "
                 f"({int(peak['flights'])} flights).")

    air = df["airline_name"].value_counts()
    if len(air):
        share = 100 * air.iloc[0] / len(df)
        concl = ("no single carrier dominates the sample" if share < 15
                 else "one carrier is over-represented in the sample")
        f.append(f"{df['airline_name'].nunique()} airlines appear; the largest, {air.index[0]}, "
                 f"accounts for {share:.1f}% of flights - {concl}.")

    live = int(df["live_speed_kmh"].notna().sum())
    if live:
        f.append(f"Live tracking data (speed, altitude, position) exists for only {live} "
                 f"flights ({100 * live / len(df):.1f}%), so those fields support illustration "
                 "rather than inference.")
    return f


# ---------------------------------------------------------------------------
# Evidence for the timestamp finding (reproducible from the raw archive)
# ---------------------------------------------------------------------------


def timestamp_semantics_check(payloads: List[dict]) -> pd.DataFrame:
    """Test how the API's ``+00:00`` timestamps should be read.

    For flights that carry both ``live.updated`` (a genuine UTC instant) and a
    departure ``actual`` time, compare the two readings of ``actual``:

    * *literal*    - trust the ``+00:00`` suffix;
    * *wall-clock* - treat the digits as airport-local time.

    A correct reading must put ``live.updated`` AFTER the departure.
    """
    from datetime import datetime

    from .timeutils import wall_clock_to_utc

    rows = []
    for payload in payloads:
        for rec in payload.get("data") or []:
            live, dep = rec.get("live") or {}, rec.get("departure") or {}
            if not (live.get("updated") and dep.get("actual") and dep.get("timezone")):
                continue
            updated = datetime.fromisoformat(str(live["updated"]).replace("Z", "+00:00"))
            literal = datetime.fromisoformat(str(dep["actual"]).replace("Z", "+00:00"))
            local = wall_clock_to_utc(dep["actual"], dep["timezone"])
            if local is None:
                continue
            rows.append({
                "flight": (rec.get("flight") or {}).get("iata"),
                "dep_airport": dep.get("iata"),
                "dep_timezone": dep["timezone"],
                "minutes_after_departure_literal": round((updated - literal).total_seconds() / 60),
                "minutes_after_departure_wallclock": round((updated - local).total_seconds() / 60),
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _jsonable(obj):
    if isinstance(obj, pd.DataFrame):
        return obj.to_dict("records")
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return None if np.isnan(obj) else float(obj)
    if isinstance(obj, (pd.Timestamp, datetime, date)):
        return obj.isoformat()
    raise TypeError(type(obj))


def build_summary(df: pd.DataFrame) -> Dict:
    """Run every analysis and return the results as one dictionary."""
    prof = dataset_profile(df)
    return {
        "profile": {k: v for k, v in prof.items() if k != "dtype_table"},
        "dtypes": prof.get("dtype_table"),
        "missing": missing_values_table(df),
        "duplicates": duplicate_checks(df),
        "constant_columns": constant_columns(df),
        "delay_coverage": delay_coverage(df),
        "numeric": numeric_descriptives(df),
        "categorical": categorical_summary(df),
        "trend_by_date": trend_by_date(df),
        "hourly": hourly_profile(df),
        "correlation_spearman": correlation_matrix(df),
        "codeshare_vs_delay": codeshare_vs_delay(df),
        "delay_by_airline": delay_by_group(df, "airline_name"),
        "delay_by_dep_airport": delay_by_group(df, "dep_iata"),
        "status_vs_delay": status_vs_delay(df),
        "outliers": {
            "scheduled_duration_min": iqr_outliers(df, "scheduled_duration_min"),
            "delay_min_positive": iqr_outliers(df, "max_delay_min", positive_only=True),
            "live_speed_kmh": iqr_outliers(df, "live_speed_kmh"),
        },
        "findings": key_findings(df),
    }


def _md_table(df: pd.DataFrame, max_rows: int = 15) -> str:
    if df is None or len(df) == 0:
        return "_(none)_\n"
    df = df.head(max_rows)
    head = "| " + " | ".join(str(c) for c in df.columns) + " |"
    sep = "|" + "|".join("---" for _ in df.columns) + "|"
    body = ["| " + " | ".join("" if pd.isna(v) else str(v) for v in row) + " |"
            for row in df.itertuples(index=False)]
    return "\n".join([head, sep] + body) + "\n"


def write_markdown(summary: Dict, path: Path) -> Path:
    """Human-readable EDA report generated from the computed results."""
    prof = summary["profile"]
    lines = [
        "# Exploratory Data Analysis - generated from the SQLite database", "",
        f"*{prof['rows']} flights x {prof['columns']} columns, "
        f"{prof['date_min']} to {prof['date_max']} ({prof['capture_dates']} flight dates).*", "",
        "## Key findings", "", *[f"{i}. {t}" for i, t in enumerate(summary["findings"], 1)], "",
        "## Data quality", "",
        f"* Exact duplicate rows: {summary['duplicates']['exact_duplicate_rows']}; "
        f"natural-key duplicates: {summary['duplicates']['natural_key_duplicates']}",
        f"* Constant columns: {', '.join(summary['constant_columns']) or 'none'}",
        f"* Delay coverage: {summary['delay_coverage']}", "",
        "### Missing values", "", _md_table(summary["missing"], 30),
        "## Descriptive statistics (numeric)", "", _md_table(summary["numeric"]),
        "## Categorical summary", "", _md_table(summary["categorical"]),
        "## Flights per capture date", "", _md_table(summary["trend_by_date"]),
        "## Delay by departure hour (local)", "", _md_table(summary["hourly"], 30),
        "## Spearman correlation", "", _md_table(summary["correlation_spearman"].reset_index()),
        "## Delay by airline (>= 4 flights with delay data)", "",
        _md_table(summary["delay_by_airline"]),
        "## Outliers (Tukey IQR)", "",
    ]
    for name, block in summary["outliers"].items():
        meta = {k: v for k, v in block.items() if k != "rows"}
        lines += [f"**{name}**: `{meta}`", "", _md_table(block.get("rows"), 10)]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def run_eda(db_path=None, save: bool = True, charts: bool = True) -> Dict:
    """Load from SQLite, analyse, draw charts and write the EDA artifacts."""
    df = load_dataset(db_path)
    if df.empty:
        raise ValueError("The database contains no flights - run the pipeline first.")
    summary = build_summary(df)
    figures: Dict[str, str] = {}
    if charts:
        from . import eda_charts
        figures = eda_charts.save_all(df, summary)
    summary["figures"] = figures
    # Reproducible evidence for the timestamp finding, from the raw archive.
    payloads = []
    for path in sorted(config.DATA_RAW_DIR.glob("*.json")):
        try:
            payloads.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    summary["timestamp_evidence"] = timestamp_semantics_check(payloads)
    if save:
        summary["timestamp_evidence"].to_csv(config.EDA_DIR / "timestamp_evidence.csv", index=False)
        # outlier row tables are for display; keep JSON compact
        slim = json.loads(json.dumps(summary, default=_jsonable))
        for block in slim["outliers"].values():
            block.pop("rows", None)
        save_json(slim, config.EDA_DIR / "eda_summary.json")
        write_markdown(summary, config.EDA_DIR / "EDA_Findings.md")
        logger.info("EDA summary written to %s", config.EDA_DIR)
    return summary
