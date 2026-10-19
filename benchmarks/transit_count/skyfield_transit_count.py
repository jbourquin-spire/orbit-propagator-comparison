#!/usr/bin/env python3
"""Skyfield batch runner: counts transits for every (satellite, ground station) pair."""

import time
from importlib.metadata import version
from pathlib import Path

from skyfield.api import EarthSatellite, Loader, wgs84

from common import Progress, emit, keep_complete, load_inputs, parse_args, result_row

LIBRARY_NAME = "skyfield (Python)"
SKYFIELD_LOADER = Loader(str(Path.home() / ".skyfield"))


def main():
    args = parse_args("Count satellite transits per ground station using skyfield.")
    satellites, stations, start, stop = load_inputs(args)

    # ---- setup (not part of the per-pair timing) ----
    setup_start = time.perf_counter()
    ts = SKYFIELD_LOADER.timescale()
    t0 = ts.from_datetime(start)
    t1 = ts.from_datetime(stop)
    observers = [wgs84.latlon(s["lat"], s["lon"], s["alt"]) for s in stations]

    sat_objects = {}
    sat_errors = {}
    for sat in satellites:
        try:
            if sat.get("omm"):
                sat_objects[sat["id"]] = EarthSatellite.from_omm(ts, sat["omm"])
            else:
                sat_objects[sat["id"]] = EarthSatellite(sat["tle_line1"], sat["tle_line2"], sat["name"], ts)
        except Exception as exc:  # noqa: BLE001 - report any parse failure per satellite
            sat_errors[sat["id"]] = f"setup failed: {exc}"
    setup_ms = (time.perf_counter() - setup_start) * 1000

    # ---- benchmark ----
    results = []
    progress = Progress(len(satellites) * len(stations))
    for sat in satellites:
        for station_index, observer in enumerate(observers):
            progress.tick()
            if sat["id"] in sat_errors:
                results.append(result_row(sat["id"], station_index, 0, error=sat_errors[sat["id"]]))
                continue
            satellite = sat_objects[sat["id"]]
            try:
                begin = time.perf_counter()
                times, events = satellite.find_events(observer, t0, t1, altitude_degrees=args.min_elevation)
                elapsed_ms = (time.perf_counter() - begin) * 1000

                # Group events into passes: rise (0) ... set (2). With a non-zero
                # altitude_degrees, rise/set are the crossings of that elevation,
                # i.e. the pass's AOS and LOS.
                passes = []
                rise = None
                for t, event in zip(times, events):
                    if event == 0:
                        rise = t.utc_datetime()
                    elif event == 2:
                        if rise is not None:
                            passes.append((rise, t.utc_datetime()))
                        rise = None
                results.append(result_row(sat["id"], station_index, elapsed_ms,
                                          keep_complete(passes, start, stop)))
            except Exception as exc:  # noqa: BLE001
                results.append(result_row(sat["id"], station_index, 0, error=str(exc)))

    emit(LIBRARY_NAME, version("skyfield"), setup_ms, results)


if __name__ == "__main__":
    main()
