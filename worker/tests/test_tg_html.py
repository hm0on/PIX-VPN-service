"""Coverage for app.tg_html.to_telegram_html.

These tests pin down the assumptions we rely on at runtime — TipTap's
output looks like the strings below, and Telegram's HTML parser is
strict about anything outside its whitelist. The fixtures here are
copied from real broadcasts that previously failed in production with
``Unsupported start tag "p"`` errors.
"""

from __future__ import annotations

import pytest

from app.tg_html import to_telegram_html


def test_empty_input_returns_empty_string() -> None:
    assert to_telegram_html(None) == ""
    assert to_telegram_html("") == ""


def test_strips_disallowed_anchor_attrs() -> None:
    src = '<a target="_blank" rel="noopener" class="x" href="https://example.com">go</a>'
    assert to_telegram_html(src) == '<a href="https://example.com">go</a>'


def test_anchor_without_href_is_unwrapped() -> None:
    assert to_telegram_html("<a>plain</a>") == "plain"


def test_paragraph_becomes_double_newline() -> None:
    out = to_telegram_html("<p>one</p><p>two</p>")
    assert out == "one\n\ntwo"


def test_empty_paragraph_collapses_to_blank_line() -> None:
    # TipTap emits <p></p> as a visible blank line; we collapse the resulting
    # \n\n\n\n run down to \n\n so Telegram doesn't render a giant gap.
    out = to_telegram_html("<p>one</p><p></p><p>two</p>")
    assert out == "one\n\ntwo"


def test_keeps_strong_em_and_basic_formatting() -> None:
    out = to_telegram_html("<p><strong>b</strong> + <em>i</em></p>")
    assert out == "<strong>b</strong> + <em>i</em>"


def test_unescapes_tg_emoji() -> None:
    src = '<p>x &lt;tg-emoji emoji-id="123"&gt;⭐&lt;/tg-emoji&gt; y</p>'
    assert to_telegram_html(src) == 'x <tg-emoji emoji-id="123">⭐</tg-emoji> y'


def test_unescapes_tg_spoiler_span_with_escaped_quotes() -> None:
    src = '<p>&lt;span class=&quot;tg-spoiler&quot;&gt;hide&lt;/span&gt;</p>'
    assert to_telegram_html(src) == '<span class="tg-spoiler">hide</span>'


def test_unescapes_tg_spoiler_span_with_real_quotes() -> None:
    # TipTap can store the class attribute either with HTML-escaped quotes
    # (&quot;) or with literal " — both forms came out of prod broadcasts.
    src = '<p>&lt;span class="tg-spoiler"&gt;hide&lt;/span&gt;</p>'
    assert to_telegram_html(src) == '<span class="tg-spoiler">hide</span>'


def test_plain_span_is_unwrapped() -> None:
    # Spans without the tg-spoiler class carry no Telegram meaning.
    out = to_telegram_html('<p><span class="text-red">x</span></p>')
    assert out == "x"


def test_full_tiptap_output_matches_expected() -> None:
    # Verbatim from the broadcast that triggered the production
    # 400 error before this converter existed.
    src = (
        '<p>тест + '
        '<a target="_blank" rel="noopener noreferrer nofollow" '
        'class="text-primary underline" href="https://www.youtube.com">ссылка</a> + '
        'эмодзи &lt;tg-emoji emoji-id="123"&gt;⭐&lt;/tg-emoji&gt; + '
        "<strong>жирный </strong>+ <em>курсив</em> </p>"
        "<p></p>"
        '<p>&lt;span class=&quot;tg-spoiler&quot;&gt;спойлер&lt;/span&gt; + фото</p>'
    )
    out = to_telegram_html(src)
    # Allowed tags survive; <p>/class/target/rel are gone.
    assert "<p>" not in out
    assert "target=" not in out
    assert "rel=" not in out
    assert 'class="text-primary' not in out
    assert '<a href="https://www.youtube.com">ссылка</a>' in out
    assert '<tg-emoji emoji-id="123">⭐</tg-emoji>' in out
    assert "<strong>жирный </strong>" in out
    assert "<em>курсив</em>" in out
    assert '<span class="tg-spoiler">спойлер</span>' in out


@pytest.mark.parametrize(
    ("src", "expected"),
    [
        ("<br>", ""),  # trailing whitespace is trimmed
        ("a<br>b", "a\nb"),
        ("<u>x</u>", "<u>x</u>"),
        ("<s>x</s>", "<s>x</s>"),
        ("<code>x</code>", "<code>x</code>"),
        ("<pre>x</pre>", "<pre>x</pre>"),
        ("<blockquote>x</blockquote>", "<blockquote>x</blockquote>"),
    ],
)
def test_basic_passthrough(src: str, expected: str) -> None:
    assert to_telegram_html(src) == expected


def test_unclosed_tag_is_closed_at_end() -> None:
    # Defensive — Telegram refuses an unclosed <b>; we close it for them.
    out = to_telegram_html("<b>oops")
    assert out == "<b>oops</b>"
