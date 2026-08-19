#!/usr/bin/env python3
"""Orbit propagator comparison harness.

Runs the three benchmark scripts in ./benchmarks (jspredict, skyfield, beyond),
gathers their JSON results, matches up transits that correspond to the same
physical pass, and renders a rich comparison table per transit so the
per-library start/peak/stop calculations can be compared side by side.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

# Each benchmark, with the base command used to run it. The OMM file path and
# the --json flag are appended at runtime.
BENCHMARKS = [
    {"key": "jspredict", "cmd": ["npx", "tsx", "benchmarks/jspredict_benchmark.ts"]},
    {"key": "skyfield", "cmd": ["uv", "run", "python", "benchmarks/skyfield_benchmark.py"]},
    {"key": "beyond", "cmd": ["uv", "run", "python", "benchmarks/beyond_benchmark.py"]},
]

# Default observer location (Boulder, Colorado) used when --observer is omitted.
# lat/lon in degrees, alt in meters.
DEFAULT_OBSERVER = {"lat": 40.0150, "lon": -105.2705, "alt": 1655}

# The benchmarks propagate for this many hours starting from the OMM epoch.
PROPAGATION_HOURS = 24
# Minimum elevation used for AOS/LOS (horizon crossing).
MIN_ELEVATION_DEG = 0.0

# Two transits from different libraries are considered the same pass if their
# peak times fall within this many seconds of each other.
MATCH_TOLERANCE_SECONDS = 120.0

console = Console()


def parse_time(value: str) -> datetime:
    """Parse an ISO-8601 timestamp (with trailing Z) into an aware datetime."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def run_benchmark(bench: Dict, omm_file: str, observer_json: str) -> Optional[Dict]:
    """Run a benchmark script for the given OMM file and return its parsed JSON.

    stderr is discarded so that library warnings (e.g. beyond's frame
    registration notice) don't corrupt the JSON emitted on stdout.
    """
    console.print(f"[cyan]Running {bench['key']}...[/cyan]")
    cmd = [*bench["cmd"], omm_file, "--observer", observer_json, "--json"]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        console.print(f"[red]{bench['key']} failed:[/red] {exc.stderr.strip()}")
        return None

    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        console.print(f"[red]{bench['key']} produced invalid JSON:[/red] {exc}")
        return None


def gather_results(omm_file: str, observer_json: str) -> Dict[str, Dict]:
    """Run all benchmarks for the given OMM file, keyed by benchmark name."""
    results = {}
    for bench in BENCHMARKS:
        payload = run_benchmark(bench, omm_file, observer_json)
        if payload is not None:
            results[bench["key"]] = payload
    return results


def index_satellites(results: Dict[str, Dict]) -> Dict[str, Dict]:
    """Group results by satellite.

    Returns a mapping of satellite key -> {
        "name": str,
        "libraries": {lib_key: satellite_result_dict}
    }
    keyed by NORAD catalog id (falling back to name).
    """
    satellites: Dict[str, Dict] = {}
    for lib_key, payload in results.items():
        for sat in payload.get("satellites", []):
            sat_key = str(sat.get("norad_cat_id") or sat.get("name"))
            entry = satellites.setdefault(
                sat_key, {"name": sat.get("name"), "libraries": {}}
            )
            entry["libraries"][lib_key] = sat
    return satellites


def match_transits(libraries: Dict[str, Dict], lib_order: List[str]) -> List[Dict]:
    """Align transits across libraries by peak-time proximity.

    Uses the library with the most transits as the reference set, then attaches
    the closest-in-time transit from every other library (within tolerance).
    Returns a list of matched transits, each a dict of {lib_key: transit_or_None}.
    """
    present = [k for k in lib_order if k in libraries and libraries[k]["transits"]]
    if not present:
        return []

    # Reference = library that found the most transits for this satellite.
    ref_key = max(present, key=lambda k: len(libraries[k]["transits"]))
    ref_transits = libraries[ref_key]["transits"]

    # Track which transits from each other library have been consumed.
    used: Dict[str, set] = {k: set() for k in present}

    matched = []
    for ref_transit in ref_transits:
        ref_peak = parse_time(ref_transit["peak"]["time"])
        row: Dict[str, Optional[Dict]] = {ref_key: ref_transit}
        used[ref_key].add(id(ref_transit))

        for lib_key in present:
            if lib_key == ref_key:
                continue
            best = None
            best_delta = None
            for idx, cand in enumerate(libraries[lib_key]["transits"]):
                if idx in used[lib_key]:
                    continue
                delta = abs((parse_time(cand["peak"]["time"]) - ref_peak).total_seconds())
                if best_delta is None or delta < best_delta:
                    best_delta = delta
                    best = (idx, cand)
            if best is not None and best_delta <= MATCH_TOLERANCE_SECONDS:
                used[lib_key].add(best[0])
                row[lib_key] = best[1]
            else:
                row[lib_key] = None

        matched.append(row)

    return matched


def fmt_time(iso: str) -> str:
    """Format an ISO timestamp to HH:MM:SS.mmm for compact display."""
    dt = parse_time(iso)
    return dt.strftime("%H:%M:%S.") + f"{dt.microsecond // 1000:03d}"


def render_transit_table(
    sat_name: str,
    transit_index: int,
    row: Dict[str, Optional[Dict]],
    lib_order: List[str],
) -> Table:
    """Build a rich table comparing one matched transit across libraries."""
    present_libs = [k for k in lib_order if k in row]

    table = Table(
        title=f"{sat_name}  \u2014  Transit #{transit_index}",
        box=box.ROUNDED,
        title_style="bold magenta",
        header_style="bold cyan",
    )
    table.add_column("Event", style="bold", no_wrap=True)
    table.add_column("Parameter", no_wrap=True)
    for lib_key in present_libs:
        table.add_column(lib_key, justify="right")

    for event in ("start", "peak", "stop"):
        event_label = event.capitalize()
        params = [
            ("Time (UTC)", lambda p: fmt_time(p["time"])),
            ("Azimuth (\u00b0)", lambda p: f"{p['azimuth']:.3f}"),
            ("Elevation (\u00b0)", lambda p: f"{p['elevation']:.3f}"),
            ("Range (km)", lambda p: f"{p['range']:.3f}"),
        ]
        for i, (param_label, accessor) in enumerate(params):
            cells = []
            for lib_key in present_libs:
                transit = row[lib_key]
                if transit is None:
                    cells.append("[dim]—[/dim]")
                else:
                    cells.append(accessor(transit[event]))
            # Only label the event on its first parameter row.
            first_col = event_label if i == 0 else ""
            table.add_row(first_col, param_label, *cells)
        table.add_section()

    return table


def render_timing_table(results: Dict[str, Dict], lib_order: List[str]) -> Table:
    """Build a table summarizing per-library execution time by satellite."""
    table = Table(
        title="Execution Time (ms)",
        box=box.ROUNDED,
        title_style="bold green",
        header_style="bold cyan",
    )
    table.add_column("Satellite", style="bold")
    present_libs = [k for k in lib_order if k in results]
    for lib_key in present_libs:
        table.add_column(lib_key, justify="right")

    # Collect all satellite names in order of first appearance.
    sat_names: List[str] = []
    for lib_key in present_libs:
        for sat in results[lib_key]["satellites"]:
            if sat["name"] not in sat_names:
                sat_names.append(sat["name"])

    for name in sat_names:
        cells = []
        for lib_key in present_libs:
            match = next(
                (s for s in results[lib_key]["satellites"] if s["name"] == name),
                None,
            )
            cells.append(f"{match['execution_time_ms']:.3f}" if match else "[dim]—[/dim]")
        table.add_row(name, *cells)

    return table


def render_input_parameters(omm_file: str, omm_data: Dict, observer: Dict) -> Panel:
    """Build a panel summarizing the shared inputs used by all three benchmarks."""
    epoch_str = omm_data.get("EPOCH", "")
    start = parse_time(epoch_str) if epoch_str else None
    stop = start + timedelta(hours=PROPAGATION_HOURS) if start else None

    def fmt(dt: Optional[datetime]) -> str:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z" if dt else "[dim]—[/dim]"

    table = Table(box=box.SIMPLE, show_header=False, pad_edge=False)
    table.add_column("Parameter", style="bold cyan", no_wrap=True)
    table.add_column("Value")

    table.add_row("OMM file", omm_file)
    table.add_row("Satellite", str(omm_data.get("OBJECT_NAME", "—")))
    table.add_row("NORAD Cat ID", str(omm_data.get("NORAD_CAT_ID", "—")))
    table.add_row("OMM epoch", epoch_str or "—")
    table.add_section()
    table.add_row("Observer latitude", f"{observer['lat']:.4f}\u00b0")
    table.add_row("Observer longitude", f"{observer['lon']:.4f}\u00b0")
    table.add_row("Observer altitude", f"{observer['alt']} m")
    table.add_section()
    table.add_row("Start time (UTC)", fmt(start))
    table.add_row("Stop time (UTC)", fmt(stop))
    table.add_row("Duration", f"{PROPAGATION_HOURS} hours")
    table.add_row("Min elevation (AOS/LOS)", f"{MIN_ELEVATION_DEG:.1f}\u00b0")

    return Panel(
        table,
        title="[bold]Benchmark Input Parameters[/bold]",
        border_style="yellow",
        box=box.ROUNDED,
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Run the jspredict, skyfield, and beyond benchmarks against a single "
            "OMM file and render a side-by-side comparison of their transit "
            "calculations for a given observer location."
        )
    )
    parser.add_argument("omm_file", help="Path to the OMM JSON file to run the benchmarks on")
    parser.add_argument(
        "--observer",
        default=json.dumps(DEFAULT_OBSERVER),
        help=(
            "Observer location as a JSON string with lat/lon (degrees) and alt "
            '(meters), e.g. \'{"lat":40.015,"lon":-105.2705,"alt":1655}\'. '
            "Defaults to Boulder, CO."
        ),
    )
    args = parser.parse_args()

    if not os.path.isfile(args.omm_file):
        console.print(f"[red]OMM file not found:[/red] {args.omm_file}")
        sys.exit(1)

    try:
        observer_obj = json.loads(args.observer)
        observer = {
            "lat": float(observer_obj["lat"]),
            "lon": float(observer_obj["lon"]),
            "alt": float(observer_obj["alt"]),
        }
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        console.print(f"[red]Invalid --observer JSON:[/red] {exc}")
        sys.exit(1)

    # Re-serialize to a canonical JSON string to pass to the benchmarks.
    observer_json = json.dumps(observer)

    with open(args.omm_file) as f:
        omm_data = json.load(f)

    console.print()
    console.print(render_input_parameters(args.omm_file, omm_data, observer))
    console.print()

    results = gather_results(args.omm_file, observer_json)
    if not results:
        console.print("[red]No benchmark results were gathered.[/red]")
        return

    lib_order = [b["key"] for b in BENCHMARKS]
    console.print()

    satellites = index_satellites(results)
    for sat_key, entry in satellites.items():
        matched = match_transits(entry["libraries"], lib_order)
        for idx, row in enumerate(matched, start=1):
            console.print(render_transit_table(entry["name"], idx, row, lib_order))
            console.print()

    console.print(render_timing_table(results, lib_order))


if __name__ == "__main__":
    main()
