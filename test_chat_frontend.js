// Frontend tests for chat.js (Issue 2 & 3): click-to-submit + Markdown.
// Loads static/js/chat.js in a stubbed DOM and asserts real behavior.
// Run: node test_chat_frontend.js

const fs = require("fs");
const vm = require("vm");
const assert = require("assert");

function makeEl() {
    const el = {
        children: [],
        _html: "",
        _text: "",
        className: "",
        value: "",
        style: {},
        dataset: {},
        appendChild(c) { this.children.push(c); return c; },
        querySelector() { return makeEl(); },
        querySelectorAll() { return []; },
        setAttribute() {},
        remove() {},
        focus() {},
        select() {},
        classList: { toggle() {}, add() {}, remove() {} },
    };
    Object.defineProperty(el, "innerHTML", {
        get() { return this._html; },
        set(v) { this._html = String(v); },
    });
    Object.defineProperty(el, "textContent", {
        // Emulate the browser: reading innerHTML after setting
        // textContent yields the escaped markup.
        get() { return this._text; },
        set(v) {
            this._text = String(v);
            this._html = String(v)
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#39;");
        },
    });
    return el;
}

function makeSandbox(sseChunks) {
    const byId = {};
    const ids = ["chatInput", "chatMessages", "sendButton", "stopButton",
        "engineStatus", "modeLabel"];
    ids.forEach((id) => { byId[id] = makeEl(); });
    const fetchCalls = [];
    const sandbox = {
        console,
        localStorage: { _s: {}, getItem(k) { return this._s[k] ?? null; }, setItem(k, v) { this._s[k] = v; } },
        URLSearchParams,
        URL,
        TextDecoder,
        TextEncoder,
        AbortController,
        navigator: {},
        window: { location: { href: "http://localhost/chat", search: "" }, history: { replaceState() {} } },
        document: {
            getElementById(id) { return byId[id] || makeEl(); },
            createElement() { return makeEl(); },
            querySelectorAll() { return []; },
            addEventListener() {},
        },
        fetch(url, opts) {
            fetchCalls.push({ url, body: JSON.parse(opts.body) });
            const enc = new TextEncoder();
            const bufs = sseChunks.map((s) => enc.encode(s));
            let i = 0;
            return Promise.resolve({
                ok: true,
                body: {
                    getReader() {
                        return {
                            read() {
                                if (i < bufs.length) {
                                    return Promise.resolve({ done: false, value: bufs[i++] });
                                }
                                return new Promise(() => {}); // hang: keeps request "busy"
                            },
                        };
                    },
                },
            });
        },
        setTimeout: (fn) => 0,
    };
    sandbox.window.document = sandbox.document;
    sandbox.globalThis = sandbox;
    return { sandbox, byId, fetchCalls };
}

function loadChat(sandbox) {
    const code = fs.readFileSync("static/js/chat.js", "utf8");
    vm.createContext(sandbox);
    vm.runInContext(code, sandbox, { filename: "chat.js" });
}

const SSE_DONE = (usedAi) =>
    `event: done\ndata: {"used_ai": ${usedAi}, "used_rag": true, "mode": "fast", "latency_ms": 100}\n\n`;
const SSE_SOURCES = `event: sources\ndata: {"sources": []}\n\n`;
const SSE_TOKEN = (t) => `event: token\ndata: {"text": ${JSON.stringify(t)}}\n\n`;

// 1. Clicking a question submits that exact question without Send.
{
    const { sandbox, byId, fetchCalls } = makeSandbox([
        SSE_SOURCES + SSE_TOKEN("Hi. ") + SSE_TOKEN("Done."),
        SSE_DONE(false),
    ]);
    loadChat(sandbox);
    vm.runInContext(`askQuestion("Explain binary search")`, sandbox);
    // sendMessage is async: let microtasks + stream reads flush.
    setTimeout(() => {
        try {
            assert.strictEqual(fetchCalls.length, 1, "exactly one request");
            assert.strictEqual(fetchCalls[0].url, "/api/chat/stream");
            assert.strictEqual(fetchCalls[0].body.message, "Explain binary search");
            const msgs = byId.chatMessages.children;
            const user = msgs.find((m) => m.className.includes("user-message"));
            assert.ok(user, "user question displayed");
            assert.ok(user.innerHTML.includes("Explain binary search"));
            console.log("PASS click submits exact question once + displays it");
        } catch (e) { console.error("FAIL click-submit:", e.message); process.exitCode = 1; }
    }, 50);
}

// 2. Repeated clicks while busy produce no duplicate request.
{
    const { sandbox, fetchCalls } = makeSandbox([]);
    loadChat(sandbox);
    vm.runInContext(`askQuestion("Q one"); askQuestion("Q two");`, sandbox);
    setTimeout(() => {
        try {
            assert.strictEqual(fetchCalls.length, 1, "busy guard blocks dupes");
            console.log("PASS busy guard: one submission for rapid clicks");
        } catch (e) { console.error("FAIL busy-guard:", e.message); process.exitCode = 1; }
    }, 50);
}

// 3. Markdown renders; hostile HTML is escaped.
{
    const { sandbox } = makeSandbox([]);
    loadChat(sandbox);
    const out = vm.runInContext(`formatReply(${JSON.stringify(
        "## Binary Search\n\nBinary search **halves** a `sorted` array.\n\n1. Pick middle\n2. Compare\n\n- fast\n- simple\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n```\nmid = lo+(hi-lo)//2\n```\n\n<script>alert(1)</script>"
    )})`, sandbox);
    try {
        assert.ok(out.includes("<h3>Binary Search</h3>"), "heading");
        assert.ok(out.includes("<ol>") && out.includes("<li>Pick middle</li>"), "ordered list");
        assert.ok(out.includes("<ul>") && out.includes("<li>fast</li>"), "bullets");
        assert.ok(out.includes("<strong>halves</strong>"), "bold");
        assert.ok(out.includes("<code>sorted</code>"), "inline code");
        assert.ok(out.includes("<pre><code>mid = lo+(hi-lo)//2</code></pre>"), "fence");
        assert.ok(out.includes("<table>") && out.includes("<th>A</th>"), "table");
        assert.ok(!out.includes("<script>") && out.includes("&lt;script&gt;"), "xss escaped");
        console.log("PASS markdown renders, hostile HTML escaped");
    } catch (e) { console.error("FAIL markdown:", e.message); process.exitCode = 1; }
}

// 4. submitQuestion is the shared path used by Send-equivalent callers.
{
    const { sandbox, byId, fetchCalls } = makeSandbox([SSE_SOURCES + SSE_TOKEN("ok") + SSE_DONE(true)]);
    loadChat(sandbox);
    vm.runInContext(`submitQuestion("  spaced question  ")`, sandbox);
    setTimeout(() => {
        try {
            assert.strictEqual(fetchCalls.length, 1);
            assert.strictEqual(fetchCalls[0].body.message, "spaced question");
            assert.strictEqual(byId.chatInput.value, "");
            console.log("PASS submitQuestion trims + submits + clears input");
        } catch (e) { console.error("FAIL submitQuestion:", e.message); process.exitCode = 1; }
    }, 50);
}

// 4b. Markdown: soft-wrapped lines stay in one paragraph.
{
    const { sandbox } = makeSandbox([]);
    loadChat(sandbox);
    try {
        const out = vm.runInContext(`formatReply(${JSON.stringify(
            "Waterfall works in sequential phases.\nRequirements flow into design.\n\nAgile welcomes change."
        )})`, sandbox);
        assert.ok(out.includes("<p>Waterfall works in sequential phases. Requirements flow into design.</p>"),
            "related sentences stay together, got: " + out);
        assert.ok(!out.includes("<br>"), "no accidental line breaks, got: " + out);
        assert.strictEqual((out.match(/<p>/g) || []).length, 2, "two paragraphs");
        console.log("PASS paragraphs keep soft-wrapped sentences together");
    } catch (e) { console.error("FAIL paragraphs:", e.message); process.exitCode = 1; }
}

// 4c. Markdown: headings and numbered lists render correctly.
{
    const { sandbox } = makeSandbox([]);
    loadChat(sandbox);
    try {
        const out = vm.runInContext(`formatReply(${JSON.stringify(
            "## Waterfall Steps\n\n1. Gather requirements\n2. Design the system\n3. Test thoroughly"
        )})`, sandbox);
        assert.ok(out.includes("<h3>Waterfall Steps</h3>"), "heading, got: " + out);
        assert.ok(out.includes("<ol>") && out.includes("<li>Gather requirements</li>") &&
            out.includes("<li>Test thoroughly</li>"), "numbered list, got: " + out);
        console.log("PASS headings and numbered lists render");
    } catch (e) { console.error("FAIL headings/lists:", e.message); process.exitCode = 1; }
}

// 5. Fallback status shows no raw error codes or model names.
{
    const { sandbox, byId } = makeSandbox([]);
    loadChat(sandbox);
    try {
        vm.runInContext(`updateStatus({answer_kind: "fallback_excerpts", error_code: "model_not_found", mode: "fast", latency_ms: 1500})`, sandbox);
        const text = byId.engineStatus.textContent;
        assert.ok(text.includes("unavailable"), "friendly fallback label, got: " + text);
        assert.ok(!text.includes("model_not_found"), "no raw code, got: " + text);
        assert.ok(!text.toLowerCase().includes("gemini"), "no model name, got: " + text);
        vm.runInContext(`updateStatus({answer_kind: "ai_generated", provider: "gemini", mode: "fast"})`, sandbox);
        assert.ok(byId.engineStatus.textContent.includes("Gemini"), "provider badge intact");
        console.log("PASS fallback status is user-safe, AI badge intact");
    } catch (e) { console.error("FAIL status badge:", e.message); process.exitCode = 1; }
}

// 6. Exact reported artifacts: glued bold, backslashed heading,
//    entity-encoded text, backslashed emphasis.
{
    const { sandbox } = makeSandbox([]);
    loadChat(sandbox);
    try {
        const out = vm.runInContext(`formatReply(${JSON.stringify(
            "The**Waterfall Model**and Agile structures work.\n\\#### Sequential Phases of Waterfall:\nLearn &#x52;equirements and \\*sprints\\* planning."
        )})`, sandbox);
        assert.ok(out.includes("The <strong>Waterfall Model</strong> and"),
            "bold spacing fixed, got: " + out);
        assert.ok(out.includes("<h5>Sequential Phases of Waterfall:</h5>"),
            "heading unescaped, got: " + out);
        assert.ok(out.includes("Learn Requirements and"),
            "entity decoded, got: " + out);
        assert.ok(out.includes("<em>sprints</em>"),
            "emphasis unescaped, got: " + out);
        assert.ok(!out.includes("\\####") && !out.includes("\\*") &&
            !out.includes("&#x") && !out.includes("**Waterfall"),
            "no raw artifacts left, got: " + out);
        console.log("PASS reported artifacts render cleanly");
    } catch (e) { console.error("FAIL artifacts:", e.message); process.exitCode = 1; }
}

// 7. LaTeX and code examples survive untouched; no double conversion.
{
    const { sandbox } = makeSandbox([]);
    loadChat(sandbox);
    try {
        const latex = "The formula is \\frac{a}{b} inline.";
        const outLatex = vm.runInContext(`formatReply(${JSON.stringify(latex)})`, sandbox);
        assert.ok(outLatex.includes("\\frac{a}{b}"),
            "LaTeX preserved, got: " + outLatex);
        const code = "Run `a**b** and \\n` now.";
        const outCode = vm.runInContext(`formatReply(${JSON.stringify(code)})`, sandbox);
        assert.ok(outCode.includes("<code>a**b** and \\n</code>"),
            "code literal, got: " + outCode);
        const fenced = "Example:\n```\nx = 1  # &#x52; stays\n```\ndone.";
        const outFence = vm.runInContext(`formatReply(${JSON.stringify(fenced)})`, sandbox);
        assert.ok(outFence.includes("<pre><code>") && outFence.includes("&#x52;") === false,
            "fence kept as code, got: " + outFence);
        const once = vm.runInContext(`formatReply("## Hi\\n\\nSome **bold** text.")`, sandbox);
        const twice = vm.runInContext(
            `formatReply(${JSON.stringify("## Hi")})`, sandbox);
        assert.ok(!once.includes("<p><p>") && once.includes("<h3>Hi</h3>"),
            "no nested paragraphs, got: " + once);
        assert.ok(twice.includes("<h3>Hi</h3>"), "stable rerender");
        console.log("PASS LaTeX/code preserved, no double conversion");
    } catch (e) { console.error("FAIL latex/code:", e.message); process.exitCode = 1; }
}

// 8. Links render safely; dangerous schemes stay literal text.
{
    const { sandbox } = makeSandbox([]);
    loadChat(sandbox);
    try {
        const out = vm.runInContext(`formatReply(${JSON.stringify(
            "See [VTU site](https://vtu.ac.in) and [evil](javascript:alert(1)) for **details**."
        )})`, sandbox);
        assert.ok(out.includes('<a href="https://vtu.ac.in" target="_blank" rel="noopener">VTU site</a>'),
            "safe link, got: " + out);
        assert.ok(!out.includes("<a href=\"javascript:"),
            "no javascript link, got: " + out);
        assert.ok(out.includes("[evil](javascript:alert(1))"),
            "rejected link stays literal, got: " + out);
        assert.ok(out.includes("<strong>details</strong>"), "bold intact");
        assert.ok(!out.includes("<script"), "no script tags");
        console.log("PASS links safe, dangerous schemes rejected");
    } catch (e) { console.error("FAIL links:", e.message); process.exitCode = 1; }
}

// 9. Blockquotes group; math notation untouched; entities decoded.
{
    const { sandbox } = makeSandbox([]);
    loadChat(sandbox);
    try {
        const out = vm.runInContext(`formatReply(${JSON.stringify(
            "> Agile welcomes change.\n> Sprints deliver increments.\n\nNext para.\n\n$E=mc^2$ and 3 * 4 = 12.\n\n&#x44;efining done."
        )})`, sandbox);
        assert.ok(out.includes("<blockquote>Agile welcomes change. Sprints deliver increments.</blockquote>"),
            "grouped quote, got: " + out);
        assert.ok(out.includes("$E=mc^2$") && out.includes("3 * 4 = 12"),
            "math intact, got: " + out);
        assert.ok(out.includes("Defining done."),
            "entity decoded, got: " + out);
        assert.ok(!out.includes("&#x"), "no raw entities");
        console.log("PASS blockquote, math, entities");
    } catch (e) { console.error("FAIL quote/math:", e.message); process.exitCode = 1; }
}

// 10. Wide tables keep parsable structure for the fixed layout.
{
    const { sandbox } = makeSandbox([]);
    loadChat(sandbox);
    try {
        const out = vm.runInContext(`formatReply(${JSON.stringify(
            "| A | B |\n|---|---|\n| https://example.com/very/long/path/no/breaks/here | 2 |"
        )})`, sandbox);
        assert.ok(out.includes("<table>") && out.includes("<th>A</th>") &&
            out.includes("<td>https://example.com/very/long/path/no/breaks/here</td>"),
            "table structure, got: " + out);
        console.log("PASS wide table structure intact");
    } catch (e) { console.error("FAIL table:", e.message); process.exitCode = 1; }
}

// 10. Wide tables keep parsable structure for the fixed layout.
{
    const { sandbox } = makeSandbox([]);
    loadChat(sandbox);
    try {
        const out = vm.runInContext(`formatReply(${JSON.stringify(
            "| A | B |\n|---|---|\n| https://example.com/very/long/path/no/breaks/here | 2 |"
        )})`, sandbox);
        assert.ok(out.includes("<table>") && out.includes("<th>A</th>") &&
            out.includes("<td>https://example.com/very/long/path/no/breaks/here</td>"),
            "table structure, got: " + out);
        assert.ok(out.includes('<div class="message-content-table">'),
            "table wrapper div present");
        console.log("PASS wide table structure intact");
    } catch (e) { console.error("FAIL table:", e.message); process.exitCode = 1; }
}

// 11. Bold glued to words on both sides, start, and middle.
{
    const { sandbox } = makeSandbox([]);
    loadChat(sandbox);
    try {
        const out = vm.runInContext(`formatReply(${JSON.stringify(
            "The**Waterfall Model**is **Agile**is an**iterative and incremental**framework"
        )})`, sandbox);
        assert.ok(out.includes("The <strong>Waterfall Model</strong> is"),
            "bold glued both sides, got: " + out);
        assert.ok(out.includes("<strong>Agile</strong> is"),
            "bold glued to following word, got: " + out);
        assert.ok(out.includes("an <strong>iterative and incremental</strong> framework"),
            "bold between words, got: " + out);
        assert.ok(!out.includes("**Waterfall") && !out.includes("**Agile") &&
            !out.includes("**iterative"), "no raw bold markers, got: " + out);
        console.log("PASS bold glued to words renders with spaces");
    } catch (e) { console.error("FAIL bold-glued:", e.message); process.exitCode = 1; }
}

// 12. HTML character references decode to real characters.
{
    const { sandbox } = makeSandbox([]);
    loadChat(sandbox);
    try {
        const out = vm.runInContext(`formatReply(${JSON.stringify(
            "&#x53;ystem and &#70;ields &amp; more"
        )})`, sandbox);
        assert.ok(out.includes("System and Fields & more"),
            "entities decoded, got: " + out);
        assert.ok(!out.includes("&#x") && !out.includes("&#70;") &&
            !out.includes("&amp;"), "no raw entities, got: " + out);
        console.log("PASS HTML entities decode safely");
    } catch (e) { console.error("FAIL entities:", e.message); process.exitCode = 1; }
}

// 13. Italic glued to words gets spaced correctly.
{
    const { sandbox } = makeSandbox([]);
    loadChat(sandbox);
    try {
        const out = vm.runInContext(`formatReply(${JSON.stringify(
            "Read*this*now and *fast*quickly"
        )})`, sandbox);
        assert.ok(out.includes("Read <em>this</em> now"),
            "italic glued both sides, got: " + out);
        assert.ok(out.includes("and <em>fast</em> quickly"),
            "italic glued following word, got: " + out);
        console.log("PASS italic glued to words renders with spaces");
    } catch (e) { console.error("FAIL italic-glued:", e.message); process.exitCode = 1; }
}

// 14. Sources never appear: card DOM absent despite a sources SSE
//     event; inline [Source N] markers stripped from the answer.
{
    const { sandbox, byId } = makeSandbox([
        SSE_SOURCES +
        'event: sources\ndata: {"sources": [{"document_id": 3,' +
        ' "subject_code": "BCS501", "page_number": 12, "filename":' +
        ' "SE Notes.pdf"}]}\n\n' +
        SSE_TOKEN("Waterfall is sequential. [Source 1] [Source 2]") +
        SSE_DONE(true),
    ]);
    sandbox.fetch = undefined; // guard: JSON fallback endpoint unused
    loadChat(sandbox);
    vm.runInContext(`askQuestion("Explain SDLC")`, sandbox);
    setTimeout(() => {
        try {
            const html = byId.chatMessages.children
            .map((c) => c.innerHTML).join("");
            assert.ok(!html.includes("source-citations"),
                "no source card DOM");
            assert.ok(!html.includes("Sources"), "no Sources heading");
            assert.ok(!html.includes("📄"), "no citation bullet");
            assert.ok(!html.includes("Open ↗"), "no PDF links");
            assert.ok(!html.includes("SE Notes"), "no filenames");
            assert.ok(!html.includes("Page 12"), "no page numbers");
            // The harness stub's querySelector detaches content nodes,
            // so the streamed text is asserted through the exact
            // renderer renderStreamed uses (formatReply).
            const rendered = vm.runInContext(
                `formatReply(${JSON.stringify(
                    "Waterfall is sequential. [Source 1] [Source 2]")})`,
                sandbox);
            assert.ok(!rendered.includes("[Source"),
                "no [Source N] markers, got: " + rendered);
            assert.ok(rendered.includes("Waterfall is sequential."),
                "answer content preserved, got: " + rendered);
            console.log("PASS sources hidden during streaming + completion");
        } catch (e) { console.error("FAIL sources-hidden:", e.message); process.exitCode = 1; }
    }, 50);
}

// 15. Address stripSystemCitations directly: academic numbered lists
//     and bracket text unrelated to Source markers must survive.
{
    const { sandbox } = makeSandbox([]);
    loadChat(sandbox);
    try {
        const out = vm.runInContext(`formatReply(${JSON.stringify(
            "See [Source 2] details.\n1. [3] IEEE 802.11 standard\nand [4-bit bus] remains."
        )})`, sandbox);
        assert.ok(!out.includes("[Source 2]") && !out.includes("details ."),
            "system marker gone, got: " + out);
        assert.ok(out.includes("[3] IEEE 802.11 standard"),
            "academic reference list intact (as markdown list), got: " + out);
        assert.ok(out.includes("[4-bit bus]"),
            "unrelated brackets intact, got: " + out);
        console.log("PASS citation markers stripped, references preserved");
    } catch (e) { console.error("FAIL strip-markers:", e.message); process.exitCode = 1; }
}

// 16. Starter suggestions: fetched from the backend, mixed render.
{
    const made = makeSandbox([]);
    made.byId.chatSuggestions = makeEl();
    made.sandbox.document.getElementById = (id) => made.byId[id] || makeEl();
    loadChat(made.sandbox);
    const suggestionsCalls = [];
    // Wrap fetch to also capture the suggestions GET.
    const sseFetch = made.sandbox.fetch;
    made.sandbox.fetch = function (url, opts) {
        if (url === "/api/chat/suggestions") {
            suggestionsCalls.push({ url });
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({
                    semester: 5,
                    suggestions: [
                        { text: "Explain the OSI reference model.", subject_code: "BCS502" },
                        { text: "State the pumping lemma.", subject_code: "BCS503" },
                        { text: "Explain COCOMO estimation.", subject_code: "BCS501" },
                        { text: "Explain grep usage.", subject_code: "BCS504" },
                    ],
                }),
            });
        }
        return sseFetch(url, opts);
    };
    vm.runInContext("refreshStarterSuggestions()", made.sandbox);
    setTimeout(() => {
        try {
            assert.strictEqual(suggestionsCalls.length, 1,
                "one suggestions GET");
            assert.strictEqual(suggestionsCalls[0].url,
                "/api/chat/suggestions");
            const wrap = made.byId.chatSuggestions;
            assert.strictEqual(wrap.children.length, 4,
                "mixed chips rendered, got: " + wrap.children.length);
            const texts = wrap.children.map((b) => b.textContent);
            assert.ok(texts.some((t) => t.includes("OSI")), "CN chip");
            assert.ok(texts.some((t) => t.includes("pumping")), "TOC chip");
            assert.ok(!wrap.innerHTML.includes("Sprints deliver"),
                "no stale template suggestions injected");
            console.log("PASS starter suggestions fetched + mixed");
        } catch (e) { console.error("FAIL suggestions:", e.message); process.exitCode = 1; }
    }, 50);
}

setTimeout(() => console.log("FRONTEND HARNESS DONE"), 300);
