// MOCK — daily readiness scores for the Trends page chart (30 days ending 2026-05-27)
const MOCK_READINESS = [
  { date: '2026-04-28', readiness_score: 71 },
  { date: '2026-04-29', readiness_score: 68 },
  { date: '2026-04-30', readiness_score: 55 },
  { date: '2026-05-01', readiness_score: 72 },
  { date: '2026-05-02', readiness_score: 78 },
  { date: '2026-05-03', readiness_score: null },
  { date: '2026-05-04', readiness_score: 66 },
  { date: '2026-05-05', readiness_score: 62 },
  { date: '2026-05-06', readiness_score: 58 },
  { date: '2026-05-07', readiness_score: 49 },
  { date: '2026-05-08', readiness_score: 44 },
  { date: '2026-05-09', readiness_score: 38 },
  { date: '2026-05-10', readiness_score: 42 },
  { date: '2026-05-11', readiness_score: null },
  { date: '2026-05-12', readiness_score: 55 },
  { date: '2026-05-13', readiness_score: 63 },
  { date: '2026-05-14', readiness_score: 70 },
  { date: '2026-05-15', readiness_score: 74 },
  { date: '2026-05-16', readiness_score: 76 },
  { date: '2026-05-17', readiness_score: 72 },
  { date: '2026-05-18', readiness_score: 68 },
  { date: '2026-05-19', readiness_score: null },
  { date: '2026-05-20', readiness_score: 73 },
  { date: '2026-05-21', readiness_score: 79 },
  { date: '2026-05-22', readiness_score: 81 },
  { date: '2026-05-23', readiness_score: 75 },
  { date: '2026-05-24', readiness_score: 69 },
  { date: '2026-05-25', readiness_score: 64 },
  { date: '2026-05-26', readiness_score: 70 },
  { date: '2026-05-27', readiness_score: 73 },
];

// MOCK — daily TSS (Training Stress Score) per workout; multiple entries on same date = multiple workouts
const MOCK_TSS = [
  { date: '2026-04-28', tss: 120 },
  { date: '2026-04-29', tss: 145 },
  { date: '2026-04-30', tss:  60 },
  { date: '2026-05-02', tss:  30 },
  { date: '2026-05-03', tss:  85 },
  { date: '2026-05-04', tss: 110 },
  { date: '2026-05-05', tss: 130 },
  { date: '2026-05-06', tss: 160 },
  { date: '2026-05-07', tss:  95 },
  { date: '2026-05-08', tss:  70 },
  { date: '2026-05-10', tss:  25 },
  { date: '2026-05-12', tss:  40 },
  { date: '2026-05-13', tss:  55 },
  { date: '2026-05-14', tss:  45 },
  { date: '2026-05-15', tss:  50 },
  { date: '2026-05-16', tss:  60 },
  { date: '2026-05-17', tss: 140 },
  { date: '2026-05-19', tss:  35 },
  { date: '2026-05-20', tss:  65 },
  { date: '2026-05-21', tss:  90 },
  { date: '2026-05-22', tss:  85 },
  { date: '2026-05-22', tss:  70 }, // double session
  { date: '2026-05-23', tss: 175 },
  { date: '2026-05-24', tss: 120 },
  { date: '2026-05-25', tss:  45 },
  { date: '2026-05-26', tss:  30 },
  { date: '2026-05-27', tss:  55 },
];

// MOCK — 7-day sleep / energy / mood trend (null = no entry that day)
const MOCK_DAILY_TREND = [
  { date: '2026-05-21', sleep_hours: 7.0, energy: 3, mood: 3 },
  { date: '2026-05-22', sleep_hours: 6.5, energy: 2, mood: 3 },
  { date: '2026-05-23', sleep_hours: null, energy: null, mood: null },
  { date: '2026-05-24', sleep_hours: 8.0, energy: 4, mood: 4 },
  { date: '2026-05-25', sleep_hours: 7.5, energy: 4, mood: 5 },
  { date: '2026-05-26', sleep_hours: 6.0, energy: 3, mood: 3 },
  { date: '2026-05-27', sleep_hours: 7.0, energy: 4, mood: 4 },
];

// ── Mock GET /trends/summary aggregation endpoint ─────────────────────────────
//
// mockGetTrendsSummary(params) mirrors the server-side endpoint shape exactly.
// params: { range?: '7d'|'30d'|'90d', from?: 'YYYY-MM-DD', to?: 'YYYY-MM-DD' }
// Throws an Error with .status = 400 for invalid params.

function _fmtD(d) {
  const y = d.getFullYear();
  const mo = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${mo}-${day}`;
}

function _shiftDate(dateStr, n) {
  const d = new Date(dateStr + 'T00:00:00');
  d.setDate(d.getDate() + n);
  return _fmtD(d);
}

function _daysBetween(from, to) {
  return Math.round((new Date(to + 'T00:00:00') - new Date(from + 'T00:00:00')) / 86400000);
}

// 120-day raw metrics indexed by date, covering 2026-01-28 to 2026-05-27.
// ~20% of days are gaps (null) to simulate missing log entries.
const _MOCK_DAILY_RAW = (() => {
  const TODAY = '2026-05-27';
  const map = {};
  for (let i = 0; i < 120; i++) {
    const date = _shiftDate(TODAY, i - 119);
    const gap = (i % 7 === 3) || (i % 13 === 6);
    map[date] = {
      readiness: gap ? null : Math.max(30, Math.min(95, Math.round(62 + 18 * Math.sin(i * 0.14) + (i % 7) * 1.2))),
      hrv:       gap ? null : Math.max(25, Math.min(70, Math.round(44 + 9  * Math.sin(i * 0.11) + (i % 5)))),
      rhr:       gap ? null : Math.max(44, Math.min(74, Math.round(59 - 7  * Math.sin(i * 0.11) - (i % 4)))),
      sleep:         gap ? null : Math.round(Math.max(4.5, Math.min(9.5, 6.9 + 1.1 * Math.sin(i * 0.19))) * 10) / 10,
      sleep_quality: gap ? null : Math.max(1, Math.min(5, Math.round(3 + 1.5 * Math.sin(i * 0.19)))),
      energy:    gap ? null : Math.max(1, Math.min(5, Math.round(3 + 1.5 * Math.sin(i * 0.16)))),
      mood:      gap ? null : Math.max(1, Math.min(5, Math.round(3.2 + 1.3 * Math.sin(i * 0.21)))),
    };
  }
  // Overlay richer existing readiness data for the most recent 30 days
  MOCK_READINESS.forEach(r => {
    if (map[r.date]) map[r.date].readiness = r.readiness_score;
  });
  return map;
})();

// TSS by date: existing workout data + generated history for earlier days
const _MOCK_TSS_BY_DATE = (() => {
  const TODAY = '2026-05-27';
  const map = {};
  for (let i = 0; i < 90; i++) {
    const date = _shiftDate(TODAY, i - 89);
    if (i % 2 === 0 && i % 5 !== 0) {
      map[date] = Math.round(45 + 80 * Math.abs(Math.sin(i * 0.17)));
    }
  }
  MOCK_TSS.forEach(({ date, tss }) => { map[date] = (map[date] || 0) + tss; });
  return map;
})();

// ── Aggregation helpers ───────────────────────────────────────────────────────

function _safeAvg(vals) {
  const v = vals.filter(x => x !== null && x !== undefined);
  if (!v.length) return null;
  return Math.round(v.reduce((a, b) => a + b, 0) / v.length * 100) / 100;
}

function _safeMin(vals) {
  const v = vals.filter(x => x !== null);
  return v.length ? Math.min(...v) : null;
}

function _safeMax(vals) {
  const v = vals.filter(x => x !== null);
  return v.length ? Math.max(...v) : null;
}

function _safeStddev(vals) {
  const v = vals.filter(x => x !== null);
  if (v.length < 2) return null;
  const mean = v.reduce((a, b) => a + b, 0) / v.length;
  return Math.round(Math.sqrt(v.reduce((s, x) => s + (x - mean) ** 2, 0) / v.length) * 100) / 100;
}

function _computeDelta(curAvg, prevAvg) {
  if (curAvg === null || prevAvg === null || prevAvg === 0) {
    return { value: null, pct: null, direction: 'flat' };
  }
  const val = Math.round((curAvg - prevAvg) * 100) / 100;
  const pct = Math.round((val / Math.abs(prevAvg)) * 10000) / 100;
  const direction = val > 0.005 ? 'up' : val < -0.005 ? 'down' : 'flat';
  return { value: val, pct, direction };
}

function _buildSeries(dates, getVal) {
  return dates.map(date => ({ date, value: getVal(date) }));
}

// ── Public mock endpoint ──────────────────────────────────────────────────────

function mockGetTrendsSummary(params) {
  const hasRange = params.range != null;
  const hasFrom  = Boolean(params.from);
  const hasTo    = Boolean(params.to);

  if (hasRange && (hasFrom || hasTo)) {
    const e = new Error('range and from/to are mutually exclusive'); e.status = 400; throw e;
  }

  const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
  let from, to;

  if (hasFrom || hasTo) {
    if (!hasFrom || !hasTo) {
      const e = new Error('Both from and to are required for a custom date range'); e.status = 400; throw e;
    }
    if (!DATE_RE.test(params.from) || !DATE_RE.test(params.to)) {
      const e = new Error('Invalid date format — use YYYY-MM-DD'); e.status = 400; throw e;
    }
    from = params.from; to = params.to;
  } else {
    const range = hasRange ? params.range : '30d';
    if (!['7d', '30d', '90d'].includes(range)) {
      const e = new Error(`Invalid range "${range}" — allowed: 7d, 30d, 90d`); e.status = 400; throw e;
    }
    const n = parseInt(range, 10);
    const todayD = new Date('2026-05-27T00:00:00');
    const fromD  = new Date(todayD); fromD.setDate(todayD.getDate() - n + 1);
    from = _fmtD(fromD); to = _fmtD(todayD);
  }

  const totalDays = _daysBetween(from, to) + 1;
  const prevTo    = _shiftDate(from, -1);
  const prevFrom  = _shiftDate(prevTo, -(totalDays - 1));

  const dates     = Array.from({ length: totalDays }, (_, i) => _shiftDate(from, i));
  const prevDates = Array.from({ length: totalDays }, (_, i) => _shiftDate(prevFrom, i));

  function raw(date, field)  { return (_MOCK_DAILY_RAW[date] || {})[field] ?? null; }
  function vals(ds, field)   { return ds.map(d => raw(d, field)); }
  function series(field)     { return _buildSeries(dates, d => raw(d, field)); }
  function delta(field)      { return _computeDelta(_safeAvg(vals(dates, field)), _safeAvg(vals(prevDates, field))); }

  // readiness
  const readSeries = series('readiness');
  const readVals   = readSeries.map(s => s.value);
  const readLatest = [...readVals].reverse().find(v => v !== null) ?? null;

  // hrv (baseline covers all available data for a stable reference)
  const hrvSeries  = series('hrv');
  const hrvVals    = hrvSeries.map(s => s.value);
  const allHrv     = Object.values(_MOCK_DAILY_RAW).map(r => r.hrv).filter(v => v !== null);

  // rhr
  const rhrSeries  = series('rhr');
  const rhrVals    = rhrSeries.map(s => s.value);
  const rhrLatest  = [...rhrVals].reverse().find(v => v !== null) ?? null;
  const allRhr     = Object.values(_MOCK_DAILY_RAW).map(r => r.rhr).filter(v => v !== null);

  // tss
  const tssSeries  = _buildSeries(dates, d => _MOCK_TSS_BY_DATE[d] ?? null);
  const tssVals    = tssSeries.map(s => s.value);
  const tssValid   = tssVals.filter(v => v !== null);
  const prevTssVals = prevDates.map(d => _MOCK_TSS_BY_DATE[d] ?? null);

  return {
    meta: { range: hasRange ? params.range : null, from, to, days: totalDays },
    readiness: {
      avg: _safeAvg(readVals), min: _safeMin(readVals), max: _safeMax(readVals), latest: readLatest,
      series: readSeries, delta: delta('readiness'),
    },
    hrv: {
      avg: _safeAvg(hrvVals), baseline_mean: _safeAvg(allHrv), baseline_sd: _safeStddev(allHrv),
      series: hrvSeries, delta: delta('hrv'),
    },
    rhr: {
      avg: _safeAvg(rhrVals), min: _safeMin(rhrVals), max: _safeMax(rhrVals), latest: rhrLatest,
      baseline_mean: _safeAvg(allRhr), baseline_sd: _safeStddev(allRhr),
      series: rhrSeries, delta: delta('rhr'),
    },
    sleep: {
      avg: _safeAvg(vals(dates, 'sleep')),
      series: dates.map(d => ({ date: d, value: raw(d, 'sleep'), quality: raw(d, 'sleep_quality') })),
      delta: delta('sleep'),
    },
    energy: {
      avg: _safeAvg(vals(dates, 'energy')),
      series: series('energy'), delta: delta('energy'),
    },
    mood: {
      avg: _safeAvg(vals(dates, 'mood')),
      series: series('mood'), delta: delta('mood'),
    },
    tss: {
      total: tssValid.length ? Math.round(tssValid.reduce((a, b) => a + b, 0)) : null,
      avg: _safeAvg(tssVals),
      series: tssSeries,
      delta: _computeDelta(_safeAvg(tssVals), _safeAvg(prevTssVals)),
    },
  };
}

// MOCK — pre-computed 7-day trends summary used when /trends/summary?range=7d is unavailable
// Shape mirrors the real GET /trends/summary response.
const MOCK_TRENDS_SUMMARY = {
  range: { from: '2026-05-21', to: '2026-05-27', days: 7 },
  readiness: {
    series: [
      { date: '2026-05-21', score: 68 }, { date: '2026-05-22', score: 72 },
      { date: '2026-05-23', score: 70 }, { date: '2026-05-24', score: 75 },
      { date: '2026-05-25', score: 74 }, { date: '2026-05-26', score: 71 },
      { date: '2026-05-27', score: 73 },
    ],
    avg: 73.0, min: 68, max: 75,
  },
  hrv: {
    series: [
      { date: '2026-05-21', value: 49 }, { date: '2026-05-22', value: 51 },
      { date: '2026-05-23', value: 48 }, { date: '2026-05-24', value: 50 },
      { date: '2026-05-25', value: 38 }, { date: '2026-05-26', value: 37 },
      { date: '2026-05-27', value: 36 },
    ],
    avg: 44.0, min: 42, max: 46,
    baseline_mean: 46.2, baseline_sd: 5.4, is_approximate: true,
  },
  rhr: {
    series: [
      { date: '2026-05-21', value: 57 }, { date: '2026-05-22', value: 56 },
      { date: '2026-05-23', value: 58 }, { date: '2026-05-24', value: 57 },
      { date: '2026-05-25', value: 56 }, { date: '2026-05-26', value: 57 },
      { date: '2026-05-27', value: 57 },
    ],
    avg: 57.0, min: 56, max: 58,
    baseline_mean: 57.4, baseline_sd: 2.2, is_approximate: true,
  },
  sleep: {
    series: [
      { date: '2026-05-21', hours: 7.5, quality: 4 }, { date: '2026-05-22', hours: 6.8, quality: 3 },
      { date: '2026-05-23', hours: null, quality: null }, { date: '2026-05-24', hours: 7.2, quality: 4 },
      { date: '2026-05-25', hours: 7.5, quality: 5 }, { date: '2026-05-26', hours: 6.5, quality: 3 },
      { date: '2026-05-27', hours: 7.1, quality: 4 },
    ],
    avg_hours: 7.1, min_hours: 6.5, max_hours: 7.5,
  },
  energy: {
    series: [
      { date: '2026-05-21', value: 3 }, { date: '2026-05-22', value: 4 },
      { date: '2026-05-23', value: null }, { date: '2026-05-24', value: 4 },
      { date: '2026-05-25', value: 4 }, { date: '2026-05-26', value: 3 },
      { date: '2026-05-27', value: 4 },
    ],
    avg: 3.6, min: 3, max: 4,
  },
  mood: {
    series: [
      { date: '2026-05-21', value: 4 }, { date: '2026-05-22', value: 3 },
      { date: '2026-05-23', value: null }, { date: '2026-05-24', value: 4 },
      { date: '2026-05-25', value: 5 }, { date: '2026-05-26', value: 3 },
      { date: '2026-05-27', value: 4 },
    ],
    avg: 3.9, min: 3, max: 5,
  },
  tss: {
    series: [
      { date: '2026-05-21', value: 85 }, { date: '2026-05-22', value: 110 },
      { date: '2026-05-23', value: null }, { date: '2026-05-24', value: 120 },
      { date: '2026-05-25', value: 145 }, { date: '2026-05-26', value: 95 },
      { date: '2026-05-27', value: 115 },
    ],
    avg: 111.7, total: 670.0,
  },
  deltas: {
    readiness: '+4',
    hrv: '-5',
    rhr: '+1',
    sleep: '-0.5h',
    energy: '+0.2',
    mood: '-0.1',
    tss: '+70%',
  },
};

// MOCK — today's readiness record used when /api/readiness/today is unavailable
const MOCK_READINESS_TODAY = {
  date: '2026-05-27',
  score: 73,
  hrv_contribution: 18.75,
  rhr_contribution: 20.0,
  sleep_contribution: 20.0,
  energy_contribution: 18.75,
  missing_data: { hrv: false, rhr: false, sleep: false, energy: false },
};

// MOCK — today's daily metrics used when /api/daily-metrics is unavailable
const MOCK_DAILY_METRICS_TODAY = {
  date: '2026-05-27',
  hrv: 44,
  resting_hr: 58,
  sleep_hours: 7.1,
  energy: 4,
};

// MOCK — training log workouts for log.html (30+ days ending 2026-05-27)
// Shape mirrors GET /training_log response workouts array.
const MOCK_WORKOUTS = [
  // Week May 25–31
  { id: 1,  date: '2026-05-27', type: 'run',  title: 'Morning tempo run',       duration_minutes: 45,  distance_km: 9.2,  weight_context: null,           avg_hr: 158, tss: 65,  source: 'strava', notes: 'Felt strong through the hills' },
  { id: 2,  date: '2026-05-26', type: 'lift', title: 'Upper body strength',      duration_minutes: 60,  distance_km: null, weight_context: '80 kg bench',  avg_hr: 128, tss: 42,  source: 'manual', notes: '' },
  { id: 3,  date: '2026-05-25', type: 'wod',  title: 'CrossFit Fran',            duration_minutes: 30,  distance_km: null, weight_context: null,           avg_hr: 172, tss: 78,  source: 'manual', notes: '3:45 Rx' },
  { id: 4,  date: '2026-05-24', type: 'bike', title: 'Easy recovery ride',       duration_minutes: 40,  distance_km: 18.5, weight_context: null,           avg_hr: 135, tss: 38,  source: 'strava', notes: '' },
  // Week May 18–24
  { id: 5,  date: '2026-05-22', type: 'run',  title: 'Long run',                 duration_minutes: 90,  distance_km: 18.4, weight_context: null,           avg_hr: 148, tss: 120, source: 'strava', notes: 'Easy aerobic pace' },
  { id: 6,  date: '2026-05-22', type: 'lift', title: 'Leg day',                  duration_minutes: 55,  distance_km: null, weight_context: '100 kg squat', avg_hr: 130, tss: 55,  source: 'manual', notes: '' },
  { id: 7,  date: '2026-05-21', type: 'run',  title: 'Interval session',         duration_minutes: 50,  distance_km: 10.5, weight_context: null,           avg_hr: 168, tss: 88,  source: 'strava', notes: '6×800 m @ 5 K pace' },
  { id: 8,  date: '2026-05-20', type: 'bike', title: 'Zwift Zone 2',             duration_minutes: 75,  distance_km: 35.0, weight_context: null,           avg_hr: 138, tss: 82,  source: 'strava', notes: '' },
  { id: 9,  date: '2026-05-19', type: 'wod',  title: 'Hero WOD — Murph',         duration_minutes: 50,  distance_km: null, weight_context: null,           avg_hr: 162, tss: 95,  source: 'manual', notes: 'With vest' },
  // Week May 11–17
  { id: 10, date: '2026-05-17', type: 'run',  title: 'Easy 5 km',               duration_minutes: 30,  distance_km: 5.2,  weight_context: null,           avg_hr: 142, tss: 28,  source: 'strava', notes: '' },
  { id: 11, date: '2026-05-16', type: 'lift', title: 'Push day',                 duration_minutes: 45,  distance_km: null, weight_context: '75 kg bench',  avg_hr: 122, tss: 35,  source: 'manual', notes: '' },
  { id: 12, date: '2026-05-15', type: 'bike', title: 'Weekend endurance ride',   duration_minutes: 120, distance_km: 65.0, weight_context: null,           avg_hr: 145, tss: 118, source: 'strava', notes: 'Hilly route, great weather' },
  { id: 13, date: '2026-05-14', type: 'run',  title: 'Track workout',            duration_minutes: 55,  distance_km: 12.0, weight_context: null,           avg_hr: 165, tss: 72,  source: 'strava', notes: '10×400 m' },
  { id: 14, date: '2026-05-13', type: 'lift', title: 'Pull day',                 duration_minutes: 50,  distance_km: null, weight_context: '90 kg deadlift', avg_hr: 125, tss: 38, source: 'manual', notes: '' },
  // Week May 4–10
  { id: 15, date: '2026-05-08', type: 'run',  title: 'Recovery jog',             duration_minutes: 25,  distance_km: 4.5,  weight_context: null,           avg_hr: 135, tss: 18,  source: 'manual', notes: '' },
  { id: 16, date: '2026-05-07', type: 'wod',  title: 'AMRAP 20 min',             duration_minutes: 25,  distance_km: null, weight_context: null,           avg_hr: 168, tss: 60,  source: 'manual', notes: '8 rounds+' },
  { id: 17, date: '2026-05-06', type: 'bike', title: 'Morning spin',             duration_minutes: 45,  distance_km: 22.0, weight_context: null,           avg_hr: 140, tss: 55,  source: 'strava', notes: '' },
  { id: 18, date: '2026-05-05', type: 'run',  title: 'Long run',                 duration_minutes: 80,  distance_km: 15.5, weight_context: null,           avg_hr: 150, tss: 105, source: 'strava', notes: 'Feeling heavy in the legs' },
  { id: 19, date: '2026-05-04', type: 'lift', title: 'Full body strength',       duration_minutes: 65,  distance_km: null, weight_context: '85 kg squat',  avg_hr: 128, tss: 48,  source: 'manual', notes: '' },
  // Week Apr 27 – May 3
  { id: 20, date: '2026-04-30', type: 'run',  title: 'Easy aerobic run',         duration_minutes: 40,  distance_km: 7.8,  weight_context: null,           avg_hr: 140, tss: 35,  source: 'strava', notes: '' },
  { id: 21, date: '2026-04-29', type: 'bike', title: 'Road ride',                duration_minutes: 95,  distance_km: 48.0, weight_context: null,           avg_hr: 152, tss: 110, source: 'strava', notes: 'Great weather' },
  { id: 22, date: '2026-04-28', type: 'lift', title: 'Heavy deadlifts',          duration_minutes: 60,  distance_km: null, weight_context: '120 kg DL',    avg_hr: 132, tss: 52,  source: 'manual', notes: '3×5 near PR' },
];

// MOCK — 30-day sleep quality (1–5), energy (1–5), mood (1–5) ending 2026-05-27; null = no entry that day
const MOCK_SEM = [
  { date: '2026-04-28', sleep_quality: 4, energy: 3, mood: 3 },
  { date: '2026-04-29', sleep_quality: 3, energy: 3, mood: 4 },
  { date: '2026-04-30', sleep_quality: 4, energy: 4, mood: 4 },
  { date: '2026-05-01', sleep_quality: 5, energy: 4, mood: 5 },
  { date: '2026-05-02', sleep_quality: 4, energy: 3, mood: 4 },
  { date: '2026-05-03', sleep_quality: null, energy: null, mood: null },
  { date: '2026-05-04', sleep_quality: 3, energy: 2, mood: 3 },
  { date: '2026-05-05', sleep_quality: 2, energy: 2, mood: 2 },
  { date: '2026-05-06', sleep_quality: 3, energy: 3, mood: 3 },
  { date: '2026-05-07', sleep_quality: 2, energy: 2, mood: 2 },
  { date: '2026-05-08', sleep_quality: 2, energy: 1, mood: 2 },
  { date: '2026-05-09', sleep_quality: 1, energy: 1, mood: 1 },
  { date: '2026-05-10', sleep_quality: 2, energy: 2, mood: 2 },
  { date: '2026-05-11', sleep_quality: null, energy: null, mood: null },
  { date: '2026-05-12', sleep_quality: 3, energy: 3, mood: 3 },
  { date: '2026-05-13', sleep_quality: 3, energy: 3, mood: 4 },
  { date: '2026-05-14', sleep_quality: 4, energy: 4, mood: 4 },
  { date: '2026-05-15', sleep_quality: 4, energy: 4, mood: 4 },
  { date: '2026-05-16', sleep_quality: 4, energy: 4, mood: 5 },
  { date: '2026-05-17', sleep_quality: 4, energy: 3, mood: 4 },
  { date: '2026-05-18', sleep_quality: 3, energy: 3, mood: 3 },
  { date: '2026-05-19', sleep_quality: null, energy: null, mood: null },
  { date: '2026-05-20', sleep_quality: 4, energy: 4, mood: 4 },
  { date: '2026-05-21', sleep_quality: 4, energy: 3, mood: 4 },
  { date: '2026-05-22', sleep_quality: 3, energy: 4, mood: 3 },
  { date: '2026-05-23', sleep_quality: 4, energy: 3, mood: 4 },
  { date: '2026-05-24', sleep_quality: 4, energy: 4, mood: 4 },
  { date: '2026-05-25', sleep_quality: 5, energy: 4, mood: 5 },
  { date: '2026-05-26', sleep_quality: 3, energy: 3, mood: 3 },
  { date: '2026-05-27', sleep_quality: 4, energy: 4, mood: 4 },
];

// MOCK — 30-day HRV and RHR values ending 2026-05-27; used to compute baseline in the mock fallback
// baseline_mean(hrv)≈46.2 ms  SD≈5.4 ms   baseline_mean(rhr)≈57.4 bpm  SD≈2.2 bpm
const MOCK_HRV_RHR = [
  { date: '2026-04-28', hrv: 52, rhr: 55 },
  { date: '2026-04-29', hrv: 50, rhr: 56 },
  { date: '2026-04-30', hrv: 47, rhr: 58 },
  { date: '2026-05-01', hrv: 53, rhr: 55 },
  { date: '2026-05-02', hrv: 55, rhr: 54 },
  { date: '2026-05-03', hrv: 48, rhr: 57 },
  { date: '2026-05-04', hrv: 44, rhr: 59 },
  { date: '2026-05-05', hrv: 46, rhr: 58 },
  { date: '2026-05-06', hrv: 43, rhr: 60 },
  { date: '2026-05-07', hrv: 40, rhr: 61 },
  { date: '2026-05-08', hrv: 38, rhr: 62 },
  { date: '2026-05-09', hrv: 36, rhr: 63 },
  { date: '2026-05-10', hrv: 41, rhr: 60 },
  { date: '2026-05-11', hrv: 45, rhr: 58 },
  { date: '2026-05-12', hrv: 47, rhr: 57 },
  { date: '2026-05-13', hrv: 50, rhr: 56 },
  { date: '2026-05-14', hrv: 52, rhr: 55 },
  { date: '2026-05-15', hrv: 54, rhr: 54 },
  { date: '2026-05-16', hrv: 51, rhr: 55 },
  { date: '2026-05-17', hrv: 48, rhr: 57 },
  { date: '2026-05-18', hrv: 46, rhr: 58 },
  { date: '2026-05-19', hrv: 44, rhr: 59 },
  { date: '2026-05-20', hrv: 47, rhr: 57 },
  { date: '2026-05-21', hrv: 42, rhr: 57 },
  { date: '2026-05-22', hrv: 45, rhr: 56 },
  { date: '2026-05-23', hrv: 43, rhr: 58 },
  { date: '2026-05-24', hrv: 46, rhr: 57 },
  { date: '2026-05-25', hrv: 44, rhr: 56 },
  { date: '2026-05-26', hrv: 43, rhr: 57 },
  { date: '2026-05-27', hrv: 44, rhr: 57 },
];

// MOCK — sample weight entries used when the selected user has no server data
const MOCK_WEIGHT_ENTRIES = [
  { recorded_date: '2026-05-18', weight_kg: 74.2 },
  { recorded_date: '2026-05-19', weight_kg: 73.9 },
  { recorded_date: '2026-05-20', weight_kg: 74.1 },
  { recorded_date: '2026-05-21', weight_kg: 73.7 },
  { recorded_date: '2026-05-22', weight_kg: 73.5 },
  { recorded_date: '2026-05-23', weight_kg: 73.8 },
  { recorded_date: '2026-05-24', weight_kg: 73.3 },
];

// MOCK — training log workouts used when GET /training_log is unavailable.
// Each entry mirrors the shape returned by the real endpoint's workouts array.
// Fields: id, date (YYYY-MM-DD), type (run|lift|wod|bike), title, duration_min,
//         distance_km, avg_hr, tss, source (Strava|Manual), notes,
//         pace_per_km (e.g. "4:56"), top_weight_kg
const MOCK_TRAINING_WORKOUTS = [
  // ── Week May 25 – 31 (current week) ──
  { id: 'w-001', date: '2026-05-27', type: 'lift', title: 'Morning Strength',      duration_min: 60,  distance_km: null, avg_hr: null, tss: 55,  source: 'Manual', notes: null,              pace_per_km: null,  top_weight_kg: 120, strava_activity_url: null },
  { id: 'w-002', date: '2026-05-25', type: 'run',  title: 'Sunday Long Run',       duration_min: 75,  distance_km: 15.2, avg_hr: 148,  tss: 85,  source: 'Strava', notes: null,              pace_per_km: '4:56', top_weight_kg: null, strava_activity_url: 'https://www.strava.com/activities/11000000002' },
  // ── Week May 18 – 24 ──
  { id: 'w-003', date: '2026-05-24', type: 'run',  title: 'Saturday Long Run',     duration_min: 92,  distance_km: 18.0, avg_hr: 151,  tss: 108, source: 'Strava', notes: null,              pace_per_km: '5:06', top_weight_kg: null, strava_activity_url: 'https://www.strava.com/activities/11000000003' },
  { id: 'w-004', date: '2026-05-23', type: 'run',  title: 'Easy Recovery Run',     duration_min: 31,  distance_km: 5.0,  avg_hr: 132,  tss: 28,  source: 'Strava', notes: null,              pace_per_km: '6:12', top_weight_kg: null, strava_activity_url: null },
  { id: 'w-005', date: '2026-05-22', type: 'wod',  title: 'CrossFit Benchmark',    duration_min: 28,  distance_km: null, avg_hr: 172,  tss: 92,  source: 'Manual', notes: 'Fran – 3:42',    pace_per_km: null,  top_weight_kg: null, strava_activity_url: null },
  { id: 'w-006', date: '2026-05-22', type: 'lift', title: 'Heavy Deadlifts',       duration_min: 70,  distance_km: null, avg_hr: null, tss: 65,  source: 'Manual', notes: null,              pace_per_km: null,  top_weight_kg: 180, strava_activity_url: null },
  { id: 'w-007', date: '2026-05-21', type: 'bike', title: 'Evening Spin',          duration_min: 88,  distance_km: 38.0, avg_hr: 143,  tss: 78,  source: 'Strava', notes: null,              pace_per_km: null,  top_weight_kg: null, strava_activity_url: 'https://www.strava.com/activities/11000000007' },
  { id: 'w-008', date: '2026-05-19', type: 'run',  title: 'Tempo Tuesday',         duration_min: 44,  distance_km: 8.0,  avg_hr: 162,  tss: 72,  source: 'Strava', notes: null,              pace_per_km: '5:30', top_weight_kg: null, strava_activity_url: 'https://www.strava.com/activities/11000000008' },
  // ── Week May 11 – 17 ──
  { id: 'w-009', date: '2026-05-17', type: 'run',  title: 'Long Run',              duration_min: 108, distance_km: 22.0, avg_hr: 154,  tss: 122, source: 'Strava', notes: null,              pace_per_km: '4:54', top_weight_kg: null, strava_activity_url: 'https://www.strava.com/activities/11000000009' },
  { id: 'w-010', date: '2026-05-16', type: 'run',  title: 'Interval Training',     duration_min: 54,  distance_km: 10.0, avg_hr: 168,  tss: 88,  source: 'Strava', notes: '6×1km @ 4:10',  pace_per_km: '5:24', top_weight_kg: null, strava_activity_url: 'https://www.strava.com/activities/11000000010' },
  { id: 'w-011', date: '2026-05-15', type: 'lift', title: 'Pull Day',              duration_min: 58,  distance_km: null, avg_hr: null, tss: 48,  source: 'Manual', notes: null,              pace_per_km: null,  top_weight_kg: 90,  strava_activity_url: null },
  { id: 'w-012', date: '2026-05-14', type: 'bike', title: 'Recovery Ride',         duration_min: 52,  distance_km: 25.0, avg_hr: 128,  tss: 32,  source: 'Strava', notes: null,              pace_per_km: null,  top_weight_kg: null, strava_activity_url: 'https://www.strava.com/activities/11000000012' },
  { id: 'w-013', date: '2026-05-13', type: 'run',  title: '5k Time Trial',         duration_min: 22,  distance_km: 5.0,  avg_hr: 175,  tss: 55,  source: 'Strava', notes: 'New PB!',        pace_per_km: '4:24', top_weight_kg: null, strava_activity_url: 'https://www.strava.com/activities/11000000013' },
  { id: 'w-014', date: '2026-05-12', type: 'lift', title: 'Push Day',              duration_min: 55,  distance_km: null, avg_hr: null, tss: 45,  source: 'Manual', notes: null,              pace_per_km: null,  top_weight_kg: 100, strava_activity_url: null },
  // ── Week May 4 – 10 ──
  { id: 'w-015', date: '2026-05-10', type: 'run',  title: 'Recovery Run',          duration_min: 34,  distance_km: 6.0,  avg_hr: 135,  tss: 30,  source: 'Strava', notes: null,              pace_per_km: '5:40', top_weight_kg: null, strava_activity_url: 'https://www.strava.com/activities/11000000015' },
  { id: 'w-016', date: '2026-05-08', type: 'bike', title: 'Long Ride',             duration_min: 132, distance_km: 58.0, avg_hr: 146,  tss: 128, source: 'Strava', notes: null,              pace_per_km: null,  top_weight_kg: null, strava_activity_url: 'https://www.strava.com/activities/11000000016' },
  { id: 'w-017', date: '2026-05-07', type: 'wod',  title: 'Murph',                 duration_min: 42,  distance_km: null, avg_hr: 166,  tss: 105, source: 'Manual', notes: '42:05 with vest', pace_per_km: null,  top_weight_kg: null, strava_activity_url: null },
  { id: 'w-018', date: '2026-05-06', type: 'run',  title: 'Easy Run',              duration_min: 40,  distance_km: 7.0,  avg_hr: 140,  tss: 38,  source: 'Strava', notes: null,              pace_per_km: '5:42', top_weight_kg: null, strava_activity_url: 'https://www.strava.com/activities/11000000018' },
  { id: 'w-019', date: '2026-05-05', type: 'lift', title: 'Full Body',             duration_min: 62,  distance_km: null, avg_hr: null, tss: 58,  source: 'Manual', notes: null,              pace_per_km: null,  top_weight_kg: 140, strava_activity_url: null },
  // ── Week Apr 27 – May 3 ──
  { id: 'w-020', date: '2026-05-02', type: 'run',  title: 'Easy Jog',              duration_min: 34,  distance_km: 6.0,  avg_hr: 138,  tss: 32,  source: 'Strava', notes: null,              pace_per_km: '5:40', top_weight_kg: null, strava_activity_url: 'https://www.strava.com/activities/11000000020' },
  { id: 'w-021', date: '2026-04-30', type: 'wod',  title: 'Benchmark WOD',         duration_min: 32,  distance_km: null, avg_hr: 168,  tss: 82,  source: 'Manual', notes: 'Helen – 10:22',  pace_per_km: null,  top_weight_kg: null, strava_activity_url: null },
  { id: 'w-022', date: '2026-04-29', type: 'lift', title: 'Strength A',            duration_min: 60,  distance_km: null, avg_hr: null, tss: 52,  source: 'Manual', notes: null,              pace_per_km: null,  top_weight_kg: 130, strava_activity_url: null },
  { id: 'w-023', date: '2026-04-28', type: 'run',  title: 'Monday Run',            duration_min: 50,  distance_km: 9.0,  avg_hr: 150,  tss: 65,  source: 'Strava', notes: null,              pace_per_km: '5:33', top_weight_kg: null, strava_activity_url: 'https://www.strava.com/activities/11000000023' },
];

// MOCK — rest day entries used when GET /training_log?include_rest=true is unavailable.
// Each entry mirrors the real API shape: top-level sleep_hours/energy/mood/resting_hr
// plus a full metrics object for backward compat. Only dates that have no workout
// in MOCK_TRAINING_WORKOUTS appear here.
const MOCK_REST_DAYS = [
  { id: 'r-001', date: '2026-05-26', type: 'rest', sleep_hours: 6.0, energy: 3, mood: 3, resting_hr: 56, metrics: { energy: 3, mood: 3, resting_hr: 56, hrv: 61, sleep_hours: 6.0, sleep_quality: 3, notes: 'Tired after yesterday\'s long run' } },
  { id: 'r-002', date: '2026-05-20', type: 'rest', sleep_hours: 7.5, energy: 4, mood: 4, resting_hr: 54, metrics: { energy: 4, mood: 4, resting_hr: 54, hrv: 68, sleep_hours: 7.5, sleep_quality: 4, notes: null } },
  { id: 'r-003', date: '2026-05-18', type: 'rest', sleep_hours: null, energy: 3, mood: null, resting_hr: 57, metrics: { energy: 3, mood: null, resting_hr: 57, hrv: 62, sleep_hours: null, sleep_quality: null, notes: 'Recovery day' } },
  { id: 'r-004', date: '2026-05-11', type: 'rest', sleep_hours: 5.5, energy: 2, mood: 2, resting_hr: 61, metrics: { energy: 2, mood: 2, resting_hr: 61, hrv: 52, sleep_hours: 5.5, sleep_quality: 2, notes: 'Legs heavy, skipped planned run' } },
  { id: 'r-005', date: '2026-05-09', type: 'rest', sleep_hours: 7.0, energy: 3, mood: 3, resting_hr: 58, metrics: { energy: 3, mood: 3, resting_hr: 58, hrv: 59, sleep_hours: 7.0, sleep_quality: 3, notes: null } },
  { id: 'r-006', date: '2026-05-04', type: 'rest', sleep_hours: 8.5, energy: 5, mood: 4, resting_hr: 52, metrics: { energy: 5, mood: 4, resting_hr: 52, hrv: 72, sleep_hours: 8.5, sleep_quality: 5, notes: 'Great sleep, feeling fresh!' } },
];
