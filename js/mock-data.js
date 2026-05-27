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
      { date: '2026-05-23', hours: 7.0, quality: 4 }, { date: '2026-05-24', hours: 7.2, quality: 4 },
      { date: '2026-05-25', hours: 7.5, quality: 5 }, { date: '2026-05-26', hours: 6.5, quality: 3 },
      { date: '2026-05-27', hours: 7.1, quality: 4 },
    ],
    avg_hours: 7.1, min_hours: 6.5, max_hours: 7.5,
  },
  energy: {
    series: [
      { date: '2026-05-21', value: 3 }, { date: '2026-05-22', value: 4 },
      { date: '2026-05-23', value: 3 }, { date: '2026-05-24', value: 4 },
      { date: '2026-05-25', value: 4 }, { date: '2026-05-26', value: 3 },
      { date: '2026-05-27', value: 4 },
    ],
    avg: 3.6, min: 3, max: 4,
  },
  mood: {
    series: [
      { date: '2026-05-21', value: 4 }, { date: '2026-05-22', value: 3 },
      { date: '2026-05-23', value: 4 }, { date: '2026-05-24', value: 4 },
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
