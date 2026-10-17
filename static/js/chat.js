/* Student Support AI - chat frontend.
 *
 * Modes: Fast (small retrieval budget, quick answer) and Detailed
 * (larger budget, step-by-step). Streaming via POST /api/chat/stream
 * (Server-Sent Events) with JSON fallback to POST /api/chat.
 * Supports ?q= / ?subject= / ?module= deep links (click-to-ask).
 */

var currentAborter = null;
var lastFailedMessage = null;
var conversationHistory = [];  // [{role: "user"|"assistant", content: "..."}]

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
    // Escape < and > but NOT &: entities are decoded before this runs
    // (decodeSafeEntities), so & from &amp; should stay as &, not become
    // &amp; again. Escaping only < and > is sufficient for XSS safety
    // since <script> tags are the main vector.
    return text
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
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

// Sources are intentionally never rendered. The server still returns
// per-document metadata (document_id, subject_code, page, ...) inside
// the response and SSE "sources" events so RAG stays auditable and
// grounded — that data is simply dropped before it can reach the DOM.

function stripSystemCitations(text) {
    // Remove ONLY unambiguous system-generated citation markers the
    // backend asks the model to emit: [Source 2] and stored sequences
    // like [Source 1], [Source 3]. Numbered academic reference lists
    // ("1. [3] IEEE 802.11 ..."), topic markers like [2]-modulo, and
    // bracket links are untouched — the pattern must literally start
    // with the word "Source" inside brackets.
    return (text || "").replace(
        /\[\s*Sources?\s*:\s*\d+(?:\s*(?:,|;|and)\s*\d+)*\s*\]|\[\s*Sources?\s+\d+\s*\]/gi,
        ""
    ).replace(/[ \t]+([.,;:])/g, "$1")  // "answer . " -> "answer."
        .replace(/[ \t]{2,}/g, " ")     // collapse gaps left by markers
        .replace(/\(\s*\)/g, "");
}

function addSourceCitations() {
    // No-op by design (kept so any stray historical call site is
    // harmless). Sources never appear in the chat UI.
}

function addFollowupSuggestions(messageEl, suggestions) {
    if (!suggestions || suggestions.length === 0) {
        return;
    }

    const messages = document.getElementById("chatMessages");
    const section = document.createElement("div");
    section.className = "followup-suggestions";

    const label = document.createElement("p");
    label.className = "followup-label";
    label.textContent = "Suggested follow-up questions";
    section.appendChild(label);

    const chips = document.createElement("div");
    chips.className = "suggestions";

    suggestions.forEach(function (text) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "mini-btn suggestion-chip";
        btn.textContent = text;
        btn.title = "Ask: " + text;
        btn.onclick = function () {
            submitQuestion(text);
        };
        chips.appendChild(btn);
    });

    section.appendChild(chips);
    messages.appendChild(section);
    scrollChat();
}

function clearFollowupSuggestions() {
    const messages = document.getElementById("chatMessages");
    messages.querySelectorAll(".followup-suggestions").forEach(function (el) {
        el.remove();
    });
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

var NAMED_ENTITIES = {
    amp: "&", lt: "<", gt: ">", quot: '"', apos: "'",
    nbsp: " ", copy: "©", reg: "®",
    hellip: "…", mdash: "—", ndash: "–",
    laquo: "«", raquo: "»"
};

function decodeSafeEntities(text) {
    // Decode ONLY safe entities the model sometimes emits literally
    // (e.g. "&#x52;equirements"): numeric refs plus a small named
    // allowlist. Runs BEFORE escaping, so decoded "<" can never
    // become markup (XSS-safe). Unknown entities stay untouched.
    return text
        .replace(/&#([0-9]{1,7});/g, function (match, digits) {
            var code = parseInt(digits, 10);
            return (code > 0 && code < 0x110000)
                ? String.fromCharCode(code) : match;
        })
        .replace(/&#[xX]([0-9a-fA-F]{1,6});/g, function (match, hex) {
            var code = parseInt(hex, 16);
            return (code > 0 && code < 0x110000)
                ? String.fromCharCode(code) : match;
        })
        .replace(/&(amp|lt|gt|quot|apos|nbsp|copy|reg|hellip|mdash|ndash|laquo|raquo);/g,
            function (match, name) {
                return NAMED_ENTITIES[name];
            });
}

function unescapeMarkdownPunct(s) {
    // Drop backslashes the model adds before ASCII punctuation
    // ("\#" -> "#", "\*" -> "*"). Backslash+letter sequences
    // (LaTeX like \frac) are intentionally left alone. Runs once
    // per line before block detection (see renderMarkdown); never
    // re-applied downstream so "\\#" correctly stays "\#".
    return s.replace(/\\([\\!"#$%&'()*+,\-./:;<=>?@[\\\]^_`{|}~])/g, "$1");
}

function renderInline(text) {
    // Inline markup on already-escaped text. `code` spans are split
    // out first so unescaping, emphasis padding, and bold/italic
    // never touch code content (LaTeX and examples stay literal).
    var segments = text.split(/(`[^`\n]+`)/g);
    for (var i = 0; i < segments.length; i++) {
        if (i % 2 === 1) {
            segments[i] = "<code>" + segments[i].slice(1, -1) + "</code>";
        } else {
            segments[i] = renderInlineText(segments[i]);
        }
    }
    return segments.join("");
}

function renderInlineText(text) {
    // Split on ** to separate bold spans from plain text. Odd-indexed
    // parts are bold content; even-indexed parts are plain text. This
    // avoids the classic problem where **bold**is an**example** matches
    // **is an** as a single bold span, consuming the ** delimiters from
    // both sides.
    var parts = text.split('**');
    var result = '';

    for (var i = 0; i < parts.length; i++) {
        if (i % 2 === 1) {
            // Bold part
            result += '<strong>' + parts[i] + '</strong>';
        } else {
            // Non-bold part: pad around adjacent bold spans and process
            // italic within this segment.
            var part = parts[i];
            // Pad before if previous part was bold and ended with non-space,
            // and current part doesn't already start with space or begin
            // with sentence-ending punctuation (never put a space before
            // "!", ".", etc. — "**details**." renders as "details.").
            if (i > 0 && parts[i - 1] && parts[i - 1][parts[i - 1].length - 1] !== ' '
                    && part[0] !== ' ' && !/^[.,;:!?)\]}'"]/.test(part)) {
                part = ' ' + part;
            }
            // Pad after if next part is bold and starts with non-space,
            // and current part doesn't already end with space
            if (i < parts.length - 1 && parts[i + 1] && parts[i + 1][0] !== ' ' && part[part.length - 1] !== ' ') {
                part = part + ' ';
            }
            // Convert markdown links. Only http(s), mailto, and local
            // relative paths become anchors; anything else (javascript:
            // etc.) stays literal text. Quotes inside the URL are
            // rejected so the href attribute can't be broken out of.
            part = part.replace(/\[([^\]\n]+)\]\(([^()\s]+)\)/g,
                function (match, label, url) {
                    if (/^(https?:\/\/|mailto:|\/|#)/i.test(url)
                            && url.indexOf('"') === -1) {
                        return '<a href="' + url
                            + '" target="_blank" rel="noopener">'
                            + label + "</a>";
                    }
                    return match;
                });
            // Process italic within non-bold part. Lookbehind is
            // zero-width (no capture), so group 1 is always the italic
            // content — this was previously capturing the prefix
            // alternation and corrupting the emitted <em> tags.
            part = part.replace(
                /(?<=(?:^|[\s(>]|\w))\*(\S(?:[^*\n]*\S)?)\*(?=[\s\S])/g,
                "<em>$1</em>");
            // Add space around italic only when glued to a word: before
            // the open tag when the preceding char is a word char, and
            // after the close tag when the following char is a word
            // char. Punctuation is never padded ("*sprints*." keeps its
            // period tight) and tags are only touched along their outer
            // edges, so "this</em>" content is never mangled.
            part = part.replace(/(?<=\w)<em>/g, " <em>");
            part = part.replace(/<\/em>(?=\w)/g, "</em> ");
            result += part;
        }
    }
    return result;
}

function renderMarkdown(text) {
    // Small block renderer for model answers: fenced code, headings,
    // bullet/numbered lists, tables, rules, paragraphs. Input is
    // escaped first. Single newlines inside a paragraph are soft
    // wraps and join with a space (standard Markdown); only a blank
    // line starts a new paragraph. This keeps related sentences
    // together instead of breaking every line apart. Fenced code
    // blocks are stashed up front (raw) so entity-decoding and
    // Markdown fixes never alter code or LaTeX; inline `code` is
    // protected later inside renderInline.
    var fenceStore = [];
    var remainder = text.replace(/```[\s\S]*?(?:```|$)/g,
        function (block) {
            fenceStore.push(block);
            return "\uE000" + (fenceStore.length - 1) + "\uE000";
        });
    var lines = escapeHtml(decodeSafeEntities(remainder)).split("\n");
    var html = [];
    var inCode = false;
    var codeBuf = [];
    var listTag = null;
    var paraBuf = [];
    var tableBuf = [];
    var quoteBuf = [];

    function flushPara() {
        if (paraBuf.length) {
            html.push("<p>" + renderInline(paraBuf.join(" ")) + "</p>");
            paraBuf = [];
        }
    }
    function flushQuote() {
        if (quoteBuf.length) {
            html.push("<blockquote>" + renderInline(quoteBuf.join(" "))
                + "</blockquote>");
            quoteBuf = [];
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
        html.push('<div class="message-content-table">' + out.join("") + "</div>");
        tableBuf = [];
    }

    lines.forEach(function (line) {
        var trimmed = line.trim();
        // Unescape model over-escaping ("\#", "\*") BEFORE block
        // detection so headings/lists/tables are recognized, but
        // never inside `code` spans (examples stay literal).
        var codeParts = trimmed.split(/(`[^`\n]+`)/g);
        var scan = codeParts.map(function (part, index) {
            return (index % 2 === 1) ? part : unescapeMarkdownPunct(part);
        }).join("");
        if (scan.indexOf("```") === 0) {
            if (inCode) {
                html.push("<pre><code>" + codeBuf.join("\n") + "</code></pre>");
                codeBuf = [];
                inCode = false;
            } else {
                flushPara();
                flushQuote();
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
        if (scan.indexOf("|") !== -1) {
            flushPara();
            flushQuote();
            flushList();
            tableBuf.push(scan);
            return;
        }
        flushTable();
        var heading = scan.match(/^(#{1,4})\s+(.*)$/);
        if (heading) {
            flushPara();
            flushQuote();
            flushList();
            var level = Math.min(heading[1].length + 1, 6);
            html.push("<h" + level + ">" + renderInline(heading[2]) + "</h" + level + ">");
            return;
        }
        if (/^---+$/.test(scan)) {
            flushPara();
            flushQuote();
            flushList();
            html.push("<hr>");
            return;
        }
        var quote = scan.match(/^&gt;\s?(.*)$/);
        if (quote) {
            flushPara();
            flushList();
            flushTable();
            quoteBuf.push(quote[1]);
            return;
        }
        var bullet = scan.match(/^[-*]\s+(.*)$/);
        if (bullet) {
            flushPara();
            flushQuote();
            if (listTag !== "ul") {
                flushList();
                html.push("<ul>");
                listTag = "ul";
            }
            html.push("<li>" + renderInline(bullet[1]) + "</li>");
            return;
        }
        var ordered = scan.match(/^\d+[.)]\s+(.*)$/);
        if (ordered) {
            flushPara();
            flushQuote();
            if (listTag !== "ol") {
                flushList();
                html.push("<ol>");
                listTag = "ol";
            }
            html.push("<li>" + renderInline(ordered[1]) + "</li>");
            return;
        }
        if (!scan) {
            flushPara();
            flushQuote();
            flushList();
            return;
        }
        flushList();
        paraBuf.push(scan);
    });
    if (inCode) {
        html.push("<pre><code>" + codeBuf.join("\n") + "</code></pre>");
    }
    flushPara();
    flushQuote();
    flushList();
    flushTable();
    var out = html.join("\n") || "<p></p>";
    // Restore stashed fenced blocks. decodeSafeEntities runs first so a
    // fence like `x = "&#x52;"` shows the real character, then
    // escapeHtml makes any literal < and > inert (code and LaTeX render
    // literally, with no double conversion). Token char built from its
    // code point to keep the source free of invisible characters.
    var fenceMark = String.fromCharCode(0xE000);
    var fencePattern = new RegExp(
        fenceMark + "(\\d+)" + fenceMark, "g");
    out = out.replace(fencePattern, function (match, index) {
        var raw = fenceStore[parseInt(index, 10)] || "";
        var inner = raw.replace(/^```[^\n]*\n?/, "").replace(/```$/, "");
        // Match the historical output: no trailing newline inside
        // the code element.
        inner = inner.replace(/\n$/, "");
        return "<pre><code>" + escapeHtml(decodeSafeEntities(inner)) + "</code></pre>";
    });
    return out;
}

function formatReply(text) {
    // System-generated citation markers are stripped before Markdown
    // rendering so they never appear while streaming, after completion,
    // or in re-rendered answers.
    return renderMarkdown(stripSystemCitations(text));
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
    // Include recent conversation history (last 6 messages = 3 turns)
    // so follow-up questions can reference previous context.
    if (conversationHistory.length > 0) {
        payload.history = conversationHistory.slice(-6);
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
        // When a general explanation is available, show "Study bank"
        // instead of "AI temporarily unavailable" since a valid
        // answer was provided.
        if (info.has_general_explanation) {
            bits.push("Study bank");
        } else {
            bits.push("⚠ AI temporarily unavailable");
        }
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
    conversationHistory.push({ role: "user", content: message });
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
    let serverSuggestions = [];

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
                        cached: false,
                        has_general_explanation: data.has_general_explanation || false
                    });
                    if (Array.isArray(data.suggestions)) {
                        serverSuggestions = data.suggestions;
                    }
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
            if (Array.isArray(data.suggestions)) {
                serverSuggestions = data.suggestions;
            }
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
                cached: data.cached,
                has_general_explanation: data.has_general_explanation || false
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
        addMessageActions(thinking, function () { return fullText; });
        // Track assistant answer in conversation history for follow-ups.
        conversationHistory.push({ role: "assistant", content: fullText });

        // Replace the static "Try asking" chips with dynamic suggestions
        // after the first real answer, then append suggestions for this
        // answer (avoiding duplicates).
        document.querySelectorAll(".suggestion-area").forEach(function (el) {
            el.remove();
        });
        addFollowupSuggestions(thinking, serverSuggestions);
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
    // Reset conversation history.
    conversationHistory = [];
    document.getElementById("chatInput").focus();
}

// Deep link (?q=...) from question lists: populate and answer at once.
document.addEventListener("DOMContentLoaded", function () {
    setMode(getMode());
    refreshStarterSuggestions();
    const ctx = getPageContext();
    if (ctx.q) {
        const input = document.getElementById("chatInput");
        input.value = ctx.q;
        sendMessage();
    }
});

// Replace the static "Try asking" chips with a balanced mixture drawn
// from the student's actual subjects (see /api/chat/suggestions). A
// subject-specific page context prioritizes that subject. Static
// template chips remain visible until real ones arrive, so the area
// is never empty if the request fails.
function refreshStarterSuggestions() {
    const wrap = document.getElementById("chatSuggestions");
    if (!wrap) {
        return;
    }
    let url = "/api/chat/suggestions";
    const ctx = getPageContext();
    if (ctx.subject_code) {
        url += "?subject_code=" + encodeURIComponent(ctx.subject_code);
    }
    fetch(url).then(function (response) {
        return response.ok ? response.json() : null;
    }).then(function (data) {
        if (!data || !Array.isArray(data.suggestions)
                || data.suggestions.length === 0) {
            return;  // keep the static template chips
        }
        wrap.innerHTML = "";
        data.suggestions.forEach(function (item) {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.onclick = function () { askQuestion(item.text); };
            btn.textContent = item.text;
            if (item.subject_code) {
                btn.title = item.subject_code;
            }
            wrap.appendChild(btn);
        });
    }).catch(function () { /* keep static chips */ });
}
