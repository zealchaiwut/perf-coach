// MOCK — pre-computed 7-day trends summary used when /trends/summary?range=7d is unavailable
const MOCK_TRENDS_SUMMARY = {
  range_start: '2026-05-21',
  range_end: '2026-05-27',
  days_with_data: 7,
  avg_readiness: 73,
  readiness_delta: 4,
  avg_sleep_hours: 7.1,
  sleep_delta: -0.5,
  avg_hrv: 44,
  hrv_delta: -5,
  avg_rhr: 57,
  rhr_delta: 1,
  total_tss: 670,
  tss_delta: 275,
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
