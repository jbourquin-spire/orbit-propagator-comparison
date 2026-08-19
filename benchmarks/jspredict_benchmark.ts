import { satelliteTransits, AngularUnits, type OrbitMeanElementsMessage } from '@nsat/jspredict';
import { DateTime } from 'luxon';
import { readFileSync } from 'fs';

interface Observer {
  lat: number; // degrees
  lon: number; // degrees
  alt: number; // meters
}

interface OMMData extends OrbitMeanElementsMessage {
  EPOCH: string;
  TLE_LINE1: string;
  TLE_LINE2: string;
  OBJECT_NAME: string;
}

interface TransitPoint {
  time: string;
  azimuth: number;
  elevation: number;
  range: number;
}

interface TransitResult {
  start: TransitPoint;
  peak: TransitPoint;
  stop: TransitPoint;
}

function parseOMM(filePath: string): OMMData {
  const content = readFileSync(filePath, 'utf-8');
  return JSON.parse(content);
}

async function computeTransits(ommData: OMMData, observer: Observer): Promise<TransitResult[]> {
  // Create observer position. jspredict's geodeticAngularUnits defaults to
  // Degrees, so latitude/longitude must be supplied in degrees (not radians).
  const observerPosition = {
    geo: {
      latitude: observer.lat, // degrees
      longitude: observer.lon, // degrees
      height: observer.alt / 1000 // km
    }
  };
  
  const startTime = DateTime.fromISO(ommData.EPOCH, {zone: 'utc'});
  const endTime = startTime.plus({days: 1})
  
  // Get transits - use degrees for angles
  const transits = satelliteTransits(
    ommData,
    startTime,
    endTime,
    observerPosition,
    0, // 0 degrees minimum elevation
    {
      azimuthAngularUnits: AngularUnits.Degrees,
      elevationAngularUnits: AngularUnits.Degrees
    }
  );
  
  const results: TransitResult[] = [];
  
  for (const transit of transits) {
    results.push({
      start: {
        time: transit.aos.epoch as string,
        azimuth: transit.aos.azimuth as number,
        elevation: transit.aos.elevation as number,
        range: transit.aos.slantRange
      },
      peak: {
        time: transit.peak.epoch as string,
        azimuth: transit.peak.azimuth as number,
        elevation: transit.peak.elevation as number,
        range: transit.peak.slantRange
      },
      stop: {
        time: transit.los.epoch as string,
        azimuth: transit.los.azimuth as number,
        elevation: transit.los.elevation as number,
        range: transit.los.slantRange
      }
    });
  }
  
  return results;
}

function formatNumber(num: number): string {
  return num.toFixed(3);
}

function printTransitTable(satelliteName: string, transits: TransitResult[], executionTime: number, observer: Observer) {
  console.log(`\n${'='.repeat(80)}`);
  console.log(`Satellite: ${satelliteName}`);
  console.log(`Library: jspredict (TypeScript)`);
  console.log(`Observer: (${observer.lat}°, ${observer.lon}°, ${observer.alt}m)`);
  console.log(`Execution Time: ${executionTime.toFixed(3)} ms`);
  console.log(`${'='.repeat(80)}`);
  
  if (transits.length === 0) {
    console.log('No transits found in the 24-hour period.');
    return;
  }
  
  console.log(`\nTotal Transits: ${transits.length}\n`);
  
  transits.forEach((transit, index) => {
    console.log(`Transit #${index + 1}:`);
    console.log(`  Start: ${transit.start.time} - Az=${formatNumber(transit.start.azimuth)}° El=${formatNumber(transit.start.elevation)}° Range=${formatNumber(transit.start.range)}km`);
    console.log(`  Peak:  ${transit.peak.time} - Az=${formatNumber(transit.peak.azimuth)}° El=${formatNumber(transit.peak.elevation)}° Range=${formatNumber(transit.peak.range)}km`);
    console.log(`  Stop:  ${transit.stop.time} - Az=${formatNumber(transit.stop.azimuth)}° El=${formatNumber(transit.stop.elevation)}° Range=${formatNumber(transit.stop.range)}km`);
    console.log();
  });
}

async function main() {
  const args = process.argv.slice(2);
  const jsonMode = args.includes('--json');

  // --observer accepts a JSON string, either as `--observer <json>` or
  // `--observer=<json>`.
  let observerRaw: string | undefined;
  const obsIdx = args.indexOf('--observer');
  if (obsIdx !== -1) {
    observerRaw = args[obsIdx + 1];
  } else {
    const eqArg = args.find(a => a.startsWith('--observer='));
    if (eqArg) observerRaw = eqArg.slice('--observer='.length);
  }

  const positional = args.filter((a, i) => !a.startsWith('--') && args[i - 1] !== '--observer');
  const ommFile = positional[0];

  if (!ommFile) {
    console.error('Usage: jspredict_benchmark.ts <omm_file> --observer \'{"lat":..,"lon":..,"alt":..}\' [--json]');
    process.exit(1);
  }

  if (!observerRaw) {
    console.error('Missing required --observer <json> argument');
    process.exit(1);
  }

  let observer: Observer;
  try {
    const parsed = JSON.parse(observerRaw);
    observer = { lat: Number(parsed.lat), lon: Number(parsed.lon), alt: Number(parsed.alt) };
    if ([observer.lat, observer.lon, observer.alt].some(v => Number.isNaN(v))) {
      throw new Error('observer must include numeric lat, lon, and alt');
    }
  } catch (err) {
    console.error(`Invalid --observer JSON: ${(err as Error).message}`);
    process.exit(1);
  }

  const ommData = parseOMM(ommFile);

  const startTime = performance.now();
  const transits = await computeTransits(ommData, observer);
  const endTime = performance.now();
  const executionTime = endTime - startTime;

  if (jsonMode) {
    const satellites = [{
      name: ommData.OBJECT_NAME,
      norad_cat_id: (ommData as any).NORAD_CAT_ID,
      execution_time_ms: executionTime,
      transits: transits.map(t => ({
        start: { time: t.start.time, azimuth: t.start.azimuth, elevation: t.start.elevation, range: t.start.range },
        peak: { time: t.peak.time, azimuth: t.peak.azimuth, elevation: t.peak.elevation, range: t.peak.range },
        stop: { time: t.stop.time, azimuth: t.stop.azimuth, elevation: t.stop.elevation, range: t.stop.range },
      })),
    }];
    console.log(JSON.stringify({ library: 'jspredict (TypeScript)', satellites }));
  } else {
    printTransitTable(ommData.OBJECT_NAME, transits, executionTime, observer);
  }
}

main().catch(console.error);

