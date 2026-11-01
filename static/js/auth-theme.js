/* Apply the dashboard's last theme before the authentication page is painted. */
(() => {
  function applyTheme() {
    let dark = false;
    try { dark = localStorage.getItem('aiot-theme-dark') === 'true'; } catch (_) {}
    document.documentElement.classList.toggle('dark-mode', dark);
  }
  applyTheme();
  window.addEventListener('storage', event => {
    if (event.key === 'aiot-theme-dark' || event.key === null) applyTheme();
  });
})();
