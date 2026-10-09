/* Student Support AI - dashboard helpers (time-based greeting) */
(function () {
    var el = document.getElementById("dashboardGreeting");
    if (!el) {
        return;
    }
    var hour = new Date().getHours();
    var text = "Good evening 👋";
    if (hour < 12) {
        text = "Good morning 👋";
    } else if (hour < 17) {
        text = "Good afternoon 👋";
    }
    el.textContent = text;
})();
