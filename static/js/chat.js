/* Student Support AI - chat frontend.
 *
 * Modes: Fast (small retrieval budget, quick answer) and Detailed
 * (larger budget, step-by-step). Streaming via POST /api/chat/stream
 * (Server-Sent Events) with JSON fallback to POST /api/chat.
 * Supports ?q= / ?subject= / ?module= deep links (click-to-ask).
 */

var currentAborter = null;
var lastFailedMessage = null;

function getMode() {
    var stored = null;
    try {
        stored = localStorage.getItem("ssa_mode");
    } catch (error) {
        stored = null;
    }
    return stored === "detailed" ? "detailed" : "fast";
}

function setMode(mode) {
    var value = mode === "detailed" ? "detailed" : "fast";
    try {
        localStorage.setItem("ssa_mode", value);
    } catch (error) {
        /* private mode: keep going without persistence */
    }
    document.querySelectorAll(".mode-toggle button").forEach(function (btn) {
        var active = btn.getAttribute("data-mode") === value;
        btn.classList.toggle("active", active);
        btn.setAttribute("aria-pressed", active ? "true" : "false");
    });
    var label = document.getElementById("modeLabel");
    if (label) {
        label.textContent = value === "fast" ? "Fast Answer" : "Detailed Answer";
    }
}

function getPageContext() {
    var params = new URLSearchParams(window.location.search || "");
    return {
        q: (params.get("q") || "").trim(),
        subject_code: (params.get("subject") || "").trim().toUpperCase(),
        module_number: (params.get("module") || "").trim()
    };
}

function submitQuestion(text) {
    // Shared submission path for the Send button, suggestion chips,
    // retries and deep links: the exact text is placed in the input
    // synchronously and the same sendMessage pipeline runs, so there
    // is no stale-state race and no duplicate request (sendMessage
    // early-returns while a request is already in flight).
    const input = document.getElementById("chatInput");
    input.value = (text || "").trim();
    sendMessage();
}

function askQuestion(text, subjectCode, moduleNumber) {
    if (subjectCode || moduleNumber) {
        try {
            var url = new URL(window.location.href);
            if (subjectCode) {
                url.searchParams.set("subject", subjectCode);
            }
            if (moduleNumber) {
                url.searchParams.set("module", moduleNumber);
            }
            window.history.replaceState(null, "", url.toString());
        } catch (error) {
            /* ignore */
        }
    }
    submitQuestion(text);
}

function handleEnter(event) {
    if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        if (currentAborter) {
            stopGeneration();
        } else {
            sendMessage();
        }
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

    const seen = {};
    sources.forEach(function (src) {
        const documentId = src.document_id || "unknown";
        const subjectCode = src.subject_code || "";
        const moduleNumber = src.module_number || "";
        const pageNumber = src.page_number || "";
        const filename = src.filename || src.doc_title || "";
        const key = documentId + ":" + pageNumber;
        if (seen[key]) {
            return;
        }
        seen[key] = true;

        let citation = "📄 ";
        if (subjectCode) {
            citation += escapeHtml(subjectCode);
        }
        if (filename) {
            citation += (subjectCode ? " • " : "") + escapeHtml(String(filename));
        }
        if (moduleNumber || pageNumber) {
            citation += "<br>";
            const bits = [];
            if (moduleNumber) {
                bits.push("Module " + escapeHtml(String(moduleNumber)));
            }
            if (pageNumber) {
                bits.push("Page " + escapeHtml(String(pageNumber)));
            }
            citation += bits.join(" • ");
        }
        if (documentId !== "unknown") {
            citation +=
                ' <a href="/knowledge/pdf/' + encodeURIComponent(documentId) +
                '" target="_blank" rel="noopener">Open ↗</a>';
        }

        const span = document.createElement("span");
        span.innerHTML = citation;
        el.appendChild(span);
    });

    messages.appendChild(el);
    scrollChat();
}

function addMessageActions(messageEl, getText) {
    const actions = document.createElement("div");
    actions.className = "message-actions";

    const copyBtn = document.createElement("button");
    copyBtn.type = "button";
    copyBtn.className = "mini-btn";
    copyBtn.textContent = "⧉ Copy";
    copyBtn.onclick = function () {
        const text = getText();
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(function () {
                copyBtn.textContent = "✓ Copied";
                setTimeout(function () { copyBtn.textContent = "⧉ Copy"; }, 1500);
            });
        } else {
            const ta = document.createElement("textarea");
            ta.value = text;
            document.body.appendChild(ta);
            ta.select();
            try { document.execCommand("copy"); } catch (error) { /* ignore */ }
            document.body.removeChild(ta);
            copyBtn.textContent = "✓ Copied";
            setTimeout(function () { copyBtn.textContent = "⧉ Copy"; }, 1500);
        }
    };
    actions.appendChild(copyBtn);

    const retryBtn = document.createElement("button");
    retryBtn.type = "button";
    retryBtn.className = "mini-btn";
    retryBtn.textContent = "↻ Retry";
    retryBtn.onclick = function () {
        if (lastUserMessage) {
            retryMessage(lastUserMessage);
        }
    };
    actions.appendChild(retryBtn);

    messageEl.querySelector(".message-content").appendChild(actions);
}

var lastUserMessage = null;

function renderInline(text) {
    // Inline markup on already-escaped text: `code, **bold**.
    // Runs after escapeHtml, so inserted tags are ours only (XSS-safe).
    return text
        .replace(/`([^`\n]+)`/g, "<code>$1</code>")
        .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}

function renderMarkdown(text) {
    // Small block renderer for model answers: fenced code, headings,
    // bullet/numbered lists, tables, rules, paragraphs. Input is
    // escaped first. Single newlines inside a paragraph are soft
    // wraps and join with a space (standard Markdown); only a blank
    // line starts a new paragraph. This keeps related sentences
    // together instead of breaking every line apart.
    var lines = escapeHtml(text).split("\n");
    var html = [];
    var inCode = false;
    var codeBuf = [];
    var listTag = null;
    var paraBuf = [];
    var tableBuf = [];

    function flushPara() {
        if (paraBuf.length) {
            html.push("<p>" + renderInline(paraBuf.join(" ")) + "</p>");
            paraBuf = [];
        }
    }
    function flushList() {
        if (listTag) {
            html.push("</" + listTag + ">");
            listTag = null;
        }
    }
    function flushTable() {
        if (!tableBuf.length) {
            return;
        }
        var hasSeparator = tableBuf.some(function (line) {
            return /^\|?[\s:|-]+\|[\s:|.-]*$/.test(line);
        });
        if (!hasSeparator || tableBuf.length < 2) {
            // Not really a table: put the lines back as a paragraph.
            paraBuf = paraBuf.concat(tableBuf);
            tableBuf = [];
            flushPara();
            return;
        }
        var rows = tableBuf.filter(function (line) {
            return !/^\|?[\s:|-]+\|[\s:|.-]*$/.test(line);
        });
        var out = ["<table>"];
        rows.forEach(function (line, index) {
            var cells = line.replace(/^\||\|$/g, "").split("|");
            var tag = index === 0 ? "th" : "td";
            out.push("<tr>" + cells.map(function (cell) {
                return "<" + tag + ">" + renderInline(cell.trim()) + "</" + tag + ">";
            }).join("") + "</tr>");
        });
        out.push("</table>");
        html.push(out.join(""));
        tableBuf = [];
    }

    lines.forEach(function (line) {
        var trimmed = line.trim();
        if (trimmed.indexOf("```") === 0) {
            if (inCode) {
                html.push("<pre><code>" + codeBuf.join("\n") + "</code></pre>");
                codeBuf = [];
                inCode = false;
            } else {
                flushPara();
                flushList();
                flushTable();
                inCode = true;
            }
            return;
        }
        if (inCode) {
            codeBuf.push(line);
            return;
        }
        if (trimmed.indexOf("|") !== -1) {
            flushPara();
            flushList();
            tableBuf.push(trimmed);
            return;
        }
        flushTable();
        var heading = trimmed.match(/^(#{1,3})\s+(.*)$/);
        if (heading) {
            flushPara();
            flushList();
            var level = heading[1].length + 1;
            html.push("<h" + level + ">" + renderInline(heading[2]) + "</h" + level + ">");
            return;
        }
        if (/^---+$/.test(trimmed)) {
            flushPara();
            flushList();
            html.push("<hr>");
            return;
        }
        var bullet = trimmed.match(/^[-*]\s+(.*)$/);
        if (bullet) {
            flushPara();
            if (listTag !== "ul") {
                flushList();
                html.push("<ul>");
                listTag = "ul";
            }
            html.push("<li>" + renderInline(bullet[1]) + "</li>");
            return;
        }
        var ordered = trimmed.match(/^\d+[.)]\s+(.*)$/);
        if (ordered) {
            flushPara();
            if (listTag !== "ol") {
                flushList();
                html.push("<ol>");
                listTag = "ol";
            }
            html.push("<li>" + renderInline(ordered[1]) + "</li>");
            return;
        }
        if (!trimmed) {
            flushPara();
            flushList();
            return;
        }
        flushList();
        paraBuf.push(trimmed);
    });
    if (inCode) {
        html.push("<pre><code>" + codeBuf.join("\n") + "</code></pre>");
    }
    flushPara();
    flushList();
    flushTable();
    return html.join("\n") || "<p></p>";
}

function formatReply(text) {
    return renderMarkdown(text);
}

function setBusy(busy) {
    const sendButton = document.getElementById("sendButton");
    const stopButton = document.getElementById("stopButton");
    if (sendButton) {
        sendButton.disabled = busy;
        sendButton.style.display = busy ? "none" : "";
    }
    if (stopButton) {
        stopButton.style.display = busy ? "" : "none";
    }
}

function stopGeneration() {
    if (currentAborter) {
        currentAborter.abort();
        currentAborter = null;
    }
}

function buildPayload(message) {
    const ctx = getPageContext();
    const payload = { message: message, mode: getMode() };
    if (ctx.subject_code) {
        payload.subject_code = ctx.subject_code;
    }
    if (ctx.module_number) {
        payload.module_number = ctx.module_number;
    }
    return payload;
}

function updateStatus(info) {
    const status = document.getElementById("engineStatus");
    if (!status) {
        return;
    }
    const bits = [];
    if (info.answer_kind === "ai_generated") {
        const provider = (info.provider || info.engine || "AI").toLowerCase();
        bits.push(provider === "openai" ? "OpenAI"
            : provider === "gemini" ? "Gemini"
            : provider === "ollama" ? "Ollama (local)" : "AI");
    } else if (info.answer_kind === "fallback_excerpts") {
        // User-safe: never render raw error codes or model names.
        // The machine-readable error_code stays in the payload for
        // developers (browser devtools / backend log).
        bits.push("⚠ AI temporarily unavailable");
    } else if (info.engine) {
        bits.push(info.engine);
    }
    if (info.mode) {
        bits.push(info.mode === "fast" ? "⚡ fast" : "🔍 detailed");
    }
    if (info.latency_ms !== undefined && info.latency_ms !== null) {
        bits.push((info.latency_ms / 1000).toFixed(1) + "s");
    }
    if (info.cached) {
        bits.push("cached");
    }
    status.textContent = "● " + (bits.join(" • ") || "Online");
}

async function sendMessage() {
    const input = document.getElementById("chatInput");
    const message = input.value.trim();

    if (!message || currentAborter) {
        return;
    }

    lastUserMessage = message;
    lastFailedMessage = null;
    addUserMessage(message);
    input.value = "";
    input.focus();

    const thinking = addThinking();
    const contentP = thinking.querySelector(".message-content p");
    setBusy(true);

    currentAborter = new AbortController();
    const signal = currentAborter.signal;
    const payload = buildPayload(message);
    let fullText = "";
    let sources = [];
    let streamed = false;

    const renderStreamed = function () {
        contentP.innerHTML = formatReply(fullText);
        scrollChat();
    };

    try {
        const response = await fetch("/api/chat/stream", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
            signal: signal
        });

        if (!response.ok || !response.body) {
            throw new Error("stream unavailable");
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let done = false;

        while (!done) {
            const chunk = await reader.read();
            if (chunk.done) {
                break;
            }
            buffer += decoder.decode(chunk.value, { stream: true });
            let sep;
            while ((sep = buffer.indexOf("\n\n")) !== -1) {
                const rawEvent = buffer.slice(0, sep);
                buffer = buffer.slice(sep + 2);
                const lines = rawEvent.split("\n");
                let eventName = "message";
                const dataLines = [];
                lines.forEach(function (line) {
                    if (line.indexOf("event:") === 0) {
                        eventName = line.slice(6).trim();
                    } else if (line.indexOf("data:") === 0) {
                        dataLines.push(line.slice(5).trim());
                    }
                });
                let data = {};
                try {
                    data = JSON.parse(dataLines.join("\n") || "{}");
                } catch (error) {
                    data = {};
                }
                if (eventName === "token" && data.text) {
                    streamed = true;
                    if (!fullText) {
                        contentP.innerHTML = "";
                    }
                    fullText += data.text;
                    renderStreamed();
                } else if (eventName === "sources" && data.sources) {
                    sources = data.sources;
                } else if (eventName === "done") {
                    updateStatus({
                        engine: data.used_ai ? (data.provider || "AI") : "study bank",
                        provider: data.provider,
                        answer_kind: data.answer_kind,
                        error_code: data.error_code,
                        mode: data.mode || getMode(),
                        latency_ms: data.latency_ms,
                        cached: false
                    });
                    done = true;
                } else if (eventName === "error") {
                    throw new Error(data.error || "streaming failed");
                }
            }
        }
    } catch (error) {
        if (error && error.name === "AbortError") {
            contentP.innerHTML = formatReply(fullText || "(stopped)") +
                '<br><em>⏹ Stopped. <button type="button" class="mini-btn" onclick="retryMessage()">↻ Retry</button></em>';
            lastFailedMessage = message;
            setBusy(false);
            currentAborter = null;
            scrollChat();
            return;
        }
        // Streaming failed: fall back to the plain JSON endpoint once.
        try {
            const response = await fetch("/api/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            const data = await response.json();
            fullText = data.answer || data.reply || "";
            sources = data.sources || [];
            if (!fullText) {
                throw new Error("empty answer");
            }
            contentP.innerHTML = formatReply(fullText);
            updateStatus({
                engine: data.engine || (data.used_ai ? (data.provider || "AI") : "study bank"),
                provider: data.provider,
                answer_kind: data.answer_kind,
                error_code: data.error_code,
                mode: data.mode || getMode(),
                latency_ms: data.latency_ms,
                cached: data.cached
            });
            streamed = true;
        } catch (fallbackError) {
            contentP.textContent = "";
            const err = document.createElement("span");
            err.innerHTML = "Sorry, I could not answer that. " +
                '<button type="button" class="mini-btn" onclick="retryMessage()">↻ Retry</button>';
            contentP.appendChild(err);
            lastFailedMessage = message;
        }
    } finally {
        setBusy(false);
        currentAborter = null;
        scrollChat();
    }

    if (streamed && fullText) {
        addSourceCitations(sources);
        addMessageActions(thinking, function () { return fullText; });
    } else if (!fullText) {
        lastFailedMessage = message;
    }
}

function retryMessage(text) {
    const input = document.getElementById("chatInput");
    input.value = text || lastFailedMessage || lastUserMessage || "";
    sendMessage();
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

// Deep link (?q=...) from question lists: populate and answer at once.
document.addEventListener("DOMContentLoaded", function () {
    setMode(getMode());
    const ctx = getPageContext();
    if (ctx.q) {
        const input = document.getElementById("chatInput");
        input.value = ctx.q;
        sendMessage();
    }
});
