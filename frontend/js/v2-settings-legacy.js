(function () {
  var link = document.getElementById("about-legacy-settings");
  if (!link) return;
  fetch("/api/about", { credentials: "same-origin" })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (data) {
      if (!data) return;
      var deadline = "2026-12-22";
      var today = new Date().toISOString().slice(0, 10);
      if (today <= deadline) link.hidden = false;
    })
    .catch(function () {
      link.hidden = false;
    });
})();