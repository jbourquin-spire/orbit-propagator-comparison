/**
 * jspredict batch runner: counts transits for every (satellite, ground station) pair.
 *
 * Usage: jspredict_transit_count.ts --satellites <manifest.json> --stations <stations.json>
 *                                   --start <ISO-8601 UTC> [--hours 24] [--min-elevation 5]
 *
 * Prints a single JSON document to stdout. See common.py for the contract.
 * `time_ms` covers only the satelliteTransits() call for one pair.
 */
import { satelliteTransits, AngularUnits, type OrbitMeanElementsMessage } from '@nsat/jspredict';
import { DateTime } from 'luxon';
import { readFileSync } from 'fs';

interface Station {
  name: string;
  lat: number; // degrees, east-positive longitude
  lon: number;
  alt: number; // meters
}

interface ManifestSatellite {
  id: number;
  name: string;
  tle_line1?: string | null;
  tle_line2?: string | null;
  omm?: OrbitMeanElementsMessage | null;
}

interface ResultRow {
  satellite: number;
  station: number;
  count: number | null;
  time_ms: number | null;
  transits: { start: string; stop: string }[];
  error: string | null;
}

// AOS/LOS must be within this many degrees of the minimum elevation to count as a complete pass.
const ELEVATION_TOLERANCE_DEG = 0.1;

function argValue(args: string[], flag: string): string | undefined {
  const idx = args.indexOf(flag);
  if (idx !== -1) return args[idx + 1];
  const eq = args.find(a => a.startsWith(`${flag}=`));
  return eq ? eq.slice(flag.length + 1) : undefined;
}

function isoMillis(dt: DateTime): string {
  return dt.toUTC().toFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'");
}

function main() {
  const args = process.argv.slice(2);
  const satellitesPath = argValue(args, '--satellites');
  const stationsPath = argValue(args, '--stations');
  const startRaw = argValue(args, '--start');
  const hours = Number(argValue(args, '--hours') ?? '24');
  const minElevation = Number(argValue(args, '--min-elevation') ?? '5');

  if (!satellitesPath || !stationsPath || !startRaw) {
    console.error('Usage: jspredict_transit_count.ts --satellites <file> --stations <file> --start <ISO> [--hours 24]');
    process.exit(1);
  }

  const satellites: ManifestSatellite[] = JSON.parse(readFileSync(satellitesPath, 'utf-8'));
  const stations: Station[] = JSON.parse(readFileSync(stationsPath, 'utf-8'));
  const start = DateTime.fromISO(startRaw, { zone: 'utc' });
  const stop = start.plus({ hours });

  // ---- setup (not part of the per-pair timing) ----
  const setupBegin = performance.now();
  // jspredict's geodeticAngularUnits defaults to Degrees; height is in km.
  const observers = stations.map(s => ({
    geo: { latitude: s.lat, longitude: s.lon, height: s.alt / 1000 },
  }));
  const elements = new Map<number, string | OrbitMeanElementsMessage>();
  for (const sat of satellites) {
    if (sat.omm) {
      elements.set(sat.id, sat.omm);
    } else {
      elements.set(sat.id, `${sat.name}\n${sat.tle_line1}\n${sat.tle_line2}`);
    }
  }
  const setupMs = performance.now() - setupBegin;

  // ---- benchmark ----
  const results: ResultRow[] = [];
  const total = satellites.length * stations.length;
  let done = 0;
  let lastProgress = 0;
  for (const sat of satellites) {
    const satElements = elements.get(sat.id)!;
    observers.forEach((observer, stationIndex) => {
      done++;
      const now = performance.now();
      if (now - lastProgress >= 500) {
        lastProgress = now;
        process.stderr.write(`@@progress ${done} ${total}\n`);
      }
      try {
        const begin = performance.now();
        const transits = satelliteTransits(satElements, start, stop, observer, minElevation, {
          azimuthAngularUnits: AngularUnits.Degrees,
          elevationAngularUnits: AngularUnits.Degrees,
        });
        const elapsedMs = performance.now() - begin;

        // A transit is the span from AOS to LOS: the crossings of the minimum
        // elevation (jspredict's `aos`/`los`; `start`/`stop` are the 0 degree
        // horizon crossings). jspredict reports a pass that is already in
        // progress at the window start (or still in progress at the end) with
        // an AOS/LOS taken from the window edge, so only count passes whose AOS
        // and LOS are both on the minimum elevation.
        const passes = transits
          .filter(t => Math.abs((t.aos.elevation as number) - minElevation) <= ELEVATION_TOLERANCE_DEG
            && Math.abs((t.los.elevation as number) - minElevation) <= ELEVATION_TOLERANCE_DEG)
          .map(t => ({ start: DateTime.fromISO(t.aos.epoch as string, { zone: 'utc' }), stop: DateTime.fromISO(t.los.epoch as string, { zone: 'utc' }) }))
          // jspredict clips an in-progress pass to the window edge, so a pass whose
          // AOS/LOS lands exactly on the edge is not a real crossing; require strictly inside.
          .filter(p => p.start.toMillis() > start.toMillis() && p.stop.toMillis() < stop.toMillis());

        results.push({
          satellite: sat.id,
          station: stationIndex,
          count: passes.length,
          time_ms: elapsedMs,
          transits: passes.map(p => ({ start: isoMillis(p.start), stop: isoMillis(p.stop) })),
          error: null,
        });
      } catch (err) {
        results.push({
          satellite: sat.id,
          station: stationIndex,
          count: null,
          time_ms: null,
          transits: [],
          error: (err as Error).message,
        });
      }
    });
  }

  const pkg = JSON.parse(readFileSync(new URL('../../node_modules/@nsat/jspredict/package.json', import.meta.url), 'utf-8'));
  console.log(JSON.stringify({ library: 'jspredict (TypeScript)', version: pkg.version, setup_ms: setupMs, results }));
}

main();
