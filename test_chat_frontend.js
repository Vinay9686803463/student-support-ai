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

setTimeout(() => console.log("FRONTEND HARNESS DONE"), 300);
