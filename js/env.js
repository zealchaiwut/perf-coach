(function () {
  var hostname = location.hostname;
  var port = location.port;
  var label = document.getElementById('env-label');
  if (!label) return;

  var env;
  if (hostname.indexOf('uat') !== -1 || port === '8002' || port === '8001') {
    env = 'UAT';
  } else if (port === '8000' || port === '80' || port === '443' || port === '') {
    env = 'PRD';
  } else {
    env = 'DEV';
  }

  label.textContent = env;
  if (env === 'UAT') label.classList.add('uat');
  if (env === 'PRD') label.classList.add('prd');
}());
