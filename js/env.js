(function () {
  fetch('/api/env')
    .then(function (res) { return res.json(); })
    .then(function (data) {
      var env = (data.environment || 'local').toLowerCase();
      document.body.dataset.env = env;
      var label = document.getElementById('env-label');
      if (label) label.textContent = env.toUpperCase();
    })
    .catch(function () {
      document.body.dataset.env = 'local';
    });
}());
