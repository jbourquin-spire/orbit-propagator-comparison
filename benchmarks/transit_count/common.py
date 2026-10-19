"""Shared helpers for the batch transit-count benchmark runners.

Each runner (skyfield, pypredict) is launched by
``transit_count_benchmark.py`` with the same arguments:

    --satellites <manifest.json>   normalized satellite list
    --stations   <stations.json>   normalized ground station list
    --start      <ISO-8601 UTC>    start of the search window
    --hours      <float>           length of the search window
    --min-elevation <float>        elevation (deg) that defines AOS and LOS

and must print a single JSON document to stdout (see ``emit``).

Progress: runners call ``Progress.tick()`` once per pair.

Timing contract: ``time_ms`` covers only the transit search for one
(satellite, ground station) pair. Building satellite/observer objects happens
once up front and is reported separately as ``setup_ms``.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

DEFAULT_MIN_ELEVATION_DEG = 5.0


def parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 timestamp (trailing Z allowed) into an aware UTC datetime."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_millis(dt: datetime) -> str:
    """Format a datetime as an ISO-8601 UTC string with millisecond precision."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_args(description: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--satellites", required=True, help="Path to the normalized satellite manifest JSON")
    parser.add_argument("--stations", required=True, help="Path to the normalized ground station JSON")
    parser.add_argument("--start", required=True, help="Window start, ISO-8601 UTC")
    parser.add_argument("--hours", type=float, default=24.0, help="Window length in hours (default: 24)")
    parser.add_argument("--min-elevation", type=float, default=DEFAULT_MIN_ELEVATION_DEG,
                        help=f"Minimum elevation in degrees; AOS/LOS are where the satellite crosses it "
                             f"(default: {DEFAULT_MIN_ELEVATION_DEG:g})")
    return parser.parse_args()


def load_inputs(args: argparse.Namespace) -> Tuple[List[Dict], List[Dict], datetime, datetime]:
    """Load the manifest/stations and compute the (start, stop) window."""
    with open(args.satellites) as f:
        satellites = json.load(f)
    with open(args.stations) as f:
        stations = json.load(f)
    start = parse_iso(args.start)
    stop = start + timedelta(hours=args.hours)
    return satellites, stations, start, stop


def result_row(satellite_id: int, station_index: int, time_ms: float,
               transits: List[Tuple[datetime, datetime]] = None, error: str = None) -> Dict:
    """Build one per-pair result row. ``transits`` is a list of (start, stop) datetimes."""
    if error is not None:
        return {"satellite": satellite_id, "station": station_index,
                "count": None, "time_ms": None, "transits": [], "error": error}
    return {
        "satellite": satellite_id,
        "station": station_index,
        "count": len(transits),
        "time_ms": time_ms,
        "transits": [{"start": iso_millis(s), "stop": iso_millis(e)} for s, e in transits],
        "error": None,
    }


def keep_complete(passes: List[Tuple[datetime, datetime]], start: datetime, stop: datetime):
    """Keep only passes whose AOS and LOS both fall inside [start, stop].

    A pass here is already the span between AOS and LOS, i.e. the satellite
    crossing the minimum elevation on the way up and on the way down.

    Libraries disagree on how to report a pass that is already in progress at
    the start of the window or still in progress at the end, so every runner
    applies this same definition of a countable transit.
    """
    return [(s, e) for s, e in passes if s >= start and e <= stop]


def emit(library: str, version: str, setup_ms: float, results: List[Dict]) -> None:
    json.dump({"library": library, "version": version, "setup_ms": setup_ms, "results": results}, sys.stdout)
    sys.stdout.write("\n")


class Progress:
    """Throttled progress reporting on stderr for the orchestrator's status line.

    Emits ``@@progress <done> <total>`` lines; anything else on stderr is
    treated by the orchestrator as a library warning.
    """

    def __init__(self, total: int, interval_s: float = 0.5):
        self.total = total
        self.done = 0
        self.interval_s = interval_s
        self._last = 0.0

    def tick(self) -> None:
        self.done += 1
        now = time.monotonic()
        if now - self._last >= self.interval_s:
            self._last = now
            sys.stderr.write(f"@@progress {self.done} {self.total}\n")
            sys.stderr.flush()
