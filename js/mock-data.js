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
      { date: '2026-05-21', value: 42 }, { date: '2026-05-22', value: 45 },
      { date: '2026-05-23', value: 43 }, { date: '2026-05-24', value: 46 },
      { date: '2026-05-25', value: 44 }, { date: '2026-05-26', value: 43 },
      { date: '2026-05-27', value: 44 },
    ],
    avg: 44.0, min: 42, max: 46,
  },
  rhr: {
    series: [
      { date: '2026-05-21', value: 57 }, { date: '2026-05-22', value: 56 },
      { date: '2026-05-23', value: 58 }, { date: '2026-05-24', value: 57 },
      { date: '2026-05-25', value: 56 }, { date: '2026-05-26', value: 57 },
      { date: '2026-05-27', value: 57 },
    ],
    avg: 57.0, min: 56, max: 58,
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
