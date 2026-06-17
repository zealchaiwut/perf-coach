/* Zone 2 HR band — single source of truth for both Run View and Run Builder.
   Any lap whose avg_hr is >= ZONE2_HR_MIN and <= ZONE2_HR_MAX is Zone 2. */
(function (root) {
  'use strict';
  var ZONE2_HR_MIN = 130;
  var ZONE2_HR_MAX = 155;

  function isZone2Lap(avgHr) {
    return typeof avgHr === 'number' && avgHr >= ZONE2_HR_MIN && avgHr <= ZONE2_HR_MAX;
  }

  root.Zone2 = { ZONE2_HR_MIN: ZONE2_HR_MIN, ZONE2_HR_MAX: ZONE2_HR_MAX, isZone2Lap: isZone2Lap };
}(window));
