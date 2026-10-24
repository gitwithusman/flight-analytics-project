# Exploratory Data Analysis - generated from the SQLite database

*230 flights x 47 columns, 2026-10-09 to 2026-10-13 (3 flight dates).*

## Key findings

1. The database holds 230 validated flights across 3 flight dates (2026-10-09 to 2026-10-13); it is a snapshot of live data, not a time series.
2. 80.0% of flights are 'scheduled'; only 3 distinct status value(s) occur (scheduled, active, landed), so status carries little discriminating power.
3. Only 125 of 230 flights (54.3%) report a delay value, so delay statistics describe that subset and not all flights.
4. Among flights with delay data, 28 (22.4%) were delayed; the median delay is 0 min but the mean is 4.0 min and the maximum 68 min - the distribution is strongly right-skewed (skew 4.2).
5. When a delay occurs it is typically 12 min (median of delayed flights); 4 delay(s) reach 30 min or more.
6. Scheduled block time (timezone-corrected) has a median of 135 min and a maximum of 735 min; 17 flights (9.1%) lie above the IQR upper fence of 449 min. All are below the 24-hour validity limit, so they were retained and listed for review.
7. Operated flights were delayed more often than codeshared listings (40% of 57 operated vs 7% of 68 codeshared; two-proportion z-test p < 0.001) - a statistically detectable difference. Codeshare rows are marketing listings of a partner's flight and delay values may not be reported for them in the same way, so this is an association in a small sample, not a cause.
8. Scheduled departures peak at 19:00 local time (36 flights).
9. 101 airlines appear; the largest, Japan Airlines, accounts for 5.2% of flights - no single carrier dominates the sample.
10. Live tracking data (speed, altitude, position) exists for only 16 flights (7.0%), so those fields support illustration rather than inference.

## Data quality

* Exact duplicate rows: 0; natural-key duplicates: 0
* Constant columns: first_seen_at, updated_at
* Delay coverage: {'flights': 230, 'delay_reported': 125, 'delay_reported_pct': np.float64(54.3), 'delayed': 28, 'delayed_pct_of_reported': np.float64(22.4)}

### Missing values

| column | missing | missing_pct |
|---|---|---|
| arr_actual | 229 | 99.6 |
| aircraft_registration | 217 | 94.3 |
| arr_gate | 216 | 93.9 |
| live_is_ground | 214 | 93.0 |
| live_latitude | 214 | 93.0 |
| live_longitude | 214 | 93.0 |
| live_altitude | 214 | 93.0 |
| live_speed_kmh | 214 | 93.0 |
| dep_actual | 213 | 92.6 |
| arr_estimated | 213 | 92.6 |
| arr_delay_min | 212 | 92.2 |
| arr_baggage | 183 | 79.6 |
| dep_terminal | 119 | 51.7 |
| dep_gate | 114 | 49.6 |
| arr_terminal | 111 | 48.3 |
| aircraft_icao24 | 105 | 45.7 |
| max_delay_min | 105 | 45.7 |
| dep_delay_min | 105 | 45.7 |
| scheduled_duration_min | 43 | 18.7 |
| dep_estimated | 23 | 10.0 |
| dep_scheduled | 23 | 10.0 |
| dep_timezone | 23 | 10.0 |
| arr_timezone | 23 | 10.0 |
| arr_scheduled | 23 | 10.0 |
| arr_airport | 6 | 2.6 |
| airline_iata | 3 | 1.3 |
| dep_airport | 3 | 1.3 |
| flight_number | 1 | 0.4 |

## Descriptive statistics (numeric)

| column | count | mean | std | min | 25% | median | 75% | max | skew |
|---|---|---|---|---|---|---|---|---|---|
| dep_delay_min | 125.0 | 3.96 | 10.94 | 0.0 | 0.0 | 0.0 | 0.0 | 68.0 | 4.19 |
| arr_delay_min | 18.0 | 0.72 | 2.27 | 0.0 | 0.0 | 0.0 | 0.0 | 9.0 | 3.37 |
| max_delay_min | 125.0 | 3.96 | 10.94 | 0.0 | 0.0 | 0.0 | 0.0 | 68.0 | 4.19 |
| scheduled_duration_min | 187.0 | 180.43 | 132.99 | 20.0 | 92.5 | 135.0 | 235.0 | 735.0 | 1.83 |
| live_speed_kmh | 16.0 | 637.31 | 291.01 | 0.0 | 590.11 | 783.13 | 823.21 | 829.7 | -1.58 |
| live_altitude | 16.0 | 7341.4 | 4065.19 | 0.0 | 5450.2 | 8450.58 | 10439.4 | 11574.8 | -0.96 |

## Categorical summary

| column | unique | top_value | top_count | top_share_pct |
|---|---|---|---|---|
| flight_status | 3 | scheduled | 184 | 80.0 |
| airline_name | 101 | Japan Airlines | 12 | 5.2 |
| dep_iata | 53 | TFU | 28 | 12.2 |
| arr_iata | 99 | SAI | 16 | 7.0 |
| route | 127 | BKK-SAI | 14 | 6.1 |
| dep_timezone | 26 | Asia/Shanghai | 48 | 20.9 |

## Flights per capture date

| date | flights | delay_reported | delayed | mean_delay_min | delayed_pct_of_reported |
|---|---|---|---|---|---|
| 2026-10-09 | 132 | 66 | 9 | 2.45 | 13.6 |
| 2026-10-10 | 1 | 0 | 0 |  |  |
| 2026-10-13 | 97 | 59 | 19 | 5.64 | 32.2 |

## Delay by departure hour (local)

| dep_hour_local | flights | delay_reported | delayed | mean_delay_min | delayed_pct_of_reported |
|---|---|---|---|---|---|
| 0 | 3 | 1 | 1 | 27.0 | 100.0 |
| 1 | 1 | 0 | 0 |  |  |
| 4 | 1 | 0 | 0 |  |  |
| 6 | 2 | 0 | 0 |  |  |
| 8 | 14 | 12 | 8 | 7.5 | 66.7 |
| 9 | 34 | 30 | 7 | 3.37 | 23.3 |
| 10 | 11 | 4 | 2 | 4.0 | 50.0 |
| 11 | 13 | 8 | 2 | 9.25 | 25.0 |
| 12 | 18 | 5 | 1 | 11.0 | 20.0 |
| 13 | 22 | 21 | 0 | 0.0 | 0.0 |
| 14 | 12 | 8 | 5 | 7.12 | 62.5 |
| 15 | 1 | 0 | 0 |  |  |
| 16 | 6 | 2 | 0 | 0.0 | 0.0 |
| 17 | 35 | 17 | 1 | 0.59 | 5.9 |
| 18 | 11 | 0 | 0 |  |  |
| 19 | 36 | 12 | 1 | 5.42 | 8.3 |
| 20 | 10 | 5 | 0 | 0.0 | 0.0 |

## Spearman correlation

| index | dep_delay_min | arr_delay_min | scheduled_duration_min | live_speed_kmh | live_altitude | dep_hour_local |
|---|---|---|---|---|---|---|
| dep_delay_min | 1.0 | 0.55 | -0.21 | 0.34 | 0.1 | -0.32 |
| arr_delay_min | 0.55 | 1.0 | 0.21 | -0.04 | -0.1 | -0.18 |
| scheduled_duration_min | -0.21 | 0.21 | 1.0 | 0.42 | 0.66 | -0.08 |
| live_speed_kmh | 0.34 | -0.04 | 0.42 | 1.0 | 0.62 | 0.3 |
| live_altitude | 0.1 | -0.1 | 0.66 | 0.62 | 1.0 | 0.41 |
| dep_hour_local | -0.32 | -0.18 | -0.08 | 0.3 | 0.41 | 1.0 |

## Delay by airline (>= 4 flights with delay data)

| airline_name | flights_with_delay_data | delayed | mean_delay_min | max_delay_min | delayed_pct |
|---|---|---|---|---|---|
| Japan Airlines | 12 | 8 | 9.5 | 32.0 | 66.7 |
| Philippine Airlines | 5 | 4 | 8.8 | 23.0 | 80.0 |
| IndiGo | 4 | 1 | 2.5 | 10.0 | 25.0 |
| China Eastern Airlines | 6 | 0 | 0.0 | 0.0 | 0.0 |
| Air China | 4 | 0 | 0.0 | 0.0 | 0.0 |
| China Southern Airlines | 4 | 0 | 0.0 | 0.0 | 0.0 |
| Fiji Airways | 4 | 0 | 0.0 | 0.0 | 0.0 |

## Outliers (Tukey IQR)

**scheduled_duration_min**: `{'column': 'scheduled_duration_min', 'positive_only': False, 'n': 187, 'q1': 92.5, 'q3': 235.0, 'iqr': 142.5, 'lower_fence': -121.25, 'upper_fence': 448.75, 'outliers': 17, 'outlier_pct': np.float64(9.1), 'median': 135.0, 'max': 735.0}`

| flight_iata | airline_name | route | flight_date | scheduled_duration_min |
|---|---|---|---|---|
| C87112 | Federal Airlines | MXP-ICN | 2026-10-13 00:00:00 | 735.0 |
| NZ282 | Air New Zealand | AKL-SIN | 2026-10-10 00:00:00 | 650.0 |
| QF5551 | Qantas | MEL-CMB | 2026-10-13 00:00:00 | 620.0 |
| TK6622 | Turkish Airlines | MIA-IST | 2026-10-13 00:00:00 | 603.0 |
| TK9214 | Turkish Airlines | MEL-HKG | 2026-10-13 00:00:00 | 580.0 |
| JL7890 | Japan Airlines | MEL-SIN | 2026-10-13 00:00:00 | 490.0 |
| FJ5324 | Fiji Airways | MEL-SIN | 2026-10-13 00:00:00 | 490.0 |
| AY5014 | Finnair | MEL-SIN | 2026-10-13 00:00:00 | 490.0 |
| EK5035 | Emirates | MEL-SIN | 2026-10-13 00:00:00 | 490.0 |
| 6E4603 | IndiGo | MEL-SIN | 2026-10-13 00:00:00 | 490.0 |

**delay_min_positive**: `{'column': 'max_delay_min', 'positive_only': True, 'n': 28, 'q1': 7.75, 'q3': 15.25, 'iqr': 7.5, 'lower_fence': -3.5, 'upper_fence': 26.5, 'outliers': 5, 'outlier_pct': np.float64(17.9), 'median': 12.0, 'max': 68.0}`

| flight_iata | airline_name | route | flight_date | max_delay_min |
|---|---|---|---|---|
| PFY312 | Pel-Air | MQL-MEB | 2026-10-13 00:00:00 | 68.0 |
| 9C6464 | Spring Airlines | LHW-PVG | 2026-10-09 00:00:00 | 65.0 |
| HO5723 | Juneyao Air | MXZ-PVG | 2026-10-13 00:00:00 | 55.0 |
| JL562 | Japan Airlines | MMB-HND | 2026-10-13 00:00:00 | 32.0 |
| RV1888 | Air Canada | MEX-YYZ | 2026-10-13 00:00:00 | 27.0 |

**live_speed_kmh**: `{'column': 'live_speed_kmh', 'positive_only': False, 'n': 16, 'q1': 590.11, 'q3': 823.21, 'iqr': 233.1, 'lower_fence': 240.46, 'upper_fence': 1172.86, 'outliers': 2, 'outlier_pct': np.float64(12.5), 'median': 783.13, 'max': 829.7}`

| flight_iata | airline_name | route | flight_date | live_speed_kmh |
|---|---|---|---|---|
| PR3111 | Philippine Airlines | IWK-HND | 2026-10-13 00:00:00 | 0.0 |
| UA7920 | United Airlines | IWK-HND | 2026-10-13 00:00:00 | 0.0 |
