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

setTimeout(() => console.log("FRONTEND HARNESS DONE"), 300);
