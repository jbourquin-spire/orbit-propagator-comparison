#!/usr/bin/env python3
"""
pypredict-based satellite transit calculator
Computes transits over an observer location for satellites from OMM files.

NOTE on coordinates: pypredict (a wrapper around the `predict` C library) uses
the classic predict convention of NORTH latitude and WEST longitude, where west
longitudes are POSITIVE. This is the opposite sign of the traditional
east-positive convention used by the other benchmarks and by this tool's
--observer argument. We therefore negate the incoming (east-positive) longitude
before handing it to pypredict.
"""

import argparse
import json
import time
from datetime import datetime, timezone
from typing import List, Dict, Tuple

import predict

LIBRARY_NAME = "pypredict (Python)"


class TransitPoint:
    def __init__(self, epoch: float, azimuth: float, elevation: float, range_km: float):
        self.epoch = epoch  # unix timestamp (seconds)
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


def _point_from_observation(obs: Dict) -> TransitPoint:
    """Build a TransitPoint from a pypredict observation dict.

    pypredict returns azimuth/elevation in degrees, slant_range in km, and the
    observation epoch as a unix timestamp.
    """
    return TransitPoint(
        epoch=obs["epoch"],
        azimuth=obs["azimuth"],
        elevation=obs["elevation"],
        range_km=obs["slant_range"],
    )


def find_transits(tle: str, qth: Tuple[float, float, int],
                  start_ts: float, end_ts: float) -> List[Transit]:
    """Find all transits in [start_ts, end_ts] using pypredict.

    predict.transits() yields passes based on their END time, so a pass is
    included when its end falls within the window.
    """
    transits = []

    for transit in predict.transits(tle, qth, ending_after=start_ts, ending_before=end_ts):
        # start/end are unix timestamps; peak() returns a full observation dict.
        start_obs = predict.observe(tle, qth, at=transit.start)
        peak_obs = transit.peak()
        stop_obs = predict.observe(tle, qth, at=transit.end)

        transits.append(Transit(
            _point_from_observation(start_obs),
            _point_from_observation(peak_obs),
            _point_from_observation(stop_obs),
        ))

    return transits


def compute_transits(omm_data: Dict, lat: float, lon: float, alt: float) -> Tuple[List[Transit], float]:
    """Compute transits for a satellite from OMM data at the given observer location.

    lat/lon are east-positive degrees (this tool's convention); pypredict wants
    west-positive longitude, so we negate lon. alt is in meters.
    """
    start_time_compute = time.perf_counter()

    # pypredict qth: (latitude_north_deg, longitude_WEST_deg, altitude_meters)
    qth = (lat, -lon, int(alt))

    # pypredict wants a 3-line TLE (name + two element lines).
    tle = f"{omm_data['OBJECT_NAME']}\n{omm_data['TLE_LINE1']}\n{omm_data['TLE_LINE2']}"

    # Use the OMM epoch as the start of the 24-hour window.
    epoch_dt = datetime.fromisoformat(omm_data['EPOCH'].replace('Z', '+00:00'))
    if epoch_dt.tzinfo is None:
        epoch_dt = epoch_dt.replace(tzinfo=timezone.utc)
    start_ts = epoch_dt.timestamp()
    end_ts = start_ts + 24 * 60 * 60  # +24 hours

    transits = find_transits(tle, qth, start_ts, end_ts)

    end_time_compute = time.perf_counter()
    execution_time = (end_time_compute - start_time_compute) * 1000  # ms

    return transits, execution_time


def compute_beta_angle_deg(omm_data: Dict, lat: float, lon: float, alt: float) -> float:
    """Compute the satellite beta angle at the OMM epoch."""
    tle = f"{omm_data['OBJECT_NAME']}\n{omm_data['TLE_LINE1']}\n{omm_data['TLE_LINE2']}"
    epoch_dt = datetime.fromisoformat(omm_data['EPOCH'].replace('Z', '+00:00'))
    if epoch_dt.tzinfo is None:
        epoch_dt = epoch_dt.replace(tzinfo=timezone.utc)
    qth = (lat, -lon, int(alt))
    observation = predict.observe(tle, qth, at=epoch_dt.timestamp())
    return float(observation['beta_angle'])


def _iso_millis(epoch: float) -> str:
    """Format a unix timestamp as an ISO-8601 UTC string with millisecond precision."""
    dt = datetime.fromtimestamp(epoch, timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f"{dt.microsecond // 1000:03d}Z"


def print_transit_table(satellite_name: str, transits: List[Transit], execution_time: float,
                        lat: float, lon: float, alt: float, beta_angle_deg: float):
    """Print formatted transit table"""
    print(f"\n{'=' * 80}")
    print(f"Satellite: {satellite_name}")
    print(f"Library: pypredict (Python)")
    print(f"Observer: ({lat}°, {lon}°, {alt}m)")
    print(f"Beta Angle at Epoch: {beta_angle_deg:.6f}°")
    print(f"Execution Time: {execution_time:.3f} ms")
    print(f"{'=' * 80}")

    if not transits:
        print('No transits found in the 24-hour period.')
        return

    print(f"\nTotal Transits: {len(transits)}\n")

    for idx, transit in enumerate(transits, 1):
        print(f"Transit #{idx}:")
        print(f"  Start: {_iso_millis(transit.start.epoch)} - Az={transit.start.azimuth:.3f}° El={transit.start.elevation:.3f}° Range={transit.start.range:.3f}km")
        print(f"  Peak:  {_iso_millis(transit.peak.epoch)} - Az={transit.peak.azimuth:.3f}° El={transit.peak.elevation:.3f}° Range={transit.peak.range:.3f}km")
        print(f"  Stop:  {_iso_millis(transit.stop.epoch)} - Az={transit.stop.azimuth:.3f}° El={transit.stop.elevation:.3f}° Range={transit.stop.range:.3f}km")
        print()


def _point_to_dict(point: TransitPoint) -> Dict:
    """Serialize a TransitPoint to a plain dict."""
    return {
        "time": _iso_millis(point.epoch),
        "azimuth": point.azimuth,
        "elevation": point.elevation,
        "range": point.range,
    }


def build_results(omm_file: str, lat: float, lon: float, alt: float) -> Dict:
    """Compute transits for a single OMM file and return a JSON-serializable dict."""
    omm_data = parse_omm(omm_file)
    transits, execution_time = compute_transits(omm_data, lat, lon, alt)
    beta_angle_deg = compute_beta_angle_deg(omm_data, lat, lon, alt)

    satellites = [{
        "name": omm_data['OBJECT_NAME'],
        "norad_cat_id": omm_data.get('NORAD_CAT_ID'),
        "beta_angle_deg": beta_angle_deg,
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
        description="Compute satellite transits from an OMM file using pypredict."
    )
    parser.add_argument("omm_file", help="Path to the OMM JSON file to process")
    parser.add_argument(
        "--observer",
        required=True,
        help='Observer location as a JSON string (east-positive longitude), '
             'e.g. \'{"lat":40.015,"lon":-105.2705,"alt":1655}\'',
    )
    parser.add_argument("--json", action="store_true", help="Emit results as JSON")
    args = parser.parse_args()

    lat, lon, alt = parse_observer(args.observer)

    if args.json:
        print(json.dumps(build_results(args.omm_file, lat, lon, alt)))
        return

    omm_data = parse_omm(args.omm_file)
    try:
        transits, execution_time = compute_transits(omm_data, lat, lon, alt)
        beta_angle_deg = compute_beta_angle_deg(omm_data, lat, lon, alt)
        print_transit_table(
            omm_data['OBJECT_NAME'], transits, execution_time, lat, lon, alt, beta_angle_deg
        )
    except Exception as e:
        print(f"\nError processing {args.omm_file}: {e}")


if __name__ == "__main__":
    main()
