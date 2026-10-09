(function () {
  try {
    var saved = localStorage.getItem("job-bot-theme");
    if (saved === "light" || saved === "dark") document.documentElement.dataset.theme = saved;
  } catch (e) {}
})();
