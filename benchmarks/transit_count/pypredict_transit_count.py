#!/usr/bin/env python3
"""pypredict batch runner: counts transits for every (satellite, ground station) pair.

NOTE on coordinates: pypredict uses the classic predict convention of NORTH
latitude and WEST-positive longitude, the opposite sign of the east-positive
longitude used everywhere else in this project, so longitude is negated.
"""

import time
from datetime import datetime, timezone
from importlib.metadata import version

import predict
from cpredict import NoTransitException

from common import Progress, emit, keep_complete, load_inputs, parse_args, result_row

LIBRARY_NAME = "pypredict (Python)"

# How far past the end of the window to search, so a pass that ends just after
# the window (horizon to horizon) but whose part above min elevation ends
# inside it is still found.
END_PADDING_S = 15 * 60


def main():
    args = parse_args("Count satellite transits per ground station using pypredict.")
    satellites, stations, start, stop = load_inputs(args)

    # ---- setup (not part of the per-pair timing) ----
    setup_start = time.perf_counter()
    qths = [(s["lat"], -s["lon"], int(s["alt"])) for s in stations]
    tles = {}
    sat_errors = {}
    for sat in satellites:
        if not sat.get("tle_line1") or not sat.get("tle_line2"):
            sat_errors[sat["id"]] = "no TLE lines available (pypredict cannot read OMM JSON)"
        else:
            tles[sat["id"]] = f"{sat['name']}\n{sat['tle_line1']}\n{sat['tle_line2']}"
    start_ts = start.timestamp()
    stop_ts = stop.timestamp()
    setup_ms = (time.perf_counter() - setup_start) * 1000

    # ---- benchmark ----
    results = []
    progress = Progress(len(satellites) * len(stations))
    for sat in satellites:
        for station_index, qth in enumerate(qths):
            progress.tick()
            if sat["id"] in sat_errors:
                results.append(result_row(sat["id"], station_index, 0, error=sat_errors[sat["id"]]))
                continue
            tle = tles[sat["id"]]
            try:
                begin = time.perf_counter()
                try:
                    # predict.transits is a generator that yields horizon-to-horizon
                    # passes by their END time, so consuming it does the work. A
                    # pass can end after the window closes while the portion above
                    # the minimum elevation ends inside it, so search a little past
                    # the end (passes are re-filtered to the window afterwards).
                    # Transit.above() trims each pass to where the satellite is at
                    # or above min elevation, which gives AOS and LOS; a pass that
                    # never reaches it comes back with zero length.
                    found = []
                    for t in predict.transits(tle, qth, ending_after=start_ts,
                                              ending_before=stop_ts + END_PADDING_S):
                        above = t.above(args.min_elevation)
                        if above.end > above.start:
                            found.append((above.start, above.end))
                except NoTransitException:
                    # pypredict raises (rather than yielding nothing) when the orbit
                    # geometry means the satellite can never rise above the horizon
                    # at this location. That is a legitimate "zero transits".
                    found = []
                elapsed_ms = (time.perf_counter() - begin) * 1000

                passes = [(datetime.fromtimestamp(s, timezone.utc), datetime.fromtimestamp(e, timezone.utc))
                          for s, e in found]
                results.append(result_row(sat["id"], station_index, elapsed_ms,
                                          keep_complete(passes, start, stop)))
            except Exception as exc:  # noqa: BLE001
                results.append(result_row(sat["id"], station_index, 0, error=str(exc)))

    emit(LIBRARY_NAME, version("pypredict"), setup_ms, results)


if __name__ == "__main__":
    main()
