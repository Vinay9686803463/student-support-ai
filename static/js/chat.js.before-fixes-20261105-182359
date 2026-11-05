/* Student Support AI - chat frontend.
 *
 * Modes: Fast (small retrieval budget, quick answer) and Detailed
 * (larger budget, step-by-step). Streaming via POST /api/chat/stream
 * (Server-Sent Events) with JSON fallback to POST /api/chat.
 * Supports ?q= / ?subject= / ?module= deep links (click-to-ask).
 */

var currentAborter = null;
var lastFailedMessage = null;
var conversationHistory = [];
var recentTopics = [];
var displayedSuggestions = [];
var latestSuggestionSeq = 0;
var FALLBACK_SUGGESTIONS = [
    "Explain agile vs waterfall models",
    "Give important Computer Networks exam questions",
    "Summarize the seven OSI layers",
    "Explain DFA vs NFA with an example"
];

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

function addFollowupSuggestions(suggestions) {
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
        btn.onclick = function () { submitQuestion(text); };
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
function addSourceCitations() {
    // No-op by design (kept so any stray historical call site is
    // harmless). Sources never appear in the chat UI.
}

function stripSystemCitations(text) {
    // Remove ONLY unambiguous system-generated citation markers the
    // backend asks the model to emit: [Source 2], [Source 1, Source 2],
    // [Sources: 1, 2], etc. Numbered academic reference lists
    // ("1. [3] IEEE 802.11 ..."), topic markers like [2]-modulo, and
    // bracket links are untouched — the pattern must literally start
    // with the word "Source" inside brackets.
    var source = String(text || "");
    var store = [];
    function stash(value) {
        store.push(value);
        return "\uE000S" + (store.length - 1) + "\uE000";
    }
    // Protect code fences and inline code so the cleanup cannot alter
    // their contents (e.g. "int main()" must keep its parentheses).
    source = source.replace(/```[\s\S]*?(?:```|$)/g, stash);
    source = source.replace(/`[^`\n]+`/g, stash);
    source = source.replace(
        /\[\s*Sources?\s*(?::\s*\d+(?:\s*(?:,|;|and)\s*\d+)*|\s+\d+(?:\s*,\s*Sources?\s*\d+)*)\s*\]/gi,
        ""
    ).replace(/[ \t]+([.,;:])/g, "$1")  // "answer . " -> "answer."
        .replace(/[ \t]{2,}/g, " ")     // collapse gaps left by markers
        .replace(/\(\s*\)/g, "");
    return source.replace(/\uE000S(\d+)\uE000/g, function (match, index) {
        return store[parseInt(index, 10)];
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
    nbsp: " ", copy: "©", reg: "®",
    hellip: "…", mdash: "—", ndash: "–",
    laquo: "«", raquo: "»",
    deg: "°", times: "×", divide: "÷", plusmn: "±",
    frac12: "½", frac14: "¼", frac34: "¾",
    sup2: "²", sup3: "³", micro: "µ",
    alpha: "α", beta: "β", gamma: "γ", delta: "δ",
    pi: "π", sigma: "σ", theta: "θ", lambda: "λ", omega: "ω",
    infin: "∞", ne: "≠", le: "≤", ge: "≥",
    rarr: "→", larr: "←", uarr: "↑", darr: "↓", harr: "↔",
    check: "✓", cross: "✗", bull: "•", dagger: "†", prime: "′",
    euro: "€", pound: "£", yen: "¥", cent: "¢",
    sect: "§", para: "¶", middot: "·"
};

function _stashValue(store, value) {
    store.push(value);
    return "\uE000" + (store.length - 1) + "\uE000";
}

function decodeSafeEntities(text) {
    // Decode ONLY safe entities the model sometimes emits literally
    // (e.g. "&#x52;equirements"). Inline code and math are stashed
    // first so their contents are never decoded (preserving entity-like
    // text inside code/examples). Unknown entities stay untouched.
    if (!text) {
        return "";
    }
    var store = [];
    var protectedText = String(text)
        .replace(/`[^`\n]+`/g, function (match) {
            return _stashValue(store, match);
        })
        .replace(/\$\$[^$\n]+\$\$/g, function (match) {
            return _stashValue(store, match);
        })
        .replace(/\$[^$\n]+\$/g, function (match) {
            return _stashValue(store, match);
        });

    protectedText = protectedText
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
        .replace(/&(amp|lt|gt|quot|apos|nbsp|copy|reg|hellip|mdash|ndash|laquo|raquo|deg|times|divide|plusmn|frac12|frac14|frac34|sup2|sup3|micro|alpha|beta|gamma|delta|pi|sigma|theta|lambda|omega|infin|ne|le|ge|rarr|larr|uarr|darr|harr|check|cross|bull|dagger|prime|euro|pound|yen|cent|sect|para|middot);/g,
            function (match, name) {
                return NAMED_ENTITIES[name] || match;
            });

    return protectedText.replace(/\uE000(\d+)\uE000/g, function (match, index) {
        return store[parseInt(index, 10)];
    });
}

function stripInternalCommentary(text) {
    // Remove sentences that only describe internal retrieval status.
    // These must never be shown to students.
    var out = String(text || "");
    out = out.replace(
        /(^|[.!?]\s+|\n)\s*(?:note\s*:\s*)?(?:based on\s+)?(?:according to\s+)?(?:the\s+)?retrieved\s+(?:study\s+)?(?:context|materials|passages?|sources?|documents?)[^\n.]*\./gi,
        "$1"
    );
    out = out.replace(
        /(^|[.!?]\s+|\n)\s*(?:note\s*:\s*)?(?:the\s+)?(?:study\s+)?sources\s+are\s+insufficient[^\n.]*\./gi,
        "$1"
    );
    out = out.replace(
        /(^|[.!?]\s+|\n)\s*(?:note\s*:\s*)?(?:based on\s+)?(?:according to\s+)?(?:the\s+)?retrieved\s+(?:study\s+)?(?:context|materials|passages?|sources?|documents?),?\s*/gi,
        "$1"
    );
    out = out.replace(/\n{3,}/g, "\n\n");
    return out;
}

function unescapeMarkdownPunct(s) {
    // Kept for compatibility. The inline renderer handles escapes now;
    // this is only used for block-detection normalization.
    return s.replace(/\\([\\!"#$%&'()*+,\-./:;<=>?@[\\\]^_`{|}~])/g, "$1");
}

function _normalizeEmphasisSpacing(text) {
    // Insert a space between a word character and an emphasis marker when
    // the two are glued together (e.g. "the**Agile**model"). Punctuation,
    // parentheses, brackets and whitespace are left untouched so we never
    // add a space before a comma or period.
    var out = text.replace(/([A-Za-z0-9])(\*{1,3})/g, "$1 $2");
    out = out.replace(/(\*{1,3})([A-Za-z0-9])/g, "$1 $2");
    out = out.replace(/([A-Za-z0-9])(_{1,3})/g, "$1 $2");
    out = out.replace(/(_{1,3})([A-Za-z0-9])/g, "$1 $2");
    return out;
}

function renderInlineText(text) {
    if (!text) {
        return "";
    }
    var store = [];
    function stash(value) {
        store.push(value);
        return "\uE000" + (store.length - 1) + "\uE000";
    }

    // 1. Protect inline code, math and safe links so emphasis rules never
    //    touch them.
    text = text.replace(/`[^`\n]+`/g, function (match) {
        return stash("<code>" + match.slice(1, -1) + "</code>");
    });
    text = text.replace(/\$\$[\s\S]*?\$\$/g, function (match) {
        return stash(match);
    });
    text = text.replace(/\$[^$\n]+\$/g, function (match) {
        return stash(match);
    });
    text = text.replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g,
        function (match, label, url) {
            var safeUrl = url.replace(/"/g, "%22");
            return stash('<a href="' + safeUrl +
                '" target="_blank" rel="noopener">' + label + '</a>');
        });

    // 2. Protect escaped punctuation as literal characters.
    text = text.replace(/\\([\\`*_{}\[\]#+\-.!~|>])/g, function (match, ch) {
        return stash(ch);
    });

    // 3. Emphasis (triple first, then double, then single).
    text = text.replace(/\*\*\*(?=\S)([\s\S]*?\S)\*\*\*/g, function (match, inner) {
        return '<strong><em>' + renderInlineText(inner) + '</em></strong>';
    });
    text = text.replace(/\*\*(?=\S)([\s\S]*?\S)\*\*/g, function (match, inner) {
        return '<strong>' + renderInlineText(inner) + '</strong>';
    });
    text = text.replace(/\*([^*\n]+?)\*/g,
        function (match, inner) {
            return '<em>' + renderInlineText(inner) + '</em>';
        });
    text = text.replace(/___(?=\S)([\s\S]*?\S)___/g, function (match, inner) {
        return '<strong><em>' + renderInlineText(inner) + '</em></strong>';
    });
    text = text.replace(/__(?=\S)([\s\S]*?\S)__/g, function (match, inner) {
        return '<strong>' + renderInlineText(inner) + '</strong>';
    });
    text = text.replace(/(^|[\s(])_([^_\n]+?)_(?=[\s).,;:!?]|$)/g,
        function (match, prefix, inner) {
            return prefix + '<em>' + renderInlineText(inner) + '</em>';
        });

    // 4. Restore protected content.
    text = text.replace(/\uE000(\d+)\uE000/g, function (match, index) {
        return store[parseInt(index, 10)];
    });

    // 5. Add spaces between word characters and emphasis tags. This is
    //    done on the generated HTML so punctuation, parentheses and
    //    brackets are never given a bogus leading space.
    text = text.replace(/([A-Za-z0-9])<strong>/g, "$1 <strong>");
    text = text.replace(/<\/strong>([A-Za-z0-9])/g, "</strong> $1");
    text = text.replace(/([A-Za-z0-9])<em>/g, "$1 <em>");
    text = text.replace(/<\/em>([A-Za-z0-9])/g, "</em> $1");
    return text;
}

function renderInline(text) {
    return renderInlineText(text);
}

function _isTableSeparator(line) {
    return /^\|?[\s:|-]+\|[\s:|.-]*$/.test(line) && line.indexOf("-") !== -1;
}

function _renderListTree(items) {
    if (!items.length) {
        return "";
    }
    var root = { children: [] };
    var stack = [{ indent: -1, node: root }];
    items.forEach(function (item) {
        while (stack.length > 1) {
            var peek = stack[stack.length - 1];
            if (peek.node.tag) {
                if (item.indent < peek.indent) {
                    stack.pop();
                    continue;
                }
                break;
            }
            if (item.indent <= peek.indent) {
                stack.pop();
                continue;
            }
            break;
        }
        var top = stack[stack.length - 1];
        if (top.node.tag && item.indent <= top.indent) {
            var existing = { text: item.text, children: [] };
            top.node.children.push(existing);
            stack.push({ indent: item.indent, node: existing });
            return;
        }
        if (item.indent > top.indent) {
            var list = {
                tag: item.ordered ? "ol" : "ul",
                start: item.number,
                children: []
            };
            top.node.children.push(list);
            stack.push({ indent: item.indent, node: list });
            top = stack[stack.length - 1];
        }
        var node = { text: item.text, children: [] };
        top.node.children.push(node);
        stack.push({ indent: item.indent, node: node });
    });

    function renderChildren(children) {
        var out = "";
        children.forEach(function (child) {
            if (child.tag) {
                out += renderListNode(child);
            } else {
                out += "<li>" + (child.text ? renderInline(child.text) : "") +
                    renderChildren(child.children) + "</li>";
            }
        });
        return out;
    }
    function renderListNode(node) {
        var startAttr = (node.start && node.start > 1)
            ? ' start="' + node.start + '"' : "";
        return "<" + node.tag + startAttr + ">" +
            renderChildren(node.children) + "</" + node.tag + ">";
    }
    return renderChildren(root.children);
}

function renderMarkdown(text) {
    // Small block renderer for model answers: fenced code, headings,
    // bullet/numbered/nested lists, tables, blockquotes, rules,
    // paragraphs. Fenced blocks are stashed raw so entities inside them
    // are preserved; the remaining text is decoded once, internal
    // commentary is removed, and only then escaped for HTML.
    var fenceStore = [];
    var remainder = String(text || "").replace(/```[\s\S]*?(?:```|$)/g,
        function (block) {
            fenceStore.push(block);
            return "\uE000F" + (fenceStore.length - 1) + "\uE000";
        });

    var decoded = decodeSafeEntities(remainder);
    var normalized = stripInternalCommentary(decoded);
    var lines = escapeHtml(normalized).split("\n");
    var html = [];
    var paraBuf = [];
    var listBuf = [];
    var tableBuf = [];
    var quoteBuf = [];

    function flushPara() {
        if (paraBuf.length) {
            html.push("<p>" + renderInline(paraBuf.join("<br>")) + "</p>");
            paraBuf = [];
        }
    }
    function flushList() {
        if (!listBuf.length) {
            return;
        }
        html.push(_renderListTree(listBuf));
        listBuf = [];
    }
    function flushTable() {
        if (!tableBuf.length) {
            return;
        }
        var rows = tableBuf.filter(function (line) {
            return !_isTableSeparator(line);
        });
        if (rows.length < 2) {
            paraBuf = paraBuf.concat(tableBuf);
            tableBuf = [];
            flushPara();
            return;
        }
        var out = ["<table>"];
        rows.forEach(function (line, index) {
            var cells = line.replace(/^\||\|$/g, "").split("|");
            var tag = index === 0 ? "th" : "td";
            out.push("<tr>" + cells.map(function (cell) {
                return "<" + tag + ">" + renderInline(cell.trim()) +
                    "</" + tag + ">";
            }).join("") + "</tr>");
        });
        out.push("</table>");
        html.push(out.join(""));
        tableBuf = [];
    }
    function flushQuote() {
        if (!quoteBuf.length) {
            return;
        }
        var inner = quoteBuf.map(function (line) {
            return renderInline(line);
        }).join("<br>");
        html.push("<blockquote>" + inner + "</blockquote>");
        quoteBuf = [];
    }

    for (var i = 0; i < lines.length; i++) {
        var line = lines[i];
        var fenceMatch = line.match(/^\uE000F(\d+)\uE000$/);
        if (fenceMatch) {
            flushPara();
            flushList();
            flushTable();
            flushQuote();
            html.push(line);
            continue;
        }

        var trimmed = line.trim();
        if (!trimmed) {
            flushPara();
            flushList();
            flushTable();
            flushQuote();
            continue;
        }

        if (trimmed.indexOf(">") === 0) {
            flushPara();
            flushList();
            flushTable();
            quoteBuf.push(trimmed.replace(/^>\s?/, ""));
            continue;
        }
        if (quoteBuf.length) {
            flushQuote();
        }

        if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
            flushPara();
            flushList();
            flushTable();
            html.push("<hr>");
            continue;
        }

        var heading = trimmed.match(/^(#{1,6})\s+(.*)$/);
        if (heading) {
            flushPara();
            flushList();
            flushTable();
            var level = heading[1].length;
            html.push("<h" + level + ">" + renderInline(heading[2]) +
                "</h" + level + ">");
            continue;
        }

        if (trimmed.indexOf("|") !== -1) {
            var isSep = _isTableSeparator(trimmed);
            var nextIsSep = (i + 1 < lines.length) &&
                _isTableSeparator(lines[i + 1].trim());
            if (isSep || nextIsSep || tableBuf.length) {
                flushPara();
                flushList();
                flushQuote();
                tableBuf.push(trimmed);
                continue;
            }
        }

        var bullet = trimmed.match(/^([-*+])\s+(.*)$/);
        var ordered = trimmed.match(/^(\d{1,9})[.)]\s+(.*)$/);
        if (bullet || ordered) {
            flushPara();
            flushTable();
            flushQuote();
            var indent = line.match(/^[\t ]*/)[0]
                .replace(/\t/g, "    ").length;
            listBuf.push({
                indent: indent,
                ordered: !!ordered,
                number: ordered ? parseInt(ordered[1], 10) : null,
                text: bullet ? bullet[2] : ordered[2]
            });
            continue;
        }

        flushList();
        flushTable();
        flushQuote();
        paraBuf.push(trimmed);
    }

    flushPara();
    flushList();
    flushTable();
    flushQuote();

    var out = html.join("\n") || "<p></p>";
    out = out.replace(/\uE000F(\d+)\uE000/g, function (match, index) {
        var raw = fenceStore[parseInt(index, 10)] || "";
        var inner = raw.replace(/^```[^\n]*\n?/, "")
            .replace(/```\s*$/, "")
            .replace(/\n$/, "");
        return "<pre><code>" + escapeHtml(inner) + "</code></pre>";
    });
    return out;
}

function formatReply(text) {
    // System-generated citation markers are stripped before Markdown
    // rendering so they never appear while streaming, after completion,
    // or in re-rendered answers. Entity decoding, internal-commentary
    // removal and Markdown-aware spacing all happen in renderMarkdown.
    var stripped = stripSystemCitations(text);
    return renderMarkdown(stripped);
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
    if (conversationHistory.length > 0) {
        payload.history = conversationHistory.slice(-6);
    }
    if (recentTopics.length > 0) {
        payload.recent_topics = recentTopics.slice(-10);
    }
    if (displayedSuggestions.length > 0) {
        payload.recent_suggestions = displayedSuggestions.slice(-20);
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
        bits.push("⚠ fallback — AI unavailable" +
            (info.error_code ? " (" + info.error_code + ")" : ""));
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
    const suggestionSeq = ++latestSuggestionSeq;
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
                        cached: false
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
            if (suggestionSeq === latestSuggestionSeq) {
                clearFollowupSuggestions();
                addFollowupSuggestions(FALLBACK_SUGGESTIONS);
            }
        }
    } finally {
        setBusy(false);
        currentAborter = null;
        scrollChat();
    }

    if (streamed && fullText) {
        addMessageActions(thinking, function () { return fullText; });
        conversationHistory.push({ role: "assistant", content: fullText });
        // Track the current question topic for dedup
        recentTopics.push(message);
        // Render follow-up suggestions if provided (fallback when empty).
        var suggestionsToRender = (serverSuggestions && serverSuggestions.length > 0)
            ? serverSuggestions
            : FALLBACK_SUGGESTIONS;
        clearFollowupSuggestions();
        if (suggestionSeq === latestSuggestionSeq) {
            addFollowupSuggestions(suggestionsToRender);
            displayedSuggestions = displayedSuggestions.concat(suggestionsToRender).slice(-20);
        }
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
    // Also remove source citations and follow-up suggestions.
    messages.querySelectorAll(".source-citations").forEach(function (el) {
        el.remove();
    });
    messages.querySelectorAll(".followup-suggestions").forEach(function (el) {
        el.remove();
    });
    // Reset conversation history and recent topics.
    conversationHistory = [];
    recentTopics = [];
    displayedSuggestions = [];
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
