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
// Attachments staged by the "+" menu, bound to the next sent message.
var pendingAttachments = [];
var _attachmentSeq = 0;
var plusMenuOpen = false;
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

function addUserMessage(text, attachments) {
    const messages = document.getElementById("chatMessages");
    const contentEl = document.createElement("div");
    contentEl.className = "message-content";
    contentEl.innerHTML =
        "<strong>You</strong><p>" +
        escapeHtml(text) +
        "</p>";
    if (attachments && attachments.length > 0) {
        const tray = document.createElement("div");
        tray.className = "message-attachments";
        attachments.forEach(function (att) {
            const chip = document.createElement("span");
            chip.className = "sent-attachment";
            chip.textContent =
                (att.kind === "library" ? "📚 " : "📎 ") + att.name;
            tray.appendChild(chip);
        });
        contentEl.appendChild(tray);
    }
    const el = document.createElement("div");
    el.className = "message user-message";
    el.appendChild(contentEl);
    el.insertAdjacentHTML(
        "beforeend",
        '<div class="message-avatar user-avatar">V</div>'
    );
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
        .replace(/\\\([\s\S]*?\\\)/g, function (match) {
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

/* ============================================================
   LaTeX-lite math renderer
   ============================================================ */

var _MATH_SYMBOLS = {
    rightarrow: "→", to: "→", leftarrow: "←", Leftarrow: "⇐",
    Rightarrow: "⇒", leftrightarrow: "↔", Leftrightarrow: "⇔",
    mapsto: "↦", uparrow: "↑", downarrow: "↓",
    times: "×", cdot: "·", div: "÷", pm: "±", mp: "∓",
    leq: "≤", le: "≤", geq: "≥", ge: "≥", neq: "≠", ne: "≠",
    approx: "≈", equiv: "≡", propto: "∝", infty: "∞",
    sum: "Σ", prod: "Π", int: "∫", partial: "∂", nabla: "∇",
    alpha: "α", beta: "β", gamma: "γ", delta: "δ", epsilon: "ε",
    varepsilon: "ε", zeta: "ζ", eta: "η", theta: "θ", iota: "ι",
    kappa: "κ", lambda: "λ", mu: "μ", nu: "ν", xi: "ξ", pi: "π",
    rho: "ρ", sigma: "σ", tau: "τ", phi: "φ", varphi: "ϕ", chi: "χ",
    psi: "ψ", omega: "ω", Gamma: "Γ", Delta: "Δ", Theta: "Θ",
    Lambda: "Λ", Xi: "Ξ", Pi: "Π", Sigma: "Σ", Phi: "Φ", Psi: "Ψ",
    Omega: "Ω",
    in: "∈", notin: "∉", subset: "⊂", subseteq: "⊆",
    cup: "∪", cap: "∩", emptyset: "∅", forall: "∀", exists: "∃",
    neg: "¬", land: "∧", lor: "∨", lnot: "¬",
    implies: "⇒", iff: "⇔",
    ldots: "…", dots: "…", cdots: "⋯", prime: "′",
    degree: "°", perp: "⊥", ell: "ℓ", hbar: "ℏ",
    aleph: "ℵ", Re: "ℜ", Im: "ℑ"
};

// Sentinel characters that never appear in normal model text.
var _MATH_SENTINEL = "\uE001";

function _looksLikeMath(body) {
    // Treat a $…$ fragment as math ONLY when it contains LaTeX-ish
    // syntax. Ordinary amounts ("It costs $5 and $3") never match and
    // stay literal text, so currency is never corrupted.
    return /\\[a-zA-Z]/.test(body)
        || /[\^_]/.test(body)
        || /[=+<>]|≤|≥|≠|→|←|↔|×|÷|±|Σ|√/.test(body);
}

function _mathEscape(text) {
    return String(text)
        .replace(/&(?!(?:[a-zA-Z]+|#\d+|#[xX][0-9a-fA-F]+);)/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function _renderMathInner(tex) {
    var out = String(tex);
    // Content is emitted as HTML — escape raw markup characters first.
    // The ampersand guard is entity-aware, so already-encoded content
    // (from the block-level escape pass) is not double-escaped.
    out = _mathEscape(out);
    // 1. \frac{num}{den} — loop so several fractions in one body all
    //    convert (nested fractions converge in bounded iterations).
    var fracGuard = 0;
    while (/\\frac\{([^{}]*)\}\{([^{}]*)\}/.test(out) && fracGuard < 50) {
        fracGuard += 1;
        out = out.replace(/\\frac\{([^{}]*)\}\{([^{}]*)\}/g,
            function (_match, num, den) {
                return '<span class="math-frac">'
                    + '<span class="math-frac-top">'
                    + _renderMathInner(num) + "</span>"
                    + '<span class="math-frac-bottom">'
                    + _renderMathInner(den) + "</span></span>";
            });
    }
    // 2. \sqrt{rad} and bare \sqrt.
    out = out.replace(/\\sqrt\{([^{}]*)\}/g, function (_match, rad) {
        return "√(" + _renderMathInner(rad) + ")";
    });
    out = out.replace(/\\sqrt([^\\a-zA-Z0-9{}])/g, "√$1");
    // 3. Symbol commands (\rightarrow, \times, Greek letters, …).
    out = out.replace(/\\([a-zA-Z]+)/g, function (match, name) {
        return Object.prototype.hasOwnProperty.call(_MATH_SYMBOLS, name)
            ? _MATH_SYMBOLS[name] : match;
    });
    // 4. Left/right sizing markers carry no meaning here.
    out = out.replace(/\\left|\\right/g, "");
    // 5. Sub/superscripts: brace form first, then a single token.
    out = out.replace(/_\{([^{}]*)\}/g, function (_match, inner) {
        return "<sub>" + inner + "</sub>";
    });
    out = out.replace(/\^\{([^{}]*)\}/g, function (_match, inner) {
        return "<sup>" + inner + "</sup>";
    });
    out = out.replace(/_([0-9a-zA-Z])/g, "<sub>$1</sub>");
    out = out.replace(/\^([0-9a-zA-Z])/g, "<sup>$1</sup>");
    return out;
}

function _renderMath(tex) {
    return _renderMathInner(tex);
}

/* ---------- Inline renderer ---------- */

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
    //    touch them. Math bodies are stored with a sentinel so the
    //    restore step renders them as real symbols; the bare $…$ form
    //    requires LaTeX-ish content so prose like "It costs $5 and $3"
    //    stays literal text.
    text = text.replace(/`[^`\n]+`/g, function (match) {
        return stash("<code>" + match.slice(1, -1) + "</code>");
    });
    text = text.replace(/\\\(([\s\S]*?)\\\)/g,
        function (_match, body) {
            return stash(_MATH_SENTINEL + body + _MATH_SENTINEL);
        });
    text = text.replace(/\$\$([^$\n]+?)\$\$/g,
        function (_match, body) {
            return stash(_MATH_SENTINEL + body + _MATH_SENTINEL);
        });
    text = text.replace(/\$([^$\n]+?)\$/g, function (match, body) {
        if (!_looksLikeMath(body)) {
            return match;   // ordinary text — do not corrupt
        }
        return stash(_MATH_SENTINEL + body + _MATH_SENTINEL);
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

    // 4. Restore protected content. Sentinelled bodies are rendered as
    //    real math; plain stashes (code, links, escapes) come back as-is.
    text = text.replace(/\uE000(\d+)\uE000/g, function (match, index) {
        var value = store[parseInt(index, 10)] || "";
        if (value.charAt(0) === _MATH_SENTINEL &&
                value.charAt(value.length - 1) === _MATH_SENTINEL) {
            return _renderMath(value.slice(1, -1));
        }
        return value;
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
    var displayStore = [];
    var remainder = String(text || "").replace(/```[\s\S]*?(?:```|$)/g,
        function (block) {
            fenceStore.push(block);
            return "\uE000F" + (fenceStore.length - 1) + "\uE000";
        });
    // Display math is stashed before block parsing so multi-line
    // formulas survive blank-line splitting (and so Markdown rules
    // never touch LaTeX backslashes). Only pair-terminated forms are
    // captured: a half-streamed "$$E = m" opener stays literal until
    // the finished answer re-renders — legible, never corrupted, and
    // never swallowing the rest of the text.
    remainder = remainder.replace(/\$\$([^$]+)\$\$/g, function (_match, body) {
        displayStore.push(body);
        return "\n\uE000B" + (displayStore.length - 1) + "\uE000\n";
    });
    remainder = remainder.replace(/\\\[([\s\S]*?)\\\]/g,
        function (_match, body) {
            displayStore.push(body);
            return "\n\uE000B" + (displayStore.length - 1) + "\uE000\n";
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
        // Wrapped so wide tables scroll horizontally on small screens
        // instead of overflowing the bubble (see .table-wrap CSS).
        html.push('<div class="table-wrap">' + out.join("") + "</div>");
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
        var displayMatch = !fenceMatch &&
            line.match(/^\uE000B(\d+)\uE000$/);
        if (fenceMatch || displayMatch) {
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
    // Display math: own-line forms become centered blocks; any token
    // that survived inside a paragraph line still becomes a valid
    // inline-block span (never a <div> inside <p>).
    out = out.replace(/\uE000B(\d+)\uE000/g, function (_match, index) {
        var body = displayStore[parseInt(index, 10)] || "";
        return '<div class="math-display">' + _renderMath(body) + "</div>";
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
    if (pendingAttachments.length > 0) {
        payload.attachments = pendingAttachments.map(function (att) {
            if (att.kind === "library") {
                return {
                    type: "library",
                    document_id: att.documentId,
                    name: att.name
                };
            }
            return {
                type: "file",
                name: att.name,
                size: att.size,
                text: att.text
            };
        });
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
    const sentAttachments = pendingAttachments.slice();
    addUserMessage(message, sentAttachments);
    conversationHistory.push({ role: "user", content: message });
    input.value = "";
    input.focus();

    // Attachments belong to exactly this message; clear the tray now.
    pendingAttachments = [];
    renderChipTray();

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
    let renderTimer = null;
    let terminalRendered = false;

    // During streaming, re-rendering the full markdown on EVERY token
    // re-parses a growing document (O(n^2) on long answers) and can
    // jank on slower devices. A ~90ms cadence stays visually
    // continuous while capping the render rate; the final render in
    // the finally block below still draws the finished answer exactly
    // once.
    const renderStreamed = function () {
        if (renderTimer) {
            return;
        }
        renderTimer = setTimeout(function () {
            renderTimer = null;
            contentP.innerHTML = formatReply(fullText);
            scrollChat();
        }, 90);
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
                    // Retrieved context arrived: swap the waiting
                    // indicator copy (identical .typing markup and
                    // styling) so the wait state says what is actually
                    // happening — reading the retrieved materials.
                    if (!fullText && contentP.querySelector(".typing")) {
                        contentP.innerHTML =
                            '<p class="typing">Reading your study materials' +
                            '<span>.</span><span>.</span><span>.</span></p>';
                    }
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
            terminalRendered = true;
            lastFailedMessage = message;
            return; // finally{} does the busy/aborter/scroll cleanup
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
            terminalRendered = true;
            // A failed exchange must not stay in the prompt history:
            // retryMessage() resubmits it, and stale duplicates would
            // bloat later prompts and change the effective cache key.
            const tail = conversationHistory[conversationHistory.length - 1];
            if (tail && tail.role === "user" && tail.content === message) {
                conversationHistory.pop();
            }
            if (suggestionSeq === latestSuggestionSeq) {
                clearFollowupSuggestions();
                addFollowupSuggestions(FALLBACK_SUGGESTIONS);
            }
        }
    } finally {
        // Cancel any pending throttled render, then draw the finished
        // answer exactly once (a token may have landed inside the last
        // throttle window).
        if (renderTimer) {
            clearTimeout(renderTimer);
            renderTimer = null;
        }
        if (fullText && streamed && !terminalRendered) {
            contentP.innerHTML = formatReply(fullText);
        }
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
    // Warm the study library during idle time after the page settles,
    // so opening the picker is instant instead of a round trip.
    window.setTimeout(prefetchLibrary, 400);
});

/* ============================================================
   "+" MENU — attachments, library picker, capability notices
   ============================================================ */

var _CHAT_FILE_MAX_BYTES = 10 * 1024 * 1024;   // matches backend limit
var _CHAT_MAX_ATTACHMENTS = 3;                 // matches backend limit

var _CHAT_TEXT_EXTENSIONS =
    /\.(pdf|txt|md|csv|doc|docx|ppt|pptx|xlsx)$/i;
var _CHAT_IMAGE_EXTENSIONS = /\.(png|jpe?g|gif|webp)$/i;

var _libraryCache = null;       // metadata only, reused for the page's lifetime
var _libraryAborter = null;     // in-flight request; aborted when the dialog closes

/* ---------- Menu open / close, keyboard and outside click ---------- */

function plusMenuEl() {
    return document.getElementById("plusMenu");
}

/* Single source of truth for the toggle button: menu state drives the
   ✕/"+" icon (the .open rotation), aria-expanded and the accessible
   name together, so they can never drift apart. aria-label changes the
   screen-reader name only — no visible tooltip is attached. */
function _syncPlusButton(open) {
    const button = document.getElementById("plusButton");
    if (!button) {
        return;
    }
    button.classList.toggle("open", !!open);
    button.setAttribute("aria-expanded", open ? "true" : "false");
    button.setAttribute("aria-label", open ? "Close menu" : "Open menu");
}

function togglePlusMenu(event) {
    if (event) {
        // Never let the toggle click reach the outside-click closer —
        // that would close the menu twice in one click.
        event.stopPropagation();
    }
    if (plusMenuOpen) {
        closePlusMenu();
        return;
    }
    closePlusToast();
    const menu = plusMenuEl();
    menu.hidden = false;
    menu.style.display = "flex";
    plusMenuOpen = true;
    _syncPlusButton(true);
    const first = menu.querySelector(".plus-menu-item");
    if (first) {
        first.focus();
    }
    // Idempotent (re)binding — removal first, so exactly one outside
    // click and one Escape handler exist no matter how often the
    // toggle cycles.
    document.removeEventListener("click", _plusOutsideClick);
    document.addEventListener("click", _plusOutsideClick);
    document.removeEventListener("keydown", _plusKeydown);
    document.addEventListener("keydown", _plusKeydown);
}

function closePlusMenu(refocus) {
    const menu = plusMenuEl();
    if (menu) {
        // Effective because of the .plus-menu[hidden] CSS guard.
        menu.hidden = true;
        menu.style.display = "";
    }
    plusMenuOpen = false;
    _syncPlusButton(false);
    if (refocus) {
        const button = document.getElementById("plusButton");
        if (button) {
            button.focus();
        }
    }
    document.removeEventListener("click", _plusOutsideClick);
    document.removeEventListener("keydown", _plusKeydown);
}

function _plusOutsideClick(event) {
    if (plusMenuEl().contains(event.target) ||
        event.target === document.getElementById("plusButton")) {
        return;
    }
    closePlusMenu();
}

function _plusKeydown(event) {
    if (event.key === "Escape") {
        event.stopPropagation();
        event.preventDefault();
        closePlusMenu(true);
        return;
    }
    if (event.key === "Tab") {
        // Keep focus cycling inside the open menu.
        const items = plusMenuEl().querySelectorAll(".plus-menu-item");
        if (!items.length) {
            return;
        }
        const firstItem = items[0];
        const lastItem = items[items.length - 1];
        if (event.shiftKey && document.activeElement === firstItem) {
            event.preventDefault();
            lastItem.focus();
        } else if (!event.shiftKey &&
                document.activeElement === lastItem) {
            event.preventDefault();
            firstItem.focus();
        }
    }
}

/* Show an honest capability notice for unconfigured options. */
var _toastTimer = null;

function showPlusToast(text) {
    closePlusToast();
    const inputBox = document.getElementById("inputBox");
    const toast = document.createElement("div");
    toast.className = "plus-toast";
    toast.id = "plusToast";
    toast.setAttribute("role", "status");
    toast.textContent = text;
    if (inputBox) {
        inputBox.appendChild(toast);
    } else {
        document.body.appendChild(toast);
    }
    _toastTimer = setTimeout(closePlusToast, 5000);
}

function closePlusToast() {
    const toast = document.getElementById("plusToast");
    if (toast) {
        toast.remove();
    }
    if (_toastTimer) {
        clearTimeout(_toastTimer);
        _toastTimer = null;
    }
}

var _UNSUPPORTED_OPTIONS = {
    image: "Image generation is not available: none of the configured "
        + "AI providers support image creation. Ask a study question "
        + "instead — text answers work as usual.",
    search: "Web search is not available: this deployment has no web "
        + "search backend configured. Answers still use your subjects' "
        + "study material and general knowledge.",
    research: ("Deep research is not available: no research workflow is "
        + "configured in this deployment. "
        + "The Detailed mode gives step-by-step answers."),
    sketch: ("Sketch is not available in this build: no drawing editor "
        + "is configured, and current providers cannot analyse images."),
    thinking: ("Thinking mode is not available: the configured AI "
        + "model does not support dedicated reasoning controls. "
        + "Use Detailed mode for step-by-step answers."),
    tools: ("No external tools are connected. The study library, "
        + "RAG retrieval and the AI chat are the active capabilities.")
};

function choosePlusAction(action) {
    closePlusMenu();   // outside-click listener is removed here
    if (action === "files") {
        document.getElementById("fileInput").click();
        return;
    }
    if (action === "library") {
        openLibrary();
        return;
    }
    if (Object.prototype.hasOwnProperty.call(_UNSUPPORTED_OPTIONS, action)) {
        showPlusToast(_UNSUPPORTED_OPTIONS[action]);
        return;
    }
    showPlusToast("That option is not available.");
}

/* ---------- File attachments ---------- */

function _formatBytes(bytes) {
    if (typeof bytes !== "number" || bytes < 0) {
        return "";
    }
    if (bytes < 1024) {
        return bytes + " B";
    }
    if (bytes < 1024 * 1024) {
        return (bytes / 1024).toFixed(1) + " KB";
    }
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

function handleFilesChosen(input) {
    const picked = Array.from(input.files || []);
    input.value = "";   // allow re-picking the same file
    picked.forEach(function (file) {
        uploadChatFile(file);
    });
}

function uploadChatFile(file) {
    if (pendingAttachments.length >= _CHAT_MAX_ATTACHMENTS) {
        showPlusToast("Up to " + _CHAT_MAX_ATTACHMENTS
            + " attachments per message.");
        return;
    }
    const lower = file.name.toLowerCase();
    if (!_CHAT_TEXT_EXTENSIONS.test(lower) &&
            !_CHAT_IMAGE_EXTENSIONS.test(lower)) {
        showPlusToast("Only PDF, Word, PowerPoint, Excel, text and "
            + "image files can be attached.");
        return;
    }
    if (file.size > _CHAT_FILE_MAX_BYTES) {
        showPlusToast('"' + file.name + '" is larger than the 10 MB limit.');
        return;
    }

    const attId = "att" + (++_attachmentSeq);
    const isImage = _CHAT_IMAGE_EXTENSIONS.test(lower);
    const chip = {
        kind: "file",
        id: attId,
        name: file.name,
        size: file.size,
        status: "busy",
        note: isImage ? "Reading…" : "Extracting text…"
    };
    pendingAttachments.push(chip);
    renderChipTray();

    const data = new FormData();
    data.append("file", file, file.name);

    fetch("/api/chat/attachments", { method: "POST", body: data })
        .then(function (response) {
            return response.json().then(function (json) {
                return { ok: response.ok, json: json };
            });
        })
        .then(function (result) {
            const chipLive = pendingAttachments.find(function (a) {
                return a.id === attId;
            });
            if (!chipLive) {
                return;   // removed while uploading
            }
            if (!result.ok || !result.json || !result.json.ok) {
                chipLive.status = "failed";
                chipLive.note = (result.json && result.json.error)
                    || "Upload failed.";
                chipLive.text = "";
                renderChipTray();
                if (result.json && result.json.error) {
                    showPlusToast(result.json.error);
                }
                return;
            }
            const uploaded = result.json.attachment;
            chipLive.status = "ready";
            chipLive.note = "";
            chipLive.text = uploaded.text || "";
            chipLive.size = uploaded.size || chipLive.size;
            if (result.json.unavailable) {
                chipLive.note = result.json.unavailable;
                chipLive.status = "failed";
                chipLive.text = "";
            } else if (uploaded.truncated) {
                chipLive.note = "Excerpt truncated (long file)";
            }
            renderChipTray();
        })
        .catch(function () {
            const chipLive = pendingAttachments.find(function (a) {
                return a.id === attId;
            });
            if (chipLive) {
                chipLive.status = "failed";
                chipLive.note = "Upload failed — check connection.";
                chipLive.text = "";
                renderChipTray();
            }
        });
}

function removeAttachment(id) {
    pendingAttachments = pendingAttachments.filter(function (a) {
        return a.id !== id;
    });
    renderChipTray();
}

function _escapeAttr(value) {
    return escapeHtml(String(value || ""));
}

function renderChipTray() {
    const tray = document.getElementById("chipTray");
    if (!tray) {
        return;
    }
    tray.innerHTML = "";
    if (!pendingAttachments.length) {
        tray.hidden = true;
        return;
    }
    tray.hidden = false;
    pendingAttachments.forEach(function (att) {
        const chip = document.createElement("span");
        chip.className = "attachment-chip";
        if (att.status === "busy") {
            chip.classList.add("is-busy");
        } else if (att.status === "failed") {
            chip.classList.add("is-failed");
        }
        const icon = document.createElement("span");
        icon.className = "chip-icon";
        icon.textContent = att.kind === "library" ? "📚" : "📎";
        const meta = document.createElement("span");
        meta.className = "chip-name";
        meta.textContent = att.name +
            (att.note ? " — " + att.note : "") +
            (att.kind === "file" && att.size ? "" : "");
        const size = document.createElement("span");
        size.className = "chip-size";
        size.textContent = _formatBytes(att.size);
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "chip-remove";
        remove.setAttribute("aria-label",
            "Remove attachment " + att.name);
        remove.textContent = "✕";
        remove.onclick = function () {
            removeAttachment(att.id);
        };
        chip.appendChild(icon);
        chip.appendChild(meta);
        chip.appendChild(size);
        chip.appendChild(remove);
        tray.appendChild(chip);
    });
}

/* ---------- Library picker ---------- */

function _libraryStopFetch() {
    if (_libraryAborter) {
        _libraryAborter.abort();
        _libraryAborter = null;
    }
}

/* Warm the library metadata in idle time after the chat page loads, so
   opening the dialog is instant instead of paying one round trip to the
   database per first open. One request total: the in-flight guard in
   startLibraryLoad makes a later openLibrary() reuse the same attempt,
   never stacking duplicates. */
function prefetchLibrary() {
    if (_libraryCache || _libraryAborter) {
        return;   // already available or already loading
    }
    const list = document.getElementById("libraryList");
    if (list) {
        startLibraryLoad(list);
    }
}

function openLibrary() {
    const overlay = document.getElementById("libraryOverlay");
    if (!overlay) {
        return;
    }
    overlay.hidden = false;
    const list = document.getElementById("libraryList");
    const search = document.getElementById("librarySearch");
    if (search) {
        search.value = "";
    }

    if (_libraryCache) {
        renderLibrary(_libraryCache);
    } else {
        // No cached copy yet: show the loading state and attach to an
        // in-flight (likely prefetched) request, or start a fresh one.
        // A failed attempt is never sticky: closing and reopening
        // always retries cleanly.
        if (list) {
            list.innerHTML = (
                '<p class="library-loading"><span class="library-spinner" '
                + 'aria-hidden="true"></span>Loading library…</p>'
            );
        }
        prefetchLibrary();
    }

    // (Re-)binding is idempotent: removal first, so exactly one Escape
    // handler exists no matter how often the dialog opens.
    document.removeEventListener("keydown", _libraryKeydown);
    document.addEventListener("keydown", _libraryKeydown);
    if (search) {
        search.focus();
    }
}

function startLibraryLoad(list) {
    if (!list || _libraryAborter) {
        // A fetch is already in flight: reuse it (no duplicate requests
        // when the dialog opens repeatedly or prefetch already ran).
        return;
    }
    const overlay = document.getElementById("libraryOverlay");
    const aborter = new AbortController();
    _libraryAborter = aborter;

    // Watchdog: a request that hangs must end in the retry state,
    // never in a spinner that can never stop.
    const watchdog = setTimeout(function () {
        aborter.abort();
    }, 20000);

    const settled = function () {
        clearTimeout(watchdog);
        if (_libraryAborter === aborter) {
            _libraryAborter = null;
        }
    };

    list.innerHTML = (
        '<p class="library-loading"><span class="library-spinner" '
        + 'aria-hidden="true"></span>Loading library…</p>'
    );

    fetch("/api/chat/library", { signal: aborter.signal })
        .then(function (response) {
            if (!response.ok) {
                // An API failure is an error state, never a silent
                // "empty library" success.
                throw new Error("HTTP " + response.status);
            }
            return response.json();
        })
        .then(function (json) {
            settled();
            _libraryCache = (json && Array.isArray(json.documents))
                ? json.documents
                : [];
            if (overlay && !overlay.hidden) {
                renderLibrary(_libraryCache);
            }
        })
        .catch(function () {
            settled();
            if (!overlay || overlay.hidden) {
                // Closed while loading: nothing to update, and the
                // next open starts a fresh attempt.
                return;
            }
            list.innerHTML = (
                '<p class="library-empty">Could not load the library. '
                + 'Check your connection and try again.</p>'
                + '<div class="library-retry-wrap">'
                + '<button type="button" class="library-retry-btn" '
                + 'onclick="retryLibraryLoad()">↻ Try again</button>'
                + '</div>'
            );
        });
}

function retryLibraryLoad() {
    const list = document.getElementById("libraryList");
    if (!list) {
        return;
    }
    startLibraryLoad(list);
}

function closeLibrary() {
    const overlay = document.getElementById("libraryOverlay");
    if (overlay) {
        overlay.hidden = true;
    }
    // Closing is allowed in EVERY state — including while the library
    // request is still in flight or after it failed: nothing here
    // depends on the API. Stop the pending request so no loading
    // continues in the background; the next open retries cleanly.
    _libraryStopFetch();
    document.removeEventListener("keydown", _libraryKeydown);
}

function _libraryKeydown(event) {
    if (event.key === "Escape") {
        event.stopPropagation();
        closeLibrary();
    }
}

function _libraryLabel(doc) {
    const label = doc.filename || doc.title || "Document";
    return label.length > 80 ? label.slice(0, 77) + "..." : label;
}

function renderLibrary(documents) {
    const list = document.getElementById("libraryList");
    if (!list) {
        return;
    }
    list.innerHTML = "";
    if (!documents.length) {
        list.innerHTML =
            '<p class="library-empty">No study documents are '
            + "available in the library yet.</p>";
        return;
    }
    documents.forEach(function (doc) {
        const item = document.createElement("button");
        item.type = "button";
        item.className = "library-item";
        item.setAttribute("data-search", (
            (doc.subject_code || "") + " " +
            (doc.subject_name || "") + " " +
            (doc.title || "") + " " +
            (doc.filename || "")
        ).toLowerCase());

        const badge = document.createElement("span");
        badge.className = "lib-badge";
        badge.textContent = doc.subject_code || "DOC";

        const text = document.createElement("span");
        text.className = "lib-text";

        const title = document.createElement("span");
        title.className = "lib-title";
        title.textContent = _libraryLabel(doc);

        const meta = document.createElement("span");
        meta.className = "lib-meta";
        const modulePart = doc.module_number
            ? " • Module " + doc.module_number : "";
        const pagesPart = doc.page_count
            ? " • " + doc.page_count + " pages" : "";
        meta.textContent = (doc.subject_name || "") + modulePart + pagesPart;

        text.appendChild(title);
        text.appendChild(meta);
        item.appendChild(badge);
        item.appendChild(text);
        item.onclick = function () {
            addLibraryAttachment(doc);
        };
        list.appendChild(item);
    });
}

function filterLibrary() {
    const search = document.getElementById("librarySearch");
    if (!search || !_libraryCache) {
        return;
    }
    const query = search.value.trim().toLowerCase();
    renderLibrary(_libraryCache.filter(function (doc) {
        if (!query) {
            return true;
        }
        const haystack = (
            (doc.subject_code || "") + " " +
            (doc.subject_name || "") + " " +
            (doc.title || "") + " " +
            (doc.filename || "")
        ).toLowerCase();
        return haystack.indexOf(query) !== -1;
    }));
}

function addLibraryAttachment(doc) {
    if (pendingAttachments.length >= _CHAT_MAX_ATTACHMENTS) {
        showPlusToast("Up to " + _CHAT_MAX_ATTACHMENTS
            + " attachments per message.");
        closeLibrary();
        return;
    }
    const already = pendingAttachments.find(function (a) {
        return a.kind === "library" && a.documentId === doc.id;
    });
    if (already) {
        closeLibrary();
        showPlusToast(_libraryLabel(doc) + " is already attached.");
        return;
    }
    pendingAttachments.push({
        kind: "library",
        id: "lib" + (++_attachmentSeq),
        documentId: doc.id,
        name: _libraryLabel(doc),
        size: (doc.page_count || 0) * 1200,   // estimate for display only
        status: "ready",
        note: ""
    });
    renderChipTray();
    closeLibrary();
    document.getElementById("chatInput").focus();
}
