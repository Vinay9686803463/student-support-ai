/* Student Support AI - chat frontend (talks to POST /api/chat) */

function useSuggestion(button) {
    const input = document.getElementById("chatInput");
    input.value = button.innerText.trim();
    input.focus();
}

function handleEnter(event) {
    if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
    }
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

function scrollChat() {
    const messages = document.getElementById("chatMessages");
    messages.scrollTop = messages.scrollHeight;
}

function addUserMessage(text) {
    const messages = document.getElementById("chatMessages");
    const el = document.createElement("div");
    el.className = "message user-message";
    el.innerHTML =
        '<div class="message-content"><strong>You</strong><p>' +
        escapeHtml(text) +
        "</p></div>" +
        '<div class="message-avatar user-avatar">V</div>';
    messages.appendChild(el);
    scrollChat();
}

function addThinking() {
    const messages = document.getElementById("chatMessages");
    const el = document.createElement("div");
    el.className = "message ai-message";
    el.innerHTML =
        '<div class="message-avatar"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456z"/></svg></div>' +
        '<div class="message-content"><strong>Student Support AI</strong>' +
        '<p class="typing">Thinking<span>.</span><span>.</span><span>.</span></p></div>';
    messages.appendChild(el);
    scrollChat();
    return el;
}

function addSourceCitations(sources) {
    const messages = document.getElementById("chatMessages");
    if (!sources || sources.length === 0) {
        return;
    }

    const el = document.createElement("div");
    el.className = "source-citations";
    el.innerHTML = '<strong>Sources</strong>';

    sources.forEach(function (src) {
        const documentId = src.document_id || "unknown";
        const moduleNumber = src.module_number || "";
        const pageNumber = src.page_number || "";
        const similarity = src.similarity !== undefined ? src.similarity.toFixed(2) : "";

        let citation = "";
        if (moduleNumber && pageNumber) {
            citation = `📄 ${documentId}<br>Module ${moduleNumber} • Page ${pageNumber}`;
        } else if (moduleNumber) {
            citation = `📄 ${documentId}<br>Module ${moduleNumber}`;
        } else if (pageNumber) {
            citation = `📄 ${documentId}<br>Page ${pageNumber}`;
        } else {
            citation = `📄 ${documentId}`;
        }

        const span = document.createElement("span");
        span.innerHTML = citation;
        el.appendChild(span);
    });

    messages.appendChild(el);
    scrollChat();
}

function formatReply(text) {
    return escapeHtml(text).replace(/\n/g, "<br>");
}

async function sendMessage() {
    const input = document.getElementById("chatInput");
    const sendButton = document.getElementById("sendButton");
    const message = input.value.trim();

    if (!message) {
        return;
    }

    addUserMessage(message);
    input.value = "";
    input.focus();

    const thinking = addThinking();
    sendButton.disabled = true;

    try {
        const response = await fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: message })
        });

        const data = await response.json();

        // Support new RAG format: answer, sources, used_rag, used_ai
        // Fall back to legacy reply/engine fields.
        const answer = data.answer || data.reply || "Sorry, I could not answer that. Please try again.";
        const sources = data.sources || [];
        const usedRag = data.used_rag || false;
        const usedAi = data.used_ai || false;
        const engine = data.engine || (usedAi ? "gemini" : "study bank");

        thinking.querySelector(".message-content p").innerHTML = formatReply(answer);

        // Display source citations if available.
        addSourceCitations(sources);

        const status = document.getElementById("engineStatus");
        if (status) {
            status.textContent = engine;
        }
    } catch (error) {
        thinking.querySelector(".message-content p").textContent =
            "Network error. Please check your connection and try again.";
    } finally {
        sendButton.disabled = false;
        scrollChat();
    }
}

function clearChat() {
    const messages = document.getElementById("chatMessages");
    messages.querySelectorAll(".message.user-message, .message.ai-message:not(:first-child)").forEach(function (el) {
        el.remove();
    });
    // Also remove source citations.
    messages.querySelectorAll(".source-citations").forEach(function (el) {
        el.remove();
    });
    document.getElementById("chatInput").focus();
}
