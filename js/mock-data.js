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
