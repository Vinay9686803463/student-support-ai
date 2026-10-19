"""Static guards for the chat formatting pipeline (ChatGPT-style render).

Locks the pipeline structure that test_chat_frontend.js exercises
dynamically:
1. math handling exists in the renderer (LaTeX-lite, sentinel-based);
2. display math is stashed at block level BEFORE markdown parsing;
3. currency-like "$5 and $3" text is never treated as math;
4. tables render inside a horizontally scrollable wrapper;
5. inline emphasis stays INLINE (the legacy display:block rule is
   overridden in the assistant scope);
6. fenced code keeps raw LaTeX (no math conversion inside code).

Run: python -m pytest tests/test_chat_formatting.py -q
"""

import pathlib

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def chat_js():
    return (_REPO / "static" / "js" / "chat.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def chat_css():
    return (_REPO / "static" / "css" / "chat.css").read_text(encoding="utf-8")


class TestMathPipeline:

    def test_math_symbols_and_renderer_exist(self, chat_js):
        assert "_MATH_SYMBOLS" in chat_js
        assert "function _renderMathInner" in chat_js
        assert "rightarrow" in chat_js   # arrows mapped
        assert "times" in chat_js

    def test_sentinel_based_stash(self, chat_js):
        assert "_MATH_SENTINEL" in chat_js
        # Inline renderer stashes math with the sentinel…
        assert "stash(_MATH_SENTINEL + body + _MATH_SENTINEL)" in chat_js
        # …and restores bodies through _renderMath.
        assert "return _renderMath(value.slice(1, -1))" in chat_js

    def test_block_level_display_math_stash(self, chat_js):
        # Multi-line $$…$$ and \[…\] stashed before block parsing.
        assert r"remainder.replace(/\$\$([^$]+)\$\$/g" in chat_js
        assert r"remainder.replace(/\\\[([\s\S]*?)\\\]/g" in chat_js
        assert r'"\n\uE000B"' in chat_js

    def test_currency_guard(self, chat_js):
        assert "_looksLikeMath" in chat_js
        assert "_looksLikeMath(body)" in chat_js

    def test_math_delimiters_covered(self, chat_js):
        assert r"/\\\(([\s\S]*?)\\\)/g" in chat_js    # \( … \)
        assert r"/\$\$([^$\n]+?)\$\$/g" in chat_js    # $$ … $$
        assert r"/\$([^$\n]+?)\$/g" in chat_js        # $ … $
        assert r"/\\\[(?:[\s\S]*?)\\\]/g" not in chat_js  # done at block level

    def test_render_math_escapes_content(self, chat_js):
        assert "function _mathEscape" in chat_js

    def test_code_blocks_render_before_math(self, chat_js):
        # Fences are stashed FIRST in renderMarkdown so $$ inside code
        # is untouched by the display-math pass.
        assert chat_js.index("fenceStore.push(block)") < \
            chat_js.index('displayStore.push(body)')


class TestTableWrapper:

    def test_table_wrapped_for_scroll(self, chat_js):
        assert 'class="table-wrap"' in chat_js

    def test_wrapper_css_scrolls(self, chat_css):
        assert ".table-wrap {" in chat_css
        zone = chat_css[chat_css.index(".table-wrap {"):]
        zone = zone[:zone.index("}", zone.index("overflow-x"))]
        assert "overflow-x: auto" in zone

    def test_typography_layer_scoped_to_assistant(self, chat_css):
        # Bold inside answers must remain INLINE (legacy core rule made
        # it block-level).
        assert ".ai-message .message-content strong {" in chat_css
        zone = chat_css[chat_css.index(".ai-message .message-content strong {"):]
        zone = zone[:zone.index("}")]
        assert "display: inline" in zone

    def test_headings_lists_code_math_styled(self, chat_css):
        for marker in (".ai-message .message-content h2 {",
                       ".ai-message .message-content ul,",
                       ".message-content div.math-display {",
                       ".ai-message .message-content pre {"):
            assert marker in chat_css, f"missing style: {marker}"
