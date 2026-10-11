/* Important Questions - click-to-ask enhancement.
 *
 * Appends an "Ask AI" button to every question card. Clicking sends the
 * exact question text to the AI Assistant, which starts answering
 * immediately (see chat.js ?q= handling). Normal card/filter behavior
 * is untouched.
 */
(function () {
    function askUrl(questionText) {
        return "/chat?q=" + encodeURIComponent(questionText);
    }

    function enhance() {
        document.querySelectorAll(".question-card").forEach(function (card) {
            if (card.querySelector(".ask-ai-btn")) {
                return;
            }
            var heading = card.querySelector("h3");
            if (!heading) {
                return;
            }
            var text = (heading.innerText || "").trim().replace(/\s+/g, " ");
            if (!text) {
                return;
            }
            var link = document.createElement("a");
            link.className = "ask-ai-btn";
            link.href = askUrl(text);
            link.textContent = "Ask AI \u2726";
            link.setAttribute(
                "aria-label",
                "Ask the AI Assistant about this question"
            );
            var footer = card.querySelector(".question-footer");
            if (footer) {
                footer.appendChild(link);
            } else {
                card.appendChild(link);
            }
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", enhance);
    } else {
        enhance();
    }
})();
