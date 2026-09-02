#!/usr/bin/env python3
"""
Beyond-based satellite transit calculator
Computes transits over Boulder, Colorado for satellites from OMM files
"""

import argparse
import json
import time
from datetime import datetime, timedelta
from typing import List, Dict, Tuple
import numpy as np
from beyond.dates import Date
from beyond.env.solarsystem import get_body
from beyond.io.tle import Tle
from beyond.frames import create_station
from beyond.orbits import Orbit

LIBRARY_NAME = "beyond (Python)"

class TransitPoint:
    def __init__(self, time: Date, azimuth: float, elevation: float, range_km: float):
        self.time = time
        self.azimuth = azimuth
        self.elevation = elevation
        self.range = range_km

class Transit:
    def __init__(self, start: TransitPoint, peak: TransitPoint, stop: TransitPoint):
        self.start = start
        self.peak = peak
        self.stop = stop


def _beta_angle_deg(position_km, velocity_km_s, sun_position_km) -> float:
    """Compute beta angle from inertial position, velocity, and Sun vectors."""
    h = np.cross(position_km, velocity_km_s)
    value = np.dot(
        h / np.linalg.norm(h),
        sun_position_km / np.linalg.norm(sun_position_km),
    )
    return float(np.degrees(np.arcsin(np.clip(value, -1.0, 1.0))))

def parse_omm(file_path: str) -> Dict:
    """Parse OMM JSON file"""
    with open(file_path, 'r') as f:
        return json.load(f)

def find_transits(orb: Orbit, station, start_date: Date, end_date: Date) -> List[Transit]:
    """Find all transits using the station.visibility method"""
    transits = []
    
    # Use the station.visibility method with events enabled
    # This will yield AOS, MAX, and LOS events for each pass
    current_pass = {}
    
    for point in station.visibility(orb, start=start_date, stop=end_date, 
                                     step=timedelta(seconds=10), events=True):
        # Check if this point has an event
        if hasattr(point, 'event') and point.event is not None:
            event_str = str(point.event)
            
            # Extract azimuth, elevation, and range (already in station frame
            # and spherical form). Beyond's theta is measured counterclockwise,
            # so negate it to get the standard clockwise-from-North azimuth.
            azimuth = (-np.degrees(point.theta)) % 360
            elevation = np.degrees(point.phi)
            range_km = point.r / 1000.0  # Convert from meters to km
            
            if 'AOS' in event_str:
                # Start of a new pass
                current_pass = {
                    'start': TransitPoint(point.date, azimuth, elevation, range_km)
                }
            elif 'MAX' in event_str:
                # Peak of the pass
                if 'start' in current_pass:
                    current_pass['peak'] = TransitPoint(point.date, azimuth, elevation, range_km)
            elif 'LOS' in event_str:
                # End of the pass
                if 'start' in current_pass and 'peak' in current_pass:
                    current_pass['stop'] = TransitPoint(point.date, azimuth, elevation, range_km)
                    # Create transit object
                    transits.append(Transit(
                        current_pass['start'],
                        current_pass['peak'],
                        current_pass['stop']
                    ))
                # Reset for next pass
                current_pass = {}
    
    return transits

def compute_transits(omm_data: Dict, lat: float, lon: float, alt: float) -> Tuple[List[Transit], float]:
    """Compute transits for a satellite from OMM data at the given observer location."""
    start_time_compute = time.perf_counter()
    
    # Create station with unique name to avoid registration conflicts.
    # create_station expects (latitude_deg, longitude_deg, altitude_meters).
    station_name = f"Observer_{omm_data.get('NORAD_CAT_ID', 'station')}"
    station = create_station(
        station_name,
        (lat, lon, alt)
    )
    
    # Parse TLE (beyond's CCSDS reader expects XML/KVN, not OMM JSON, so we
    # use the TLE_LINE fields embedded in the OMM record)
    line1 = omm_data['TLE_LINE1']
    line2 = omm_data['TLE_LINE2']
    tle = Tle(f"{omm_data['OBJECT_NAME']}\n{line1}\n{line2}")
    orb = tle.orbit()
    
    # Use the orbit's own epoch as the start of the 24-hour window
    start_date = orb.date
    end_date = start_date + timedelta(hours=24)
    
    # Find transits using the station visibility method
    transits = find_transits(orb, station, start_date, end_date)
    
    end_time_compute = time.perf_counter()
    execution_time = (end_time_compute - start_time_compute) * 1000  # Convert to ms
    
    return transits, execution_time


def compute_beta_angle_deg(omm_data: Dict) -> float:
    """Compute the satellite beta angle at the OMM epoch."""
    tle = Tle(f"{omm_data['OBJECT_NAME']}\n{omm_data['TLE_LINE1']}\n{omm_data['TLE_LINE2']}")
    orbit0 = tle.orbit()
    orbit = orbit0.propagate(orbit0.date)
    sun = get_body('Sun').propagate(orbit.date).copy(frame='TEME')
    return _beta_angle_deg(
        np.array(orbit[:3]) / 1000.0,
        np.array(orbit[3:]) / 1000.0,
        np.array(sun[:3]) / 1000.0,
    )

def print_transit_table(satellite_name: str, transits: List[Transit], execution_time: float,
                        lat: float, lon: float, alt: float, beta_angle_deg: float):
    """Print formatted transit table"""
    print(f"\n{'=' * 80}")
    print(f"Satellite: {satellite_name}")
    print(f"Library: beyond (Python)")
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
        print(f"  Start: {transit.start.time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]}Z - Az={transit.start.azimuth:.3f}° El={transit.start.elevation:.3f}° Range={transit.start.range:.3f}km")
        print(f"  Peak:  {transit.peak.time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]}Z - Az={transit.peak.azimuth:.3f}° El={transit.peak.elevation:.3f}° Range={transit.peak.range:.3f}km")
        print(f"  Stop:  {transit.stop.time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]}Z - Az={transit.stop.azimuth:.3f}° El={transit.stop.elevation:.3f}° Range={transit.stop.range:.3f}km")
        print()

def _point_to_dict(point: TransitPoint) -> Dict:
    """Serialize a TransitPoint to a plain dict."""
    return {
        "time": point.time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + "Z",
        "azimuth": point.azimuth,
        "elevation": point.elevation,
        "range": point.range,
    }


def build_results(omm_file: str, lat: float, lon: float, alt: float) -> Dict:
    """Compute transits for a single OMM file and return a JSON-serializable dict."""
    omm_data = parse_omm(omm_file)
    transits, execution_time = compute_transits(omm_data, lat, lon, alt)
    beta_angle_deg = compute_beta_angle_deg(omm_data)

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
        description="Compute satellite transits from an OMM file using beyond."
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
    try:
        transits, execution_time = compute_transits(omm_data, lat, lon, alt)
        beta_angle_deg = compute_beta_angle_deg(omm_data)
        print_transit_table(
            omm_data['OBJECT_NAME'], transits, execution_time, lat, lon, alt, beta_angle_deg
        )
    except Exception as e:
        print(f"\nError processing {args.omm_file}: {e}")

if __name__ == "__main__":
    main()
