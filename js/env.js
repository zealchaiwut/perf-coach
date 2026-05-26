(function () {
  var label = document.getElementById('env-label');
  if (!label) return;

  fetch('/api/environment')
    .then(function (res) { return res.json(); })
    .then(function (data) {
      var env = (data.environment || '').toUpperCase();
      label.textContent = env;
      if (env === 'UAT') label.classList.add('uat');
      if (env === 'PRD') label.classList.add('prd');
    })
    .catch(function () {
      label.textContent = 'DEV';
    });
}());
