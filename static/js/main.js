/* Student Support AI - shared helpers (flash auto-dismiss, dark-mode boot) */
(function () {
    // Auto-dismiss flash messages after 5 seconds
    document.querySelectorAll(".flash-message, .alert").forEach(function (el) {
        setTimeout(function () {
            el.style.transition = "opacity 0.4s ease";
            el.style.opacity = "0";
            setTimeout(function () { el.remove(); }, 450);
        }, 5000);
    });

    // Apply saved dark mode early on every page
    try {
        if (localStorage.getItem("studentSupportDarkMode") === "true") {
            document.body.classList.add("dark-mode");
        }
    } catch (e) { /* storage unavailable */ }
})();

/* Toggle the avatar profile dropdown (works with several menus per page). */
function toggleProfileMenu(event) {
    if (event) {
        event.stopPropagation();
    }
    const button = event && event.currentTarget;
    const menu = button
        ? button.closest(".profile-menu").querySelector(".profile-dropdown")
        : document.getElementById("profileDropdown");
    if (!menu) {
        return;
    }
    const wasOpen = menu.classList.contains("show");
    document.querySelectorAll(".profile-dropdown.show").forEach(function (el) {
        el.classList.remove("show");
    });
    if (!wasOpen) {
        menu.classList.add("show");
    }
}

document.addEventListener("click", function (event) {
    if (!event.target.closest(".profile-menu")) {
        document.querySelectorAll(".profile-dropdown.show").forEach(function (el) {
            el.classList.remove("show");
        });
    }
});

document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
        document.querySelectorAll(".profile-dropdown.show").forEach(function (el) {
            el.classList.remove("show");
        });
    }
});

/* Show / hide password fields (eye toggle on auth pages). */
function togglePassword(inputId, button) {
    const input = document.getElementById(inputId);
    if (!input) {
        return;
    }
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    button.setAttribute("aria-label", show ? "Hide password" : "Show password");
    const eyeOpen = button.querySelector(".eye-open");
    const eyeClosed = button.querySelector(".eye-closed");
    if (eyeOpen && eyeClosed) {
        eyeOpen.style.display = show ? "none" : "";
        eyeClosed.style.display = show ? "" : "none";
    }
}
