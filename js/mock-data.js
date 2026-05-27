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
      sleep:     gap ? null : Math.round(Math.max(4.5, Math.min(9.5, 6.9 + 1.1 * Math.sin(i * 0.19))) * 10) / 10,
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
      series: rhrSeries, delta: delta('rhr'),
    },
    sleep: {
      avg: _safeAvg(vals(dates, 'sleep')),
      series: series('sleep'), delta: delta('sleep'),
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
