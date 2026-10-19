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
        setAttribute(k, v) {
            this._attrs = Object.assign({}, this._attrs, { [k]: String(v) });
        },
        getAttribute(k) { return (this._attrs || {})[k] ?? null; },
        remove() {},
        focus() {},
        select() {},
        // Real DOM parity for the "append and keep what came before"
        // placement mode chat.js uses for message avatars.
        insertAdjacentHTML(_position, html) { this._html += String(html); },
        classList: {
            _s: new Set(),
            add(c) { this._s.add(c); },
            remove(c) { this._s.delete(c); },
            toggle(c, force) {
                const has = this._s.has(c);
                const want = force === undefined ? !has : !!force;
                if (want) { this._s.add(c); } else { this._s.delete(c); }
                return want;   // presence after the call, like the DOM
            },
            contains(c) { return this._s.has(c); },
        },
    };
    Object.defineProperty(el, "innerHTML", {
        // Serialize own innerHTML plus children like a real DOM would;
        // node content placed via appendChild must be visible to
        // assertions inspecting the parent's innerHTML.
        get() {
            return this._html +
                this.children.map((child) => child.innerHTML).join("");
        },
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

function makeSandbox(sseChunks, options) {
    options = options || {};
    const byId = {};
    const ids = ["chatInput", "chatMessages", "sendButton", "stopButton",
        "engineStatus", "modeLabel",
        "libraryOverlay", "libraryList", "librarySearch",
        "plusMenu", "inputBox", "plusButton"];
    ids.forEach((id) => { byId[id] = makeEl(); });
    const fetchCalls = [];
    const libraryCalls = [];
    const libraryFetch = options.libraryFetch || null;
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
            removeEventListener() {},
        },
        fetch(url, opts) {
            fetchCalls.push({ url, body: opts && opts.body ? JSON.parse(opts.body) : null });
            if (url === "/api/chat/library") {
                libraryCalls.push({ url, signal: opts && opts.signal });
                if (!libraryFetch) {
                    return Promise.reject(new Error("no library route configured in test"));
                }
                return libraryFetch(opts && opts.signal);
            }
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
        clearTimeout: () => {},
    };
    sandbox.window.document = sandbox.document;
    sandbox.globalThis = sandbox;
    return { sandbox, byId, fetchCalls, libraryCalls };
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
        assert.ok(out.includes("<h2>Binary Search</h2>"), "heading");
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

// 14. Markdown spacing around bold spans glued to surrounding words.
{
    const { sandbox } = makeSandbox([]);
    loadChat(sandbox);
    try {
        const out = vm.runInContext(`formatReply(${JSON.stringify(
            "comparing the**Agile**and**Waterfall**models based on standard Software Engineering"
        )})`, sandbox);
        assert.ok(out.includes("the <strong>Agile</strong> and"),
            "space before bold phrase, got: " + out);
        assert.ok(out.includes("<strong>Waterfall</strong> models"),
            "space after bold phrase, got: " + out);
        const out2 = vm.runInContext(`formatReply(${JSON.stringify(
            "The**Waterfall Model**is traditional"
        )})`, sandbox);
        assert.ok(out2.includes("The <strong>Waterfall Model</strong> is"),
            "glued bold both sides, got: " + out2);
        const out3 = vm.runInContext(`formatReply(${JSON.stringify(
            "This is **bold text** and this is normal text."
        )})`, sandbox);
        assert.ok(out3.includes("This is <strong>bold text</strong> and"),
            "normal spaced bold unchanged, got: " + out3);
        const out4 = vm.runInContext(`formatReply(${JSON.stringify(
            "Use `literal code**` without changing its contents."
        )})`, sandbox);
        assert.ok(out4.includes("<code>literal code**</code>"),
            "code span untouched, got: " + out4);
        const out5 = vm.runInContext(`formatReply(${JSON.stringify(
            "See [docs](https://example.com/path?q=1&r=2) for details."
        )})`, sandbox);
        assert.ok(out5.includes('href="https://example.com/path?q=1&amp;r=2"'),
            "link URL intact (& encoded for HTML), got: " + out5);
        const out6 = vm.runInContext(`formatReply(${JSON.stringify(
            "The value $E=mc^2$ stays inline."
        )})`, sandbox);
        assert.ok(out6.includes("$E=mc^2$"), "math notation preserved, got: " + out6);
        console.log("PASS markdown spacing around bold spans");
    } catch (e) { console.error("FAIL spacing:", e.message); process.exitCode = 1; }
}

// 15. HTML entities decode exactly once (no double-decode, no literal codes).
{
    const { sandbox } = makeSandbox([]);
    loadChat(sandbox);
    try {
        const out = vm.runInContext(`formatReply(${JSON.stringify(
            "&#x41;gile and &#65;gile and &#x20;space and &amp; more"
        )})`, sandbox);
        assert.ok(out.includes("Agile and Agile"),
            "hex + decimal entities decoded, got: " + out);
        assert.ok(out.includes("space and"), "nbsp-like entity decoded, got: " + out);
        assert.ok(out.includes("&amp; more") || out.includes("& more"),
            "amp entity decoded (re-encoded for HTML), got: " + out);
        assert.ok(!out.includes("&#x"), "no raw hex entities left, got: " + out);
        assert.ok(!out.includes("&#65;"), "no raw decimal entities left, got: " + out);
        console.log("PASS HTML entities decode exactly once");
    } catch (e) { console.error("FAIL entities:", e.message); process.exitCode = 1; }
}

// 16. Global formatting regression suite: shared renderer for every subject.
{
    const { sandbox } = makeSandbox([]);
    loadChat(sandbox);
    const render = (s) => vm.runInContext(`formatReply(${JSON.stringify(s)})`, sandbox);
    try {
        // Headings at every level.
        const headings = render("# H1\n## H2\n### H3\n#### H4\n##### H5\n###### H6");
        ["<h1>H1</h1>", "<h2>H2</h2>", "<h3>H3</h3>", "<h4>H4</h4>", "<h5>H5</h5>", "<h6>H6</h6>"]
            .forEach((h) => assert.ok(headings.includes(h), "heading " + h + " in " + headings));

        // Missing spaces around bold glued to words, but never before punctuation.
        const spaced = render("both**Waterfall**and**Agile**are");
        assert.ok(spaced.includes("both <strong>Waterfall</strong> and <strong>Agile</strong> are"), spaced);
        assert.ok(render("The**Waterfall Model**is a sequential methodology.")
            .includes("The <strong>Waterfall Model</strong> is a sequential methodology."));
        assert.ok(render("approach to the**Agile**model")
            .includes("approach to the <strong>Agile</strong> model"));
        assert.ok(render("a**Product Backlog**, and priorities")
            .includes("a <strong>Product Backlog</strong>, and priorities"));
        assert.ok(render("word**bold**.").includes("word <strong>bold</strong>."));
        assert.ok(render("word.**bold**").includes("word.<strong>bold</strong>"));
        assert.ok(render("This is **bold text** and this is normal text.")
            .includes("This is <strong>bold text</strong> and this is normal text."));

        // Italic and triple emphasis.
        assert.ok(render("*italic*").includes("<em>italic</em>"));
        assert.ok(render("***both***").includes("<strong><em>both</em></strong>"));
        assert.ok(render("word*italic*text").includes("word <em>italic</em> text"));

        // Escaped asterisks stay literal.
        const escaped = render("\\*not italic\\* and \\*not bold\\*");
        assert.ok(escaped.includes("*not italic*") && escaped.includes("*not bold*"), escaped);
        assert.ok(!escaped.includes("<em>"), "escaped asterisks must not become emphasis: " + escaped);

        // HTML entities: hex, decimal, named; decode exactly once.
        const entities = render("&#x41;ll developers &#x44;evelopers &#x54;he");
        assert.ok(entities.includes("All developers Developers The"), entities);
        assert.ok(!entities.includes("&#x") && !entities.includes("&#65;"), entities);
        const once = render("&amp;#x41; and &amp; literal");
        assert.ok(once.includes("&amp;#x41;"), "double-encoded entity must not decode twice: " + once);
        assert.ok(once.includes("&amp; literal"), once);
        // Entities inside code stay literal.
        const codeEntities = render("Code: `&#x41;` and `&amp;`");
        assert.ok(codeEntities.includes("<code>&amp;#x41;</code>"), codeEntities);
        assert.ok(codeEntities.includes("<code>&amp;amp;</code>"), codeEntities);

        // Lists, nested lists and numbering.
        const list = render("1. One\n1. Two\n- bullet\n   - nested\n   - nested two");
        assert.ok(list.includes("<ol>") && list.includes("<li>One</li>") && list.includes("<li>Two</li>"), list);
        assert.ok(list.includes("<ul>") && list.includes("<li>bullet"), list);
        assert.ok(list.includes("<li>nested</li>"), list);
        assert.ok((list.match(/<ol>/g) || []).length === 1, "one ordered list, got " + list);

        // Tables.
        const table = render("| Col A | Col B |\n|:------|------:|\n| 1 | 2 |\n| 3 | 4 |");
        assert.ok(table.includes("<th>Col A</th>") && table.includes("<th>Col B</th>"), table);
        assert.ok(table.includes("<td>1</td>") && table.includes("<td>3</td>"), table);

        // Fenced code blocks are not wrapped in a paragraph.
        const fence = render("```python\nprint('hi')\n```");
        assert.ok(fence.includes("<pre><code>print(&#39;hi&#39;)</code></pre>"), fence);
        assert.ok(!fence.includes("<p><pre>"), "fence must not be wrapped in <p>: " + fence);

        // Inline code, safe links, math, Unicode.
        const mixed = render("Use `code` and [docs](https://example.com/path?q=1&r=2) and π, é, 你好");
        assert.ok(mixed.includes("<code>code</code>"), mixed);
        assert.ok(mixed.includes('href="https://example.com/path?q=1&amp;r=2"'), mixed);
        assert.ok(mixed.includes("π, é, 你好"), mixed);
        assert.ok(render("Math $E=mc^2$ stays inline.").includes("$E=mc^2$"));

        // Malicious HTML is escaped.
        const xss = render("<script>alert(1)</script> and **bold**");
        assert.ok(!xss.includes("<script>") && xss.includes("&lt;script&gt;"), xss);
        assert.ok(xss.includes("<strong>bold</strong>"), xss);

        // Internal RAG commentary is removed from student-facing answers.
        const commentary = render("The retrieved study context lacks a full comparative analysis. Waterfall and Agile differ.");
        assert.ok(!commentary.toLowerCase().includes("retrieved"), commentary);
        assert.ok(commentary.includes("Waterfall and Agile differ."), commentary);

        // Multiple subjects/semesters use the same renderer.
        const dbms = render("Normalization **reduces** redundancy.\n\n1. 1NF\n2. 2NF\n\n| Form | Rule |\n|---|---|\n| 1NF | atomic |");
        assert.ok(dbms.includes("<strong>reduces</strong>") && dbms.includes("<ol>"), dbms);
        const toc = render("Convert **NFA** to **DFA**.\n\n- step one\n- step two");
        assert.ok(toc.includes("<strong>NFA</strong>") && toc.includes("<ul>"), toc);
        const maths = render("The derivative of $x^2$ is $2x$.");
        assert.ok(maths.includes("$x^2$") && maths.includes("$2x$"), maths);
        const prog = render("```c\nint main() { return 0; }\n```");
        assert.ok(prog.includes("<pre><code>int main() { return 0; }</code></pre>"), prog);

        // Streaming chunks that split Markdown syntax render correctly at the end.
        const chunks = ["## Agile vs ", "**Waterfall**", " Model\n", "1. Agile\n", "1. Waterfall"];
        let acc = "";
        chunks.forEach((c) => { acc += c; render(acc); });
        const streamed = render(acc);
        assert.ok(streamed.includes("<h2>Agile vs <strong>Waterfall</strong> Model</h2>"), streamed);
        assert.ok(streamed.includes("<li>Agile</li>") && streamed.includes("<li>Waterfall</li>"), streamed);

        console.log("PASS global formatting regression suite");
    } catch (e) { console.error("FAIL global formatting:", e.message); process.exitCode = 1; }
}

// 17. Retry and stored history use the same normalization.
{
    const { sandbox } = makeSandbox([]);
    loadChat(sandbox);
    try {
        const first = vm.runInContext(`formatReply(${JSON.stringify("The**Waterfall Model**is sequential")})`, sandbox);
        const retried = vm.runInContext(`formatReply(${JSON.stringify("The**Waterfall Model**is sequential")})`, sandbox);
        assert.strictEqual(first, retried, "retry must render identically");
        assert.ok(retried.includes("The <strong>Waterfall Model</strong> is sequential"), retried);
        console.log("PASS retry/stored-history formatting is shared");
    } catch (e) { console.error("FAIL retry formatting:", e.message); process.exitCode = 1; }
}

// 18. Library: prefetch keeps a document cache; reopening never refetches.
{
    const DOC = { id: 7, subject_code: "BCS502", subject_name: "Computer Networks",
        title: "Module 1 - Network Layer", filename: "m1.pdf",
        module_number: 1, page_count: 12 };
    const respond = (signal) => Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve({ ok: true, documents: [DOC] }),
    });
    const { sandbox, byId, libraryCalls } = makeSandbox([], { libraryFetch: respond });
    loadChat(sandbox);
    vm.runInContext("prefetchLibrary()", sandbox);
    setTimeout(() => {
        try {
            assert.strictEqual(libraryCalls.length, 1, "prefetch made one request");
            vm.runInContext("openLibrary()", sandbox);
            assert.ok(byId.libraryList.innerHTML.includes("BCS502")
                && byId.libraryList.innerHTML.includes("m1.pdf"),
                "documents render on open (badge + filename label)");
            vm.runInContext("closeLibrary()", sandbox);
            vm.runInContext("openLibrary()", sandbox);
            assert.strictEqual(libraryCalls.length, 1,
                "reopening serves the cache instead of refetching");
            console.log("PASS library prefetch renders instantly + cache on reopen");
        } catch (e) { console.error("FAIL library-prefetch:", e.message); process.exitCode = 1; }
    }, 20);
}

// 19. Library: the X closes during an in-flight load and aborts the request.
{
    const state = { mode: "hanging", signal: null };
    const respond = (signal) => {
        state.signal = signal;
        return new Promise((resolve, reject) => {
            const onAbort = () => reject(new Error("Aborted"));
            if (signal && signal.aborted) { reject(new Error("Aborted")); return; }
            if (signal) { signal.addEventListener("abort", onAbort); }
            // Otherwise pending forever: only abort can settle it.
        });
    };
    const { sandbox, byId } = makeSandbox([], { libraryFetch: respond });
    loadChat(sandbox);
    vm.runInContext("openLibrary()", sandbox);
    setTimeout(() => {
        try {
            assert.strictEqual(byId.libraryOverlay.hidden, false, "dialog opens");
            assert.ok(byId.libraryList.innerHTML.includes("Loading library"),
                "loading state visible");
            vm.runInContext("closeLibrary()", sandbox);
            assert.strictEqual(byId.libraryOverlay.hidden, true,
                "X closes the dialog immediately while loading");
            assert.strictEqual(state.signal.aborted, true,
                "in-flight request aborted on close");
            // Reopen must retry cleanly (nothing sticky): the next test
            // covers reopen-after-failure; the cache path is test 18.
            console.log("PASS close works while loading and aborts the fetch");
        } catch (e) { console.error("FAIL library-close-loading:", e.message); process.exitCode = 1; }
    }, 10);
}

// 20. Library: API failure = error state + retry; retry succeeds; Ok but
//     empty library shows the empty-state message (not an error).
{
    let mode = "fail";
    const DOC = { id: 2, subject_code: "BCS501", subject_name: "Software Engineering",
        title: "Module 1 - SDLC", filename: "sdlc-module-1.pdf",
        module_number: 1, page_count: 9 };
    const respond = (signal) => {
        if (mode === "fail") {
            return Promise.reject(new Error("network down"));
        }
        if (mode === "empty") {
            return Promise.resolve({ ok: true, status: 200,
                json: () => Promise.resolve({ ok: true, documents: [] }) });
        }
        return Promise.resolve({ ok: true, status: 200,
            json: () => Promise.resolve({ ok: true, documents: [DOC] }) });
    };
    const { sandbox, byId, libraryCalls } = makeSandbox([], { libraryFetch: respond });
    loadChat(sandbox);
    vm.runInContext("openLibrary()", sandbox);
    setTimeout(() => {
        try {
            assert.ok(byId.libraryList.innerHTML.includes("Could not load the library"),
                "error state shown");
            assert.ok(byId.libraryList.innerHTML.includes("Try again"),
                "retry button offered");
            assert.strictEqual(mode === "fail" && byId.libraryList.innerHTML.includes("No study documents"),
                false, "an API failure is never shown as an empty library");
            mode = "ok";
            vm.runInContext("retryLibraryLoad()", sandbox);
        } catch (e) { console.error("FAIL library-error-state:", e.message); process.exitCode = 1; return; }
        setTimeout(() => {
            try {
                assert.ok(byId.libraryList.innerHTML.includes("sdlc-module-1.pdf"),
                    "retry loads documents");
                const openingCalls = libraryCalls.length;
                vm.runInContext("closeLibrary()", sandbox);
                mode = "empty";
                vm.runInContext("openLibrary()", sandbox); // opens from cache AFTER success
                assert.strictEqual(libraryCalls.length, openingCalls,
                    "cached success is reused, no refetch");
                assert.ok(byId.libraryList.innerHTML.includes("sdlc-module-1.pdf"),
                    "cache still shows documents");
                // True empty-library render (200 OK, zero documents):
                // empty-state message, never an error banner.
                vm.runInContext("renderLibrary([])", sandbox);
                assert.ok(byId.libraryList.innerHTML.includes(
                    "No study documents"), "empty state message shown");
                assert.strictEqual(
                    byId.libraryList.innerHTML.includes("Could not load"),
                    false, "empty library is not an error state");
                console.log("PASS library error/retry flow + cached reuse");
            } catch (e) { console.error("FAIL library-error-state:", e.message); process.exitCode = 1; }
        }, 20);
    }, 10);
}

// 21. Library: Escape closes even while a request is pending; single kb handler.
{
    const respond = () => new Promise(() => {});   // pending forever
    const { sandbox, byId, libraryCalls } = makeSandbox([], { libraryFetch: respond });
    loadChat(sandbox);
    vm.runInContext("openLibrary()", sandbox);
    setTimeout(() => {
        try {
            assert.strictEqual(libraryCalls.length, 1, "exactly one in-flight request");
            vm.runInContext(
                '_libraryKeydown({ key: "Escape", stopPropagation() {} })', sandbox);
            assert.strictEqual(byId.libraryOverlay.hidden, true,
                "Escape closes without waiting for the API");
            assert.strictEqual(libraryCalls[0].signal.aborted, true,
                "pending request aborted on Escape");
            // Second close is a no-op safe repeat (no duplicate listeners).
            vm.runInContext("closeLibrary()", sandbox);
            console.log("PASS Escape closes during load, single handler binding");
        } catch (e) { console.error("FAIL library-escape:", e.message); process.exitCode = 1; }
    }, 10);
}

// 22. "+"/✕ toggle: one button, one state — opens, closes, reopens; the
//     icon and aria attributes stay in sync with real menu visibility.
{
    const { sandbox, byId } = makeSandbox([]);
    loadChat(sandbox);
    vm.runInContext("togglePlusMenu(null)", sandbox);
    try {
        assert.strictEqual(byId.plusMenu.hidden, false, "menu opens");
        assert.ok(byId.plusButton.classList.contains("open"),
            "icon shows the open (✕) state");
        assert.strictEqual(byId.plusButton.getAttribute("aria-expanded"),
            "true");
        assert.strictEqual(byId.plusButton.getAttribute("aria-label"),
            "Close menu", "accessible name switches to Close (no tooltip)");
        assert.strictEqual(vm.runInContext("plusMenuOpen", sandbox), true,
            "one shared state variable drives everything");
        // Second toggle = click ✕: menu closes, icon reverts to "+".
        vm.runInContext("togglePlusMenu(null)", sandbox);
        assert.strictEqual(byId.plusMenu.hidden, true,
            "✕ click closes the menu");
        assert.ok(!byId.plusButton.classList.contains("open"),
            "icon returns to + (no .open class)");
        assert.strictEqual(byId.plusButton.getAttribute("aria-expanded"),
            "false");
        assert.strictEqual(byId.plusButton.getAttribute("aria-label"),
            "Open menu");
        // Third toggle: reopening works again.
        vm.runInContext("togglePlusMenu(null)", sandbox);
        assert.strictEqual(byId.plusMenu.hidden, false, "reopens");
        vm.runInContext("closePlusMenu()", sandbox);
        assert.strictEqual(byId.plusMenu.hidden, true, "closes again");
        console.log("PASS plus/✕ toggle cycles with synced icon + aria");
    } catch (e) { console.error("FAIL plus-toggle:", e.message); process.exitCode = 1; }
}

// 23. Toggle works while Add-from-library is loading; a menu item never
//     double-toggles the menu.
{
    let mode = "hanging";
    let libSignal = null;
    const respond = (signal) => {
        libSignal = signal;
        return mode === "hanging"
            ? new Promise((resolve, reject) => {
                const onAbort = () => reject(new Error("Aborted"));
                if (signal && signal.aborted) { reject(new Error("Aborted")); return; }
                if (signal) { signal.addEventListener("abort", onAbort); }
            })
            : Promise.resolve({ ok: true, status: 200,
                json: () => Promise.resolve({ ok: true, documents: [
                    { id: 3, subject_code: "BCS503", subject_name: "DBMS",
                      title: "Module 1", filename: "db1.pdf",
                      module_number: 1, page_count: 6 } ] }) });
    };
    const { sandbox, byId, libraryCalls } = makeSandbox([], { libraryFetch: respond });
    loadChat(sandbox);
    // Open the menu, pick "Add from library": menu closes once; the
    // dialog starts loading and keeps loading.
    vm.runInContext("togglePlusMenu(null)", sandbox);
    vm.runInContext("choosePlusAction('library')", sandbox);
    try {
        assert.strictEqual(vm.runInContext("plusMenuOpen", sandbox), false,
            "choosing a menu item closes the menu exactly once");
        assert.strictEqual(byId.plusMenu.hidden, true, "menu is closed");
        assert.strictEqual(byId.libraryOverlay.hidden, false,
            "library dialog opened");
        assert.strictEqual(libraryCalls.length, 1, "one library request");
        // While the library request is still in flight, the ✕ toggle
        // must keep working immediately.
        vm.runInContext("togglePlusMenu(null)", sandbox);   // open
        assert.strictEqual(byId.plusMenu.hidden, false,
            "toggle still opens while library loads");
        vm.runInContext("togglePlusMenu(null)", sandbox);   // close via ✕
        assert.strictEqual(byId.plusMenu.hidden, true,
            "toggle closes immediately while library loads");
        assert.strictEqual(libSignal.aborted, false,
            "library request untouched by the menu toggle");
        assert.ok(byId.libraryList.innerHTML.includes("Loading library"),
            "library still loading, unaffected");
        // Escape closes the pending library dialog and aborts its fetch.
        vm.runInContext(
            '_libraryKeydown({ key: "Escape", stopPropagation() {} })',
            sandbox);
        assert.strictEqual(libSignal.aborted, true,
            "Escape aborts the pending library request");
        // Retry from a clean state still works.
        mode = "ok";
        vm.runInContext("openLibrary()", sandbox);
    } catch (e) { console.error("FAIL plus-toggle-while-loading:", e.message); process.exitCode = 1; }
    setTimeout(() => {
        try {
            assert.strictEqual(libraryCalls.length, 2,
                "fresh attempt after abort (no sticky failure)");
            assert.ok(byId.libraryList.innerHTML.includes("db1.pdf"),
                "documents render after the loading + toggle sequence");
            console.log("PASS toggle works during library load; no double-toggle");
        } catch (e) { console.error("FAIL plus-toggle-while-loading:", e.message); process.exitCode = 1; }
    }, 20);
}

setTimeout(() => console.log("FRONTEND HARNESS DONE"), 450);
