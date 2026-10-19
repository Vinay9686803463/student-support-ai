"""Static guards for the "+" menu toggle button (✕ state).

The toggle button beside the chat input doubles as the menu's open/✕
close control. These guards lock in:
1. the CSS cascading rule that makes a closed menu actually hide
   (.plus-menu[hidden] beats the author `display: flex`);
2. the red hover on the open (✕) state, pointer devices only;
3. clean markup: type="button", no visible tooltip, accessible name;
4. JS: one shared state, icon/aria synced from it, no duplicate
   document listeners, no accidental double-toggle on item clicks.

Run: python -m pytest tests/test_plus_menu_toggle.py -q
"""

import os
import pathlib

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def chat_css():
    return (_REPO / "static" / "css" / "chat.css").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def chat_html():
    return (_REPO / "templates" / "chat.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def chat_js():
    return (_REPO / "static" / "js" / "chat.js").read_text(encoding="utf-8")


class TestPlusMenuToggleCss:

    def test_hidden_guard_makes_close_effective(self, chat_css):
        assert ".plus-menu[hidden]" in chat_css
        guard = chat_css[chat_css.index(".plus-menu[hidden]"):]
        assert "display: none" in guard[:60]

    def test_open_state_hover_is_red_with_white_icon(self, chat_css):
        zone = chat_css[chat_css.index("@media (hover: hover)"):]
        rule = zone[zone.index(".plus-button.open:hover"):]
        rule = rule[:rule.index("}")]
        assert "#ef4444" in rule       # red fill
        assert "#ffffff" in rule       # white ✕

    def test_icon_and_colors_transition_smoothly(self, chat_css):
        start = chat_css.index(".plus-button {")
        rule = chat_css[start:chat_css.index("}", start)]
        assert "transition:" in rule
        for prop in ("background", "color", "transform"):
            assert prop in rule, f"transition missing: {prop}"


class TestPlusMenuToggleMarkup:

    def test_button_type_button_and_handler(self, chat_html):
        start = chat_html.index('id="plusButton"')
        block = chat_html[start - 100: chat_html.index("</button>", start)]
        assert 'type="button"' in block
        assert "togglePlusMenu(event)" in block
        assert "aria-controls=\"plusMenu\"" in block

    def test_no_visible_tooltip(self, chat_html):
        start = chat_html.index('id="plusButton"')
        block = chat_html[start - 100: chat_html.index("</button>", start)]
        assert "title=" not in block, (
            "the title attribute renders a visible tooltip, which the "
            "spec forbids — rely on aria-label only"
        )

    def test_accessible_name_present(self, chat_html):
        start = chat_html.index('id="plusButton"')
        block = chat_html[start - 100: chat_html.index("</button>", start)]
        assert "aria-label=" in block


class TestPlusMenuToggleJavascript:

    def test_single_state_drives_icon_and_aria(self, chat_js):
        sync_start = chat_js.index("function _syncPlusButton")
        sync_body = chat_js[sync_start:chat_js.index(
            "}", chat_js.index("aria-label", sync_start))]
        # The helper is the only place that touches the .open class;
        # direct classList.add/remove("open") elsewhere would risk drift.
        assert 'classList.toggle("open"' in sync_body
        assert 'aria-expanded' in sync_body
        assert 'aria-label' in sync_body
        assert chat_js.count('classList.add("open")') == 0
        assert chat_js.count('classList.remove("open")') == 0

    def test_toggle_uses_existing_state(self, chat_js):
        start = chat_js.index("function togglePlusMenu")
        body = chat_js[start:chat_js.index("function closePlusMenu")]
        assert "plusMenuOpen" in body
        assert "closePlusMenu()" in body          # same-state close path
        assert "event.stopPropagation()" in body  # no instant re-close

    def test_document_listeners_bound_idempotently(self, chat_js):
        open_start = chat_js.index("function togglePlusMenu")
        close_start = chat_js.index("function closePlusMenu")
        outside_start = chat_js.index("function _plusOutsideClick")
        open_body = chat_js[open_start:close_start]
        close_body = chat_js[close_start:outside_start]
        # Removal before each add: repeated open cycles can't stack
        # duplicate outside-click or Escape handlers.
        assert open_body.count("addEventListener") == 2
        assert open_body.count("removeEventListener") == 2
        first_add = open_body.index("addEventListener")
        assert open_body.index("removeEventListener") < first_add, (
            "must remove the previous binding before re-adding")
        # Closing always unbinds both.
        assert close_body.count("removeEventListener") == 2

    def test_outside_click_ignores_menu_and_button(self, chat_js):
        start = chat_js.index("function _plusOutsideClick")
        body = chat_js[start:chat_js.index("function _plusKeydown")]
        assert "contains(event.target)" in body
        assert 'getElementById("plusButton")' in body
