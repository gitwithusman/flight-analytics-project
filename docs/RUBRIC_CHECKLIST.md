# Rubric checklist - ETL + EDA Pipeline (Weeks 6-8, CLO2, 10 marks)

> "Build an ETL pipeline that extracts data from an API, transforms/validates it with pandas and Pydantic,
> loads it to a database, and conducts a structured exploratory data analysis on the result."

Final marks depend on the instructor's evaluation. Evidence paths are relative to the project root.

| # | Requirement | Implementation | Evidence |
|---|---|---|---|
| 1 | Extract real data from an API | `src/api_client.py` (`fetch_flights`, `fetch_flights_paged`), AviationStack `/v1/flights` | `data/raw/` (4 real responses, 235 records); `refresh_log` runs 1-5 |
| 2 | HTTP errors, timeouts, empty responses, API failures | `_request`: retries with exponential back-off, provider error mapping, empty / non-JSON / malformed body handling; failures logged | Report section 6; `tests/test_pipeline.py`; run 4 (HTTP 403) in `refresh_log` |
| 3 | Credentials via environment variables | `src/config.py`, `.env.example`, `.gitignore`, `_redact()` | `test_api_key_never_appears_in_error_messages` |
| 4 | pandas cleaning (missing, duplicates, types, formats, invalid) | `src/data_processor.py` (`TRANSFORM_DECISIONS`), `src/timeutils.py` | Report section 8; `outputs/reports/pipeline_run_*.json` |
| 5 | Pydantic validation; accepted / rejected / errors reported | `src/models.py` (2 gates, `ValidationReport`) | 232 accepted / 3 rejected; `rejected_records` table + CSV; `validation_stress_test.json` (11 of 11) |
| 6 | Database: schema, PKs, duplicate prevention, safe ops, transactions | `src/database.py` (schema v2, upsert, atomic `load_batch`) | `tests/test_database_v2.py`, `test_load_is_atomic` |
| 7 | Re-run does not duplicate; verified by queries | natural-key UNIQUE + `ON CONFLICT DO UPDATE`; `verify_database()` | Report Tables 12-13; notebook section 2.5; `run_pipeline.py --inspect` |
| 8 | Structured EDA on data read from the database | `src/eda.py` -> `database.fetch_flights` | `notebooks/ETL_EDA_Analysis.ipynb`; `outputs/eda/` |
| 9 | Dimensions, types, missing, duplicates, descriptive stats | `dataset_profile`, `missing_values_table`, `duplicate_checks`, `numeric_descriptives` | Report 11.1-11.2 |
| 10 | Distributions, trends, relationships, comparisons, outliers | `src/eda_charts.py` (12 figures), z-test, Tukey IQR | `visualizations/eda/`; Report 11.3-11.7 |
| 11 | Labelled charts, interpretation, actionable findings | titles, axes with units, n annotations, `key_findings()` | Report 11.8; `outputs/eda/EDA_Findings.md` |
| 12 | Modular code, logging, error handling, config | module split, `utils.get_logger`, `config.py` | `outputs/logs/application.log`; README |
| 13 | Updated project files | notebook, runners, DB init/migration, `requirements.txt`, `README.md`, `.env.example` | project folder |
| 14 | Report matches code and verified results | every figure / number generated from artefacts | `Project_Report.pdf` / `.docx` |
| 15 | Install / configure / run / inspect / reproduce instructions | README section 1; report Appendix B | `README.md` |
| 16 | Tested end to end | 122 automated tests; pipeline, EDA, notebook, terminal and GUI runs | `python -m pytest tests/` |
| 17 | Honest limitations | report 13.3 and 14.2 | `Project_Report.pdf` |

## Known limitations (summary)
* Live API could not be called during final verification; Extract was tested with mocked HTTP and the archived real responses.
* Three flight dates only - no trend or seasonality claims. 54% of flights report a delay value.
* The "local time mislabelled as UTC" finding is proven on 11 Asian departures; applied to all airports.
* 43 flights have an unresolvable timezone, so their times stay NULL (nothing is guessed).
