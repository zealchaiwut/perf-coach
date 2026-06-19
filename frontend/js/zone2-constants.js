/* Zone 2 HR band — single source of truth for both Run View and Run Builder.
   Any lap whose avg_hr is >= ZONE2_HR_MIN and <= ZONE2_HR_MAX is Zone 2.
   Defaults (130/155) are overridden by the user's persisted zone2_hr_min/max
   preference, fetched asynchronously on load. */
(function (root) {
  'use strict';
  var ZONE2_HR_MIN = 130;
  var ZONE2_HR_MAX = 155;

  function isZone2Lap(avgHr) {
    return typeof avgHr === 'number' && avgHr >= ZONE2_HR_MIN && avgHr <= ZONE2_HR_MAX;
  }

  root.Zone2 = { ZONE2_HR_MIN: ZONE2_HR_MIN, ZONE2_HR_MAX: ZONE2_HR_MAX, isZone2Lap: isZone2Lap };

  // Load persisted zone-2 bounds from user preferences; falls back to 130/155 on any error.
  fetch('/api/user-preferences')
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (data) {
      if (!data) return;
      var row = (data.row) || {};
      if (typeof row.zone2_hr_min === 'number') {
        ZONE2_HR_MIN = row.zone2_hr_min;
        root.Zone2.ZONE2_HR_MIN = row.zone2_hr_min;
      }
      if (typeof row.zone2_hr_max === 'number') {
        ZONE2_HR_MAX = row.zone2_hr_max;
        root.Zone2.ZONE2_HR_MAX = row.zone2_hr_max;
      }
    })
    .catch(function () {});
}(window));
