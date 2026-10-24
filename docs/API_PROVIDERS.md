# External APIs - selection, verification and status

Researched against each provider's own documentation (and, where noted, secondary sources) on 18-19 Oct 2026.
**Status column = what has actually been verified in this project.** Nothing below is claimed to work live until it has
been tested with a real key (see "Live verification" at the end).

| Purpose | Provider | Key needed | Free tier | Docs | Verified so far |
|---|---|---|---|---|---|
| Flight status, stored flight snapshots | **AviationStack** `/v1/flights` | yes (`AVIATIONSTACK_API_KEY`) | yes, ~100 requests/month, HTTP only, ~100 records/request | https://aviationstack.com/documentation | used successfully by the original project (4 real responses archived in `data/raw/`); not re-tested in the final sandbox (no outbound access) |
| Flight search options (airline, times, stops, duration) | **FlightAPI** `onewaytrip` / `roundtrip` (https://api.flightapi.io) | yes (`FLIGHTAPI_API_KEY`, from your FlightAPI dashboard) | credit based (2 credits per search) | https://www.flightapi.io/documentation/oneway-trip-api/ | request/response handling verified with mocked HTTP against the documented structure; **live call not yet made** |
| Weather (forecast / current / historical) | **Open-Meteo** | none | free for non-commercial use (<10,000 calls/day), attribution required (CC BY 4.0) | https://open-meteo.com/en/docs | request/response handling verified with mocked HTTP; live call not yet made |
| Airport coordinates, names, countries | **OurAirports** (bundled CSV) | none | public domain | https://ourairports.com/data/ | verified: 134 of 134 stored airports resolve to coordinates |
| Map land outline | **Natural Earth** 1:110m (bundled GeoJSON) | none | public domain | https://www.naturalearthdata.com | verified (renders offline) |

## Why not the usual alternatives
* **Amadeus Self-Service (Flight Offers Search)** - the common free student choice. Multiple sources (including a developer
  write-up dated July 2026 and the project's own changelogs) report that the Self-Service portal was **shut down on
  17 July 2026**. It was therefore not used.
* **Duffel**, **Skyscanner**, **Kiwi Tequila**, **SerpApi Google Flights** - require partner approval, paid plans or offer
  only sandbox / very small free quotas; none was assumed to be free or approved. They can be added behind the same
  provider interface (`src/providers/`) if you obtain access.

## What the flight-search data is (and is not)
FlightAPI returns itineraries (carrier, flight number, departure / arrival, stops, duration). The application reads
**only those itinerary facts**; pricing blocks in the response are ignored and never stored or shown (the flights-fares
feature was removed in v2.1; the API's URL still requires a currency segment, so a fixed placeholder is sent).
* options are **not a booking guarantee** - schedules and availability change; confirm with the airline or agent;
* the API provides **no baggage allowance** - the UI shows "not provided"; an arrival time missing from the source is
  shown only as *derived* (departure + duration) and marked as such;
* a booking link is opened only if it is on a verified host; the app never invents URLs and does not book inside it;
* routes with no flights return an empty result and the UI says so instead of showing anything made up.
* Travelpayouts / Aviasales (a cached-price API) was part of earlier versions and has been removed together with the
  fare feature.

## Credentials
All keys are read from environment variables / `.env` (git-ignored). `.env.example` contains names and placeholders only.
Keys are never logged: every error message and the log viewer pass through a scrubber, and Settings shows keys masked.

## Live verification (to be completed)
Pending: the project owner provides `AVIATIONSTACK_API_KEY` (already used before) and `FLIGHTAPI_API_KEY`; each
integration is then tested with a real request and the results recorded here and in the project report.
