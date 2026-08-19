#!/usr/bin/env python3
"""
Skyfield-based satellite transit calculator
Computes transits over Boulder, Colorado for satellites from OMM files
"""

import argparse
import json
import time
from datetime import datetime, timedelta
from typing import List, Dict, Tuple
from skyfield.api import EarthSatellite, load, wgs84, utc
from skyfield.timelib import Time
import numpy as np

LIBRARY_NAME = "skyfield (Python)"

class TransitPoint:
    def __init__(self, time: Time, azimuth: float, elevation: float, range_km: float):
        self.time = time
        self.azimuth = azimuth
        self.elevation = elevation
        self.range = range_km

class Transit:
    def __init__(self, start: TransitPoint, peak: TransitPoint, stop: TransitPoint):
        self.start = start
        self.peak = peak
        self.stop = stop

def parse_omm(file_path: str) -> Dict:
    """Parse OMM JSON file"""
    with open(file_path, 'r') as f:
        return json.load(f)

def iso_millis(t: Time) -> str:
    """Format a skyfield Time as an ISO-8601 UTC string with millisecond
    precision. utc_iso() truncates to whole seconds, so build it from the
    underlying Python datetime instead."""
    dt = t.utc_datetime()
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f"{dt.microsecond // 1000:03d}Z"

def _look_angles(sat: EarthSatellite, observer, t: Time) -> TransitPoint:
    """Compute az/el/range look angles at a given time."""
    topocentric = (sat - observer).at(t)
    alt, az, dist = topocentric.altaz()
    return TransitPoint(
        time=t,
        azimuth=az.degrees,
        elevation=alt.degrees,
        range_km=dist.km,
    )


def find_transits(sat: EarthSatellite, observer, start_time: Time, end_time: Time,
                  min_elevation: float = 0.0) -> List[Transit]:
    """Find all transits using skyfield's built-in find_events.

    find_events returns rise (0), culminate (1), and set (2) events refined
    to the horizon crossing, so start/stop land exactly on min_elevation.
    """
    transits = []

    times, events = sat.find_events(
        observer, start_time, end_time, altitude_degrees=min_elevation
    )

    # Group events into passes. A valid pass is rise -> culminate -> set.
    current = {}
    for t, event in zip(times, events):
        if event == 0:  # rise
            current = {'start': _look_angles(sat, observer, t)}
        elif event == 1:  # culminate
            if 'start' in current:
                current['peak'] = _look_angles(sat, observer, t)
        elif event == 2:  # set
            if 'start' in current and 'peak' in current:
                current['stop'] = _look_angles(sat, observer, t)
                transits.append(
                    Transit(current['start'], current['peak'], current['stop'])
                )
            current = {}

    return transits

def compute_transits(omm_data: Dict, lat: float, lon: float, alt: float) -> Tuple[List[Transit], float]:
    """Compute transits for a satellite from OMM data at the given observer location."""
    start_time_compute = time.perf_counter()
    
    # Create timescale and observer
    ts = load.timescale()
    observer = wgs84.latlon(lat, lon, alt)
    
    # Build the satellite directly from OMM fields (native OMM support)
    satellite = EarthSatellite.from_omm(ts, omm_data)
    
    # Use the satellite's own epoch as the start of the 24-hour window
    start_time = satellite.epoch
    end_time = ts.tt_jd(start_time.tt + 1.0)  # +24 hours (1 Julian day)
    
    # Find transits
    transits = find_transits(satellite, observer, start_time, end_time, min_elevation=0.0)
    
    end_time_compute = time.perf_counter()
    execution_time = (end_time_compute - start_time_compute) * 1000  # Convert to ms
    
    return transits, execution_time

def print_transit_table(satellite_name: str, transits: List[Transit], execution_time: float,
                        lat: float, lon: float, alt: float):
    """Print formatted transit table"""
    print(f"\n{'=' * 80}")
    print(f"Satellite: {satellite_name}")
    print(f"Library: skyfield (Python)")
    print(f"Observer: ({lat}°, {lon}°, {alt}m)")
    print(f"Execution Time: {execution_time:.3f} ms")
    print(f"{'=' * 80}")
    
    if not transits:
        print('No transits found in the 24-hour period.')
        return
    
    print(f"\nTotal Transits: {len(transits)}\n")
    
    for idx, transit in enumerate(transits, 1):
        print(f"Transit #{idx}:")
        print(f"  Start: {iso_millis(transit.start.time)} - Az={transit.start.azimuth:.3f}° El={transit.start.elevation:.3f}° Range={transit.start.range:.3f}km")
        print(f"  Peak:  {iso_millis(transit.peak.time)} - Az={transit.peak.azimuth:.3f}° El={transit.peak.elevation:.3f}° Range={transit.peak.range:.3f}km")
        print(f"  Stop:  {iso_millis(transit.stop.time)} - Az={transit.stop.azimuth:.3f}° El={transit.stop.elevation:.3f}° Range={transit.stop.range:.3f}km")
        print()

def _point_to_dict(point: TransitPoint) -> Dict:
    """Serialize a TransitPoint to a plain dict."""
    return {
        "time": iso_millis(point.time),
        "azimuth": point.azimuth,
        "elevation": point.elevation,
        "range": point.range,
    }


def build_results(omm_file: str, lat: float, lon: float, alt: float) -> Dict:
    """Compute transits for a single OMM file and return a JSON-serializable dict."""
    omm_data = parse_omm(omm_file)
    transits, execution_time = compute_transits(omm_data, lat, lon, alt)

    satellites = [{
        "name": omm_data['OBJECT_NAME'],
        "norad_cat_id": omm_data.get('NORAD_CAT_ID'),
        "execution_time_ms": execution_time,
        "transits": [
            {
                "start": _point_to_dict(t.start),
                "peak": _point_to_dict(t.peak),
                "stop": _point_to_dict(t.stop),
            }
            for t in transits
        ],
    }]

    return {"library": LIBRARY_NAME, "satellites": satellites}


def parse_observer(raw: str) -> Tuple[float, float, float]:
    """Parse an observer JSON string of the form {"lat":..,"lon":..,"alt":..}."""
    data = json.loads(raw)
    return float(data["lat"]), float(data["lon"]), float(data["alt"])


def main():
    parser = argparse.ArgumentParser(
        description="Compute satellite transits from an OMM file using skyfield."
    )
    parser.add_argument("omm_file", help="Path to the OMM JSON file to process")
    parser.add_argument(
        "--observer",
        required=True,
        help='Observer location as a JSON string, e.g. \'{"lat":40.015,"lon":-105.2705,"alt":1655}\'',
    )
    parser.add_argument("--json", action="store_true", help="Emit results as JSON")
    args = parser.parse_args()

    lat, lon, alt = parse_observer(args.observer)

    if args.json:
        print(json.dumps(build_results(args.omm_file, lat, lon, alt)))
        return

    omm_data = parse_omm(args.omm_file)
    transits, execution_time = compute_transits(omm_data, lat, lon, alt)
    print_transit_table(omm_data['OBJECT_NAME'], transits, execution_time, lat, lon, alt)

if __name__ == "__main__":
    main()
