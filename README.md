# orbit-propagator-comparison

Compares various orbit propagation libraries for performance and accuracy.

The tool runs four SGP4-based transit predictors against the same OMM
(Orbit Mean-Elements Message) and observer location, then compares the
start/peak/stop look angles they compute for each pass:

- **jspredict** (TypeScript) — `@nsat/jspredict`
- **skyfield** (Python) — `EarthSatellite.from_omm` + `find_events`
- **beyond** (Python) — `station.visibility`
- **pypredict** (Python) — `predict.transits` (wrapper around the `predict` C library)

> **Note on coordinates:** pypredict's underlying `predict` library uses the
> classic convention of NORTH latitude and WEST-positive longitude, which is the
> opposite sign of the east-positive convention used by the other libraries and
> by this tool's `--observer` argument. The pypredict benchmark negates the
> incoming east-positive longitude before handing it to pypredict.

## Usage

```bash
# Default observer (Boulder, CO)
uv run python main.py resources/iss.omm.json

# Custom observer (JSON: east-positive lon in degrees, alt in meters)
uv run python main.py resources/iss.omm.json --observer '{"lat": 40.015, "lon": -105.2705, "alt": 1655}'
```

## Transit Count Benchmark

`transit_count_benchmark.py` measures how long each library takes to count the
transits over a 24 hour window starting at the **current date and time**, for
every satellite in a directory and every ground station in a JSON file, and
checks whether the libraries agree on the number of transits.

```bash
uv run python transit_count_benchmark.py <satellite_dir> <groundstations.json>

# e.g.
uv run python transit_count_benchmark.py resources/tle resources/groundstations.json

# Only some libraries, and save every per-pair result for later analysis
uv run python transit_count_benchmark.py resources/tle resources/groundstations.json \
    --libraries jspredict,skyfield --json-output results.json

# Count only passes that climb above 10 degrees
uv run python transit_count_benchmark.py resources/tle resources/groundstations.json --min-elevation 10
```

Options: `--min-elevation DEG` (default 5), `--hours N` (window length, default
24), `--libraries a,b,c`, `--max-mismatch-rows N` (default 50) and
`--json-output PATH`.

**Inputs**

- *Satellite directory* — every `.tle`/`.txt`/`.3le` file (2-line or 3-line
  TLEs, one or many satellites per file) and every `.json` file (an OMM object
  or a list of OMM objects). Other files are skipped with a warning.
  pypredict can only read TLEs, so for OMM files it uses the
  `TLE_LINE1`/`TLE_LINE2` fields; an OMM without them is reported as an error
  for that library.
- *Ground station file* — a JSON list in the format of
  `resources/groundstations.json`:
  `{"name": "...", "location": {"latitude": deg, "longitude": deg (east-positive), "height": meters}}`.

**What is measured**

- All libraries get identical inputs and the same window start time, and are
  run one after another (never in parallel).
- Timing covers only the transit search for one satellite/ground station pair.
  Building the satellite and observer objects happens once up front and is
  reported separately as *Setup*. Skyfield and jspredict are given the OMM
  directly when one is available.
- A transit is the span between AOS and LOS, where AOS and LOS are the times
  the satellite crosses the minimum elevation (`--min-elevation`, default 5°)
  going up and coming down. Both must fall inside the window: a pass already in
  progress when the window opens, or still in progress when it closes, is not
  counted, so a library that reports one is not credited with an extra
  transit. Passes that never reach the minimum elevation are not transits.
  Each library's native support is used: jspredict's `aos`/`los` events,
  skyfield's `find_events(altitude_degrees=...)` and pypredict's
  `Transit.above(...)`.
- Even so, libraries can still differ on passes that are borderline: ones whose
  peak barely reaches the minimum elevation (a few seconds long) or whose AOS/LOS
  lands within a second or so of the window edge.

**Output** — an execution-time summary per library, transit counts and time per
ground station (with a ✓/✗ for whether every satellite agreed across libraries),
and a list of each satellite/station pair where the counts differ. Pairs where a
library raised an error are shown in the *Errors* column and excluded from the
agreement check.

The runners live in `benchmarks/transit_count/` (`common.py` plus one runner
per library) and can be reused outside the orchestrator; they read a normalized
satellite manifest and station list and print a JSON document.

## Benchmark Results — ISS (ZARYA)

### Input Parameters

| Parameter | Value |
| --- | --- |
| OMM file | `resources/iss.omm.json` |
| Satellite | ISS (ZARYA) |
| NORAD Cat ID | 25544 |
| OMM epoch | 2026-08-19T03:31:32.932416 |
| Observer latitude | 40.0150° |
| Observer longitude | -105.2705° |
| Observer altitude | 1655.0 m |
| Start time (UTC) | 2026-08-19T09:31:32.932Z |
| Stop time (UTC) | 2026-08-20T09:31:32.932Z |
| Duration | 24 hours |
| Min elevation (AOS/LOS) | 0.0° |

### Transit #1

**Start**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 09:49:49.574 | 195.636 | 0.000 | 2327.677 |
| skyfield | 09:49:49.579 | 195.636 | 0.000 | 2327.654 |
| beyond | 09:49:49.573 | 195.636 | 0.000 | 2327.681 |
| pypredict | 09:49:50.031 | 195.599 | 0.026 | 2324.837 |

**Peak**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 09:54:39.353 | 131.206 | 17.796 | 1091.804 |
| skyfield | 09:54:39.230 | 131.258 | 17.797 | 1091.780 |
| beyond | 09:54:39.315 | 131.222 | 17.796 | 1091.805 |
| pypredict | 09:54:39.319 | 131.220 | 17.796 | 1091.805 |

**Stop**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 09:59:30.257 | 67.065 | -0.000 | 2341.913 |
| skyfield | 09:59:30.282 | 67.063 | -0.001 | 2342.043 |
| beyond | 09:59:30.256 | 67.065 | -0.000 | 2341.909 |
| pypredict | 09:59:30.734 | 67.028 | -0.027 | 2344.891 |

### Transit #2

**Start**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 11:25:49.751 | 244.625 | 0.000 | 2333.131 |
| skyfield | 11:25:49.760 | 244.626 | 0.000 | 2333.098 |
| beyond | 11:25:49.750 | 244.625 | 0.000 | 2333.137 |
| pypredict | 11:25:50.183 | 244.638 | 0.027 | 2330.186 |

**Peak**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 11:31:10.295 | 327.156 | 48.371 | 542.760 |
| skyfield | 11:31:10.198 | 327.038 | 48.369 | 542.771 |
| beyond | 11:31:10.294 | 327.155 | 48.371 | 542.761 |
| pypredict | 11:31:10.310 | 327.174 | 48.371 | 542.762 |

**Stop**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 11:36:32.734 | 49.787 | 0.000 | 2345.547 |
| skyfield | 11:36:32.750 | 49.788 | -0.001 | 2345.630 |
| beyond | 11:36:32.735 | 49.787 | -0.000 | 2345.553 |
| pypredict | 11:36:35.161 | 49.862 | -0.147 | 2362.079 |

### Transit #3

**Start**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 13:03:50.787 | 284.749 | -0.000 | 2340.324 |
| skyfield | 13:03:50.796 | 284.750 | 0.000 | 2340.302 |
| beyond | 13:03:50.787 | 284.749 | 0.000 | 2340.322 |
| pypredict | 13:03:51.348 | 284.803 | 0.030 | 2337.039 |

**Peak**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 13:08:34.271 | 346.123 | 14.253 | 1250.657 |
| skyfield | 13:08:34.181 | 346.090 | 14.253 | 1250.663 |
| beyond | 13:08:34.270 | 346.122 | 14.253 | 1250.657 |
| pypredict | 13:08:34.279 | 346.126 | 14.253 | 1250.658 |

**Stop**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 13:13:18.658 | 47.492 | 0.000 | 2347.504 |
| skyfield | 13:13:18.673 | 47.493 | -0.001 | 2347.570 |
| beyond | 13:13:18.659 | 47.492 | -0.000 | 2347.510 |
| pypredict | 13:13:10.724 | 46.721 | 0.419 | 2301.200 |

### Transit #4

**Start**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 14:41:54.874 | 309.198 | 0.000 | 2345.227 |
| skyfield | 14:41:54.886 | 309.199 | 0.000 | 2345.186 |
| beyond | 14:41:54.873 | 309.198 | 0.000 | 2345.232 |
| pypredict | 14:41:55.419 | 309.256 | 0.028 | 2342.175 |

**Peak**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 14:46:28.147 | 6.885 | 11.919 | 1373.523 |
| skyfield | 14:46:28.219 | 6.907 | 11.919 | 1373.519 |
| beyond | 14:46:28.148 | 6.886 | 11.919 | 1373.523 |
| pypredict | 14:46:28.163 | 6.890 | 11.919 | 1373.524 |

**Stop**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 14:51:01.588 | 64.531 | -0.000 | 2347.848 |
| skyfield | 14:51:01.596 | 64.531 | -0.000 | 2347.866 |
| beyond | 14:51:01.587 | 64.531 | -0.000 | 2347.845 |
| pypredict | 14:51:02.175 | 64.592 | -0.030 | 2351.141 |

### Transit #5

**Start**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 16:18:54.078 | 312.717 | 0.000 | 2347.368 |
| skyfield | 16:18:54.087 | 312.717 | 0.000 | 2347.329 |
| beyond | 16:18:54.077 | 312.717 | 0.000 | 2347.371 |
| pypredict | 16:18:54.523 | 312.743 | 0.026 | 2344.461 |

**Peak**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 16:24:06.528 | 26.680 | 27.486 | 820.505 |
| skyfield | 16:24:06.604 | 26.722 | 27.487 | 820.493 |
| beyond | 16:24:06.524 | 26.678 | 27.486 | 820.506 |
| pypredict | 16:24:06.506 | 26.667 | 27.486 | 820.506 |

**Stop**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 16:29:18.456 | 100.541 | -0.000 | 2345.103 |
| skyfield | 16:29:18.463 | 100.542 | -0.000 | 2345.117 |
| beyond | 16:29:18.456 | 100.541 | -0.000 | 2345.105 |
| pypredict | 16:29:18.869 | 100.565 | -0.024 | 2347.805 |

### Transit #6

**Start**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 17:55:39.294 | 300.894 | 0.000 | 2347.857 |
| skyfield | 17:55:39.298 | 300.894 | 0.000 | 2347.855 |
| beyond | 17:55:39.293 | 300.894 | 0.000 | 2347.862 |
| pypredict | 17:55:39.745 | 300.878 | 0.027 | 2344.802 |

**Peak**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 18:00:56.636 | 223.597 | 37.990 | 646.603 |
| skyfield | 18:00:56.565 | 223.659 | 37.989 | 646.621 |
| beyond | 18:00:56.637 | 223.596 | 37.991 | 646.603 |
| pypredict | 18:00:56.633 | 223.600 | 37.991 | 646.605 |

**Stop**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 18:06:13.195 | 146.100 | 0.000 | 2340.659 |
| skyfield | 18:06:13.199 | 146.101 | -0.000 | 2340.667 |
| beyond | 18:06:13.196 | 146.100 | -0.000 | 2340.664 |
| pypredict | 18:06:13.675 | 146.082 | -0.029 | 2343.905 |

### Transit #7

**Start**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 19:34:35.380 | 263.188 | -0.000 | 2345.329 |
| skyfield | 19:34:35.405 | 263.184 | 0.000 | 2345.287 |
| beyond | 19:34:35.379 | 263.188 | 0.000 | 2345.329 |
| pypredict | 19:34:34.284 | 263.366 | -0.029 | 2348.541 |

**Peak**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 19:36:53.668 | 237.558 | 1.986 | 2132.285 |
| skyfield | 19:36:53.720 | 237.548 | 1.985 | 2132.310 |
| beyond | 19:36:53.670 | 237.557 | 1.986 | 2132.284 |
| pypredict | 19:36:53.665 | 237.558 | 1.986 | 2132.286 |

**Stop**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 19:39:11.988 | 211.864 | 0.000 | 2340.435 |
| skyfield | 19:39:12.062 | 211.853 | -0.002 | 2340.666 |
| beyond | 19:39:11.991 | 211.864 | -0.000 | 2340.442 |
| pypredict | 19:39:17.049 | 211.040 | -0.133 | 2355.252 |

### Execution Time (ms)

| Satellite | jspredict | skyfield | beyond | pypredict |
| --- | ---: | ---: | ---: | ---: |
| ISS (ZARYA) | 17.460 | 5.512 | 2701.462 | 2.899 |

## Observations

- **Accuracy:** All four libraries agree closely at peak, where azimuth and
  elevation typically match within ~0.1° and range within ~0.01 km. At peak the
  exact culmination instant is the most sensitive quantity (differences up to
  ~0.1 s) because elevation is nearly flat there, making it depend on each
  library's root-finding method.
- **AOS/LOS resolution:** pypredict resolves the horizon-crossing (start/stop)
  times to whole seconds, so its reported start/stop elevations land slightly
  off 0° (typically ±0.03°, occasionally more on steep passes) and the
  corresponding azimuth/range differ by a few km. The other three libraries
  refine the crossing to the exact 0° elevation.
- **Performance:** pypredict is the fastest (~3 ms) since it is a thin wrapper
  over the compiled `predict` C library, closely followed by skyfield (~6 ms)
  and jspredict (~17 ms). beyond is substantially slower (~2700 ms) because
  `station.visibility` performs a fine-grained stepped propagation with event
  refinement.
- All seven ISS passes over Boulder in the 24 hours following the OMM epoch
  were detected identically by every library.
