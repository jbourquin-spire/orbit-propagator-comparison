# orbit-propagator-comparison

Compares various orbit propagation libraries for performance and accuracy.

The tool runs three SGP4-based transit predictors against the same OMM
(Orbit Mean-Elements Message) and observer location, then compares the
start/peak/stop look angles they compute for each pass:

- **jspredict** (TypeScript) — `@nsat/jspredict`
- **skyfield** (Python) — `EarthSatellite.from_omm` + `find_events`
- **beyond** (Python) — `station.visibility`

## Usage

```bash
# Default observer (Boulder, CO)
uv run python main.py resources/iss.omm.json

# Custom observer (JSON: lat/lon in degrees, alt in meters)
uv run python main.py resources/iss.omm.json --observer '{"lat": 40.015, "lon": -105.2705, "alt": 1655}'
```

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

**Peak**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 09:54:39.353 | 131.206 | 17.796 | 1091.804 |
| skyfield | 09:54:39.230 | 131.258 | 17.797 | 1091.780 |
| beyond | 09:54:39.315 | 131.222 | 17.796 | 1091.805 |

**Stop**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 09:59:30.257 | 67.065 | -0.000 | 2341.913 |
| skyfield | 09:59:30.282 | 67.063 | -0.001 | 2342.043 |
| beyond | 09:59:30.256 | 67.065 | -0.000 | 2341.909 |

### Transit #2

**Start**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 11:25:49.751 | 244.625 | 0.000 | 2333.131 |
| skyfield | 11:25:49.760 | 244.626 | 0.000 | 2333.098 |
| beyond | 11:25:49.750 | 244.625 | 0.000 | 2333.137 |

**Peak**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 11:31:10.295 | 327.156 | 48.371 | 542.760 |
| skyfield | 11:31:10.198 | 327.038 | 48.369 | 542.771 |
| beyond | 11:31:10.294 | 327.155 | 48.371 | 542.761 |

**Stop**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 11:36:32.734 | 49.787 | 0.000 | 2345.547 |
| skyfield | 11:36:32.750 | 49.788 | -0.001 | 2345.630 |
| beyond | 11:36:32.735 | 49.787 | -0.000 | 2345.553 |

### Transit #3

**Start**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 13:03:50.787 | 284.749 | -0.000 | 2340.324 |
| skyfield | 13:03:50.796 | 284.750 | 0.000 | 2340.302 |
| beyond | 13:03:50.787 | 284.749 | 0.000 | 2340.322 |

**Peak**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 13:08:34.271 | 346.123 | 14.253 | 1250.657 |
| skyfield | 13:08:34.181 | 346.090 | 14.253 | 1250.663 |
| beyond | 13:08:34.270 | 346.122 | 14.253 | 1250.657 |

**Stop**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 13:13:18.658 | 47.492 | 0.000 | 2347.504 |
| skyfield | 13:13:18.673 | 47.493 | -0.001 | 2347.570 |
| beyond | 13:13:18.659 | 47.492 | -0.000 | 2347.510 |

### Transit #4

**Start**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 14:41:54.874 | 309.198 | 0.000 | 2345.227 |
| skyfield | 14:41:54.886 | 309.199 | 0.000 | 2345.186 |
| beyond | 14:41:54.873 | 309.198 | 0.000 | 2345.232 |

**Peak**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 14:46:28.147 | 6.885 | 11.919 | 1373.523 |
| skyfield | 14:46:28.219 | 6.907 | 11.919 | 1373.519 |
| beyond | 14:46:28.148 | 6.886 | 11.919 | 1373.523 |

**Stop**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 14:51:01.588 | 64.531 | -0.000 | 2347.848 |
| skyfield | 14:51:01.596 | 64.531 | -0.000 | 2347.866 |
| beyond | 14:51:01.587 | 64.531 | -0.000 | 2347.845 |

### Transit #5

**Start**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 16:18:54.078 | 312.717 | 0.000 | 2347.368 |
| skyfield | 16:18:54.087 | 312.717 | 0.000 | 2347.329 |
| beyond | 16:18:54.077 | 312.717 | 0.000 | 2347.371 |

**Peak**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 16:24:06.528 | 26.680 | 27.486 | 820.505 |
| skyfield | 16:24:06.604 | 26.722 | 27.487 | 820.493 |
| beyond | 16:24:06.524 | 26.678 | 27.486 | 820.506 |

**Stop**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 16:29:18.456 | 100.541 | -0.000 | 2345.103 |
| skyfield | 16:29:18.463 | 100.542 | -0.000 | 2345.117 |
| beyond | 16:29:18.456 | 100.541 | -0.000 | 2345.105 |

### Transit #6

**Start**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 17:55:39.294 | 300.894 | 0.000 | 2347.857 |
| skyfield | 17:55:39.298 | 300.894 | 0.000 | 2347.855 |
| beyond | 17:55:39.293 | 300.894 | 0.000 | 2347.862 |

**Peak**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 18:00:56.636 | 223.597 | 37.990 | 646.603 |
| skyfield | 18:00:56.565 | 223.659 | 37.989 | 646.621 |
| beyond | 18:00:56.637 | 223.596 | 37.991 | 646.603 |

**Stop**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 18:06:13.195 | 146.100 | 0.000 | 2340.659 |
| skyfield | 18:06:13.199 | 146.101 | -0.000 | 2340.667 |
| beyond | 18:06:13.196 | 146.100 | -0.000 | 2340.664 |

### Transit #7

**Start**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 19:34:35.380 | 263.188 | -0.000 | 2345.329 |
| skyfield | 19:34:35.405 | 263.184 | 0.000 | 2345.287 |
| beyond | 19:34:35.379 | 263.188 | 0.000 | 2345.329 |

**Peak**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 19:36:53.668 | 237.558 | 1.986 | 2132.285 |
| skyfield | 19:36:53.720 | 237.548 | 1.985 | 2132.310 |
| beyond | 19:36:53.670 | 237.557 | 1.986 | 2132.284 |

**Stop**

| Library | Time (UTC) | Azimuth (°) | Elevation (°) | Range (km) |
| --- | --- | ---: | ---: | ---: |
| jspredict | 19:39:11.988 | 211.864 | 0.000 | 2340.435 |
| skyfield | 19:39:12.062 | 211.853 | -0.002 | 2340.666 |
| beyond | 19:39:11.991 | 211.864 | -0.000 | 2340.442 |

### Execution Time (ms)

| Satellite | jspredict | skyfield | beyond |
| --- | ---: | ---: | ---: |
| ISS (ZARYA) | 17.645 | 6.938 | 3001.832 |

## Observations

- **Accuracy:** All three libraries agree closely. Azimuth and elevation
  typically match within ~0.1°, and range within ~0.1 km. The largest
  discrepancies appear at peak time (up to ~0.1 s) because elevation is nearly
  flat near culmination, making the exact peak instant sensitive to each
  library's root-finding method.
- **Performance:** skyfield is the fastest (~7 ms), followed by jspredict
  (~18 ms). beyond is substantially slower (~3000 ms) because
  `station.visibility` performs a fine-grained stepped propagation with event
  refinement.
- All seven ISS passes over Boulder in the 24 hours following the OMM epoch
  were detected identically by every library.
