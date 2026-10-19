#!/usr/bin/env python3
"""Transit-count benchmark.

Given a directory of TLE/OMM files and a JSON list of ground stations (see
resources/groundstations.json), this runs every propagator library over every
(satellite, ground station) pair for a 24 hour window starting at the current
date/time and reports:

  1. how long each library takes to find the transits, and
  2. whether the libraries agree on the number of transits per ground station.

All libraries receive exactly the same normalized inputs (a satellite manifest,
a station list and one shared window start time). Each runner lives in
benchmarks/transit_count/ and times only the transit search for each pair; the
cost of building satellite/observer objects is reported separately as "setup".

A "transit" is the span between AOS and LOS, where AOS/LOS are the times the
satellite crosses the minimum elevation (default 5 deg, see --min-elevation),
and both must fall inside the window. Passes already in progress at the start of the window, or still in
progress at the end, are not counted by any library.
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

RUNNER_DIR = os.path.join("benchmarks", "transit_count")

# Each runner, with the base command used to launch it. The input file paths,
# window start and window length are appended at runtime.
BENCHMARKS = [
    {"key": "jspredict", "cmd": ["npx", "--yes", "tsx", os.path.join(RUNNER_DIR, "jspredict_transit_count.ts")]},
    {"key": "skyfield", "cmd": ["uv", "run", "python", os.path.join(RUNNER_DIR, "skyfield_transit_count.py")]},
    {"key": "pypredict", "cmd": ["uv", "run", "python", os.path.join(RUNNER_DIR, "pypredict_transit_count.py")]},
]

TLE_EXTENSIONS = {".tle", ".txt", ".3le", ".2le"}
OMM_EXTENSIONS = {".json"}

console = Console()


# --------------------------------------------------------------------------- #
# Input loading
# --------------------------------------------------------------------------- #

def parse_tle_text(text: str, fallback_name: str) -> List[Dict]:
    """Parse 2LE/3LE text (one or many satellites) into manifest entries."""
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    sats: List[Dict] = []
    name: Optional[str] = None
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("1 ") and i + 1 < len(lines) and lines[i + 1].startswith("2 "):
            line2 = lines[i + 1]
            sats.append({
                "name": name or fallback_name,
                "norad_cat_id": line[2:7].strip(),
                "tle_line1": line,
                "tle_line2": line2,
                "omm": None,
            })
            name = None
            i += 2
        else:
            # Name line; "0 NAME" is the Space-Track 3LE convention.
            name = line[2:].strip() if line.startswith("0 ") else line.strip()
            i += 1
    return sats


def parse_omm_json(data, fallback_name: str) -> List[Dict]:
    """Parse an OMM JSON document (one object or a list of objects)."""
    records = data if isinstance(data, list) else [data]
    sats = []
    for rec in records:
        if not isinstance(rec, dict) or "MEAN_MOTION" not in rec or "EPOCH" not in rec:
            raise ValueError("not an OMM record (missing MEAN_MOTION/EPOCH)")
        sats.append({
            "name": str(rec.get("OBJECT_NAME") or fallback_name),
            "norad_cat_id": str(rec.get("NORAD_CAT_ID", "")),
            "tle_line1": rec.get("TLE_LINE1"),
            "tle_line2": rec.get("TLE_LINE2"),
            "omm": rec,
        })
    return sats


def load_satellites(directory: str) -> Tuple[List[Dict], List[str]]:
    """Load every TLE/OMM file in ``directory`` (non-recursive).

    Returns (satellites, warnings). Each satellite gets a sequential ``id`` and
    a ``source_file`` entry.
    """
    satellites: List[Dict] = []
    warnings: List[str] = []
    for filename in sorted(os.listdir(directory)):
        path = os.path.join(directory, filename)
        stem, ext = os.path.splitext(filename)
        ext = ext.lower()
        if not os.path.isfile(path) or filename.startswith("."):
            continue
        if ext not in TLE_EXTENSIONS | OMM_EXTENSIONS:
            warnings.append(f"Skipping {filename}: unsupported extension")
            continue
        try:
            with open(path) as f:
                if ext in OMM_EXTENSIONS:
                    found = parse_omm_json(json.load(f), stem)
                else:
                    found = parse_tle_text(f.read(), stem)
        except (OSError, ValueError) as exc:  # json.JSONDecodeError is a ValueError
            warnings.append(f"Skipping {filename}: {exc}")
            continue
        if not found:
            warnings.append(f"Skipping {filename}: no satellites found")
        for sat in found:
            sat["source_file"] = filename
            sat["format"] = "omm" if sat["omm"] else "tle"
            sat["id"] = len(satellites)
            satellites.append(sat)
    return satellites, warnings


def load_stations(path: str) -> List[Dict]:
    """Load ground stations in the resources/groundstations.json format.

    Each entry is {"name": ..., "location": {"latitude", "longitude", "height"}}
    with latitude/longitude in degrees (east-positive longitude) and height in
    meters. Flat {"lat", "lon", "alt"} entries are accepted too.
    """
    with open(path) as f:
        raw = json.load(f)
    if not isinstance(raw, list):
        raise ValueError("ground station file must contain a JSON list")

    stations = []
    for idx, entry in enumerate(raw):
        try:
            loc = entry.get("location", entry)
            stations.append({
                "name": str(entry.get("name", f"station-{idx}")),
                "lat": float(loc.get("latitude", loc.get("lat"))),
                "lon": float(loc.get("longitude", loc.get("lon"))),
                "alt": float(loc.get("height", loc.get("alt", 0.0))),
            })
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid ground station entry #{idx}: {exc}") from exc
    return stations


# --------------------------------------------------------------------------- #
# Running the libraries
# --------------------------------------------------------------------------- #

PROGRESS_PREFIX = "@@progress "


def run_runner(bench: Dict, sats_path: str, stations_path: str, start_iso: str, hours: float,
               min_elevation: float, on_progress=None) -> Optional[Dict]:
    """Launch one runner and return its parsed JSON output (or None on failure).

    The runner reports progress as ``@@progress <done> <total>`` lines on
    stderr; any other stderr output (library warnings) is only shown if the
    runner fails.
    """
    cmd = [*bench["cmd"], "--satellites", sats_path, "--stations", stations_path,
           "--start", start_iso, "--hours", str(hours),
           "--min-elevation", str(min_elevation)]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except FileNotFoundError as exc:
        console.print(f"[red]{bench['key']} could not be launched:[/red] {exc}")
        return None

    stderr_lines: List[str] = []

    def pump_stderr():
        for line in proc.stderr:
            if line.startswith(PROGRESS_PREFIX):
                try:
                    done, total = (int(x) for x in line[len(PROGRESS_PREFIX):].split())
                except ValueError:
                    continue
                if on_progress:
                    on_progress(done, total)
            else:
                stderr_lines.append(line)

    thread = threading.Thread(target=pump_stderr, daemon=True)
    thread.start()
    stdout = proc.stdout.read()
    proc.wait()
    thread.join()

    if proc.returncode != 0:
        detail = "".join(stderr_lines).strip() or stdout.strip()
        console.print(f"[red]{bench['key']} failed:[/red] {detail}")
        return None
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        console.print(f"[red]{bench['key']} produced invalid JSON:[/red] {exc}")
        return None


# --------------------------------------------------------------------------- #
# Analysis
# --------------------------------------------------------------------------- #

def index_results(runs: Dict[str, Dict]) -> Dict[str, Dict[Tuple[int, int], Dict]]:
    """{lib: {(satellite_id, station_index): row}}"""
    return {
        lib: {(r["satellite"], r["station"]): r for r in run["results"]}
        for lib, run in runs.items()
    }


def pair_counts(indexed, lib_order: List[str], sat_id: int, station_idx: int) -> Dict[str, Optional[int]]:
    return {lib: indexed[lib].get((sat_id, station_idx), {}).get("count") for lib in lib_order}


def summarize_timing(run: Dict) -> Dict:
    rows = run["results"]
    times = [r["time_ms"] for r in rows if r["time_ms"] is not None]
    return {
        "setup_ms": run["setup_ms"],
        "total_ms": sum(times),
        "mean_ms": statistics.fmean(times) if times else None,
        "median_ms": statistics.median(times) if times else None,
        "pairs": len(times),
        "errors": sum(1 for r in rows if r["error"] is not None),
        "transits": sum(r["count"] or 0 for r in rows),
    }


def compare_counts(indexed, lib_order, satellites, stations):
    """Classify every pair as agreeing, disagreeing or incomplete.

    A pair is incomplete when at least one library failed to produce a count
    for it; those pairs are excluded from the agreement statistics.
    """
    per_station = {
        i: {"totals": defaultdict(int), "agree": 0, "mismatch": 0, "incomplete": 0}
        for i in range(len(stations))
    }
    mismatches = []
    for sat in satellites:
        for i in range(len(stations)):
            counts = pair_counts(indexed, lib_order, sat["id"], i)
            info = per_station[i]
            if any(c is None for c in counts.values()):
                info["incomplete"] += 1
                continue
            for lib, c in counts.items():
                info["totals"][lib] += c
            if len(set(counts.values())) == 1:
                info["agree"] += 1
            else:
                info["mismatch"] += 1
                mismatches.append((sat, stations[i], counts))
    return per_station, mismatches


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

def fmt_ms(value: Optional[float]) -> str:
    return "[dim]\u2014[/dim]" if value is None else f"{value:,.2f}"


def render_input_panel(args, satellites, stations, start: datetime, stop: datetime, libs: List[str]) -> Panel:
    n_omm = sum(1 for s in satellites if s["format"] == "omm")
    n_tle = len(satellites) - n_omm
    table = Table(box=box.SIMPLE, show_header=False, pad_edge=False)
    table.add_column("Parameter", style="bold cyan", no_wrap=True)
    table.add_column("Value")
    table.add_row("Satellite directory", args.satellite_dir)
    table.add_row("Satellites", f"{len(satellites)} ({n_tle} TLE, {n_omm} OMM)")
    table.add_row("Ground station file", args.groundstations)
    table.add_row("Ground stations", str(len(stations)))
    table.add_row("Satellite/station pairs", f"{len(satellites) * len(stations):,}")
    table.add_section()
    table.add_row("Start time (UTC)", start.strftime("%Y-%m-%dT%H:%M:%S.") + f"{start.microsecond // 1000:03d}Z")
    table.add_row("Stop time (UTC)", stop.strftime("%Y-%m-%dT%H:%M:%S.") + f"{stop.microsecond // 1000:03d}Z")
    table.add_row("Duration", f"{args.hours:g} hours")
    table.add_row("Min elevation (AOS/LOS)", f"{args.min_elevation:g}\u00b0")
    table.add_row("Libraries", ", ".join(libs))
    return Panel(table, title="[bold]Transit Count Benchmark Inputs[/bold]", border_style="yellow", box=box.ROUNDED)


def render_timing_table(runs, lib_order) -> Table:
    summaries = {lib: summarize_timing(runs[lib]) for lib in lib_order}
    fastest_mean = min((s["mean_ms"] for s in summaries.values() if s["mean_ms"]), default=None)

    table = Table(title="Execution Time", box=box.ROUNDED, title_style="bold green", header_style="bold cyan")
    table.add_column("Library", style="bold")
    table.add_column("Version")
    table.add_column("Total (ms)", justify="right")
    table.add_column("Mean/pair (ms)", justify="right")
    table.add_column("Median/pair (ms)", justify="right")
    table.add_column("Slowdown", justify="right")
    table.add_column("Setup (ms)", justify="right")
    table.add_column("Transits", justify="right")
    table.add_column("Errors", justify="right")
    for lib in lib_order:
        s = summaries[lib]
        relative = f"{s['mean_ms'] / fastest_mean:.2f}x" if s["mean_ms"] and fastest_mean else "[dim]\u2014[/dim]"
        errors = f"[red]{s['errors']}[/red]" if s["errors"] else "0"
        table.add_row(lib, str(runs[lib].get("version", "")), fmt_ms(s["total_ms"]), fmt_ms(s["mean_ms"]),
                      fmt_ms(s["median_ms"]), relative, fmt_ms(s["setup_ms"]),
                      f"{s['transits']:,}", errors)
    return table


def render_station_count_table(per_station, stations, lib_order) -> Table:
    table = Table(title="Transit Counts per Ground Station (all satellites)", box=box.ROUNDED,
                  title_style="bold magenta", header_style="bold cyan")
    table.add_column("Ground station", style="bold")
    for lib in lib_order:
        table.add_column(lib, justify="right")
    table.add_column("Pairs agreeing", justify="right")
    table.add_column("Match", justify="center")
    for i, station in enumerate(stations):
        info = per_station[i]
        compared = info["agree"] + info["mismatch"]
        if compared == 0:
            status = "[yellow]?[/yellow]"
        elif info["mismatch"]:
            status = "[red]\u2717[/red]"
        else:
            status = "[green]\u2713[/green]"
        agree = f"{info['agree']}/{compared}"
        if info["incomplete"]:
            agree += f" [dim](+{info['incomplete']} incomplete)[/dim]"
        table.add_row(station["name"], *(f"{info['totals'][lib]:,}" for lib in lib_order), agree, status)
    return table


def render_station_time_table(runs, indexed, satellites, stations, lib_order) -> Table:
    table = Table(title="Execution Time per Ground Station (ms, all satellites)", box=box.ROUNDED,
                  title_style="bold green", header_style="bold cyan")
    table.add_column("Ground station", style="bold")
    for lib in lib_order:
        table.add_column(lib, justify="right")
    for i, station in enumerate(stations):
        cells = []
        for lib in lib_order:
            times = [indexed[lib][(s["id"], i)]["time_ms"] for s in satellites
                     if (s["id"], i) in indexed[lib] and indexed[lib][(s["id"], i)]["time_ms"] is not None]
            cells.append(fmt_ms(sum(times)) if times else fmt_ms(None))
        table.add_row(station["name"], *cells)
    return table


def render_mismatch_table(mismatches, lib_order, limit: int) -> Table:
    table = Table(title=f"Transit Count Disagreements ({len(mismatches)} pairs)", box=box.ROUNDED,
                  title_style="bold red", header_style="bold cyan")
    table.add_column("Satellite", style="bold")
    table.add_column("Ground station", style="bold")
    for lib in lib_order:
        table.add_column(lib, justify="right")
    for sat, station, counts in mismatches[:limit]:
        majority = statistics.mode(counts.values())
        cells = [f"[red]{c}[/red]" if c != majority else str(c) for c in counts.values()]
        table.add_row(sat["name"], station["name"], *cells)
    if len(mismatches) > limit:
        table.caption = f"Showing {limit} of {len(mismatches)}; use --max-mismatch-rows or --json-output for all."
    return table


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark how long each orbit propagator library takes to count satellite "
            "transits over 24 hours for every satellite in a directory of TLE/OMM files and "
            "every ground station in a JSON file, and check that the libraries agree on the counts."
        )
    )
    parser.add_argument("satellite_dir", help="Directory of TLE (.tle/.txt/.3le) and/or OMM (.json) files")
    parser.add_argument("groundstations", help="JSON list of ground stations (format of resources/groundstations.json)")
    parser.add_argument("--hours", type=float, default=24.0, help="Window length in hours (default: 24)")
    parser.add_argument(
        "--min-elevation", type=float, default=5.0,
        help="Minimum elevation in degrees. AOS and LOS are the times the satellite crosses it, "
             "and a transit is the span between them (default: 5)",
    )
    parser.add_argument(
        "--libraries", default=",".join(b["key"] for b in BENCHMARKS),
        help="Comma-separated libraries to run (default: all)",
    )
    parser.add_argument("--max-mismatch-rows", type=int, default=50,
                        help="Maximum number of disagreeing pairs to list (default: 50)")
    parser.add_argument("--json-output", metavar="PATH",
                        help="Also write the full per-pair results and comparison to this JSON file")
    args = parser.parse_args()

    if not os.path.isdir(args.satellite_dir):
        console.print(f"[red]Satellite directory not found:[/red] {args.satellite_dir}")
        sys.exit(1)
    if not os.path.isfile(args.groundstations):
        console.print(f"[red]Ground station file not found:[/red] {args.groundstations}")
        sys.exit(1)

    wanted = [k.strip() for k in args.libraries.split(",") if k.strip()]
    unknown = [k for k in wanted if k not in {b["key"] for b in BENCHMARKS}]
    if unknown:
        console.print(f"[red]Unknown libraries:[/red] {', '.join(unknown)}")
        sys.exit(1)
    benchmarks = [b for b in BENCHMARKS if b["key"] in wanted]

    satellites, warnings = load_satellites(args.satellite_dir)
    for w in warnings:
        console.print(f"[yellow]{w}[/yellow]")
    if not satellites:
        console.print(f"[red]No TLE/OMM satellites found in {args.satellite_dir}[/red]")
        sys.exit(1)
    try:
        stations = load_stations(args.groundstations)
    except (OSError, ValueError) as exc:
        console.print(f"[red]Invalid ground station file:[/red] {exc}")
        sys.exit(1)
    if not stations:
        console.print("[red]No ground stations found[/red]")
        sys.exit(1)

    # One shared window for every library: now -> now + hours.
    start = datetime.now(timezone.utc)
    stop = start + timedelta(hours=args.hours)
    start_iso = start.strftime("%Y-%m-%dT%H:%M:%S.") + f"{start.microsecond // 1000:03d}Z"

    console.print()
    console.print(render_input_panel(args, satellites, stations, start, stop, [b["key"] for b in benchmarks]))
    console.print()

    runs: Dict[str, Dict] = {}
    with tempfile.TemporaryDirectory() as tmp:
        sats_path = os.path.join(tmp, "satellites.json")
        stations_path = os.path.join(tmp, "stations.json")
        with open(sats_path, "w") as f:
            json.dump(satellites, f)
        with open(stations_path, "w") as f:
            json.dump(stations, f)

        # Run sequentially so the libraries don't compete for CPU.
        for bench in benchmarks:
            with console.status(f"[cyan]Running {bench['key']}...[/cyan]") as status:
                def on_progress(done, total, key=bench["key"], status=status):
                    status.update(f"[cyan]Running {key}... {done:,}/{total:,} pairs[/cyan]")

                run = run_runner(bench, sats_path, stations_path, start_iso, args.hours,
                                  args.min_elevation, on_progress)
            if run is not None:
                runs[bench["key"]] = run
                console.print(f"[green]\u2713[/green] {bench['key']} finished")

    if not runs:
        console.print("[red]No benchmark results were gathered.[/red]")
        sys.exit(1)

    lib_order = [b["key"] for b in benchmarks if b["key"] in runs]
    indexed = index_results(runs)
    per_station, mismatches = compare_counts(indexed, lib_order, satellites, stations)

    console.print()
    console.print(render_timing_table(runs, lib_order))
    console.print()
    console.print(render_station_count_table(per_station, stations, lib_order))
    console.print()
    console.print(render_station_time_table(runs, indexed, satellites, stations, lib_order))
    console.print()

    agree = sum(s["agree"] for s in per_station.values())
    incomplete = sum(s["incomplete"] for s in per_station.values())
    compared = agree + len(mismatches)
    if len(lib_order) < 2:
        console.print("[yellow]Only one library produced results; nothing to compare.[/yellow]")
    elif mismatches:
        console.print(render_mismatch_table(mismatches, lib_order, args.max_mismatch_rows))
        console.print()
    if len(lib_order) >= 2:
        colour = "red" if mismatches else "green"
        console.print(
            f"[{colour}]{agree:,} of {compared:,} satellite/station pairs have identical transit counts "
            f"across {', '.join(lib_order)}.[/{colour}]"
        )
    if incomplete:
        console.print(f"[yellow]{incomplete:,} pairs were excluded from the comparison because at least one "
                      f"library returned an error.[/yellow]")

    if args.json_output:
        output = {
            "window": {"start": start_iso, "hours": args.hours, "min_elevation_deg": args.min_elevation},
            "satellites": [{k: v for k, v in s.items() if k != "omm"} for s in satellites],
            "stations": stations,
            "libraries": runs,
            "comparison": {
                "pairs_agreeing": agree,
                "pairs_disagreeing": len(mismatches),
                "pairs_incomplete": incomplete,
                "disagreements": [
                    {"satellite": s["name"], "station": g["name"], "counts": c} for s, g, c in mismatches
                ],
            },
        }
        with open(args.json_output, "w") as f:
            json.dump(output, f, indent=2)
        console.print(f"Full results written to {args.json_output}")


if __name__ == "__main__":
    main()
