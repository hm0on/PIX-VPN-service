"""TipTap → Telegram HTML converter.

The admin editor (TipTap, see ``admin/src/pages/broadcasts/BroadcastEditor.tsx``)
emits full HTML — ``<p>`` paragraphs, attributes like ``target=`` and
``class=`` on ``<a>``, etc. Telegram's Bot API only understands a small
whitelist (https://core.telegram.org/bots/api#html-style):

    <b>, <strong>, <i>, <em>, <u>, <ins>, <s>, <strike>, <del>,
    <a href="...">, <code>, <pre>, <pre><code class="language-...">,
    <span class="tg-spoiler">, <tg-spoiler>, <tg-emoji emoji-id="...">,
    <blockquote>

Anything else either causes a 400 ("Unsupported start tag") or is silently
ignored. So before we ship the broadcast text to Telegram we have to
sanitize it down to that subset.

Two extra wrinkles the editor introduces:

- Empty ``<p></p>`` paragraphs are kept by TipTap as line spacers; we map
  them to a single newline rather than dropping them entirely.
- The editor stores raw ``<tg-emoji ...>`` / ``<tg-spoiler>`` markup as
  HTML-escaped text (e.g. ``&lt;tg-emoji emoji-id="..."&gt;⭐&lt;/tg-emoji&gt;``)
  so the editor renders it as visible text instead of trying to
  interpret it. We unescape that back to real tags here so Telegram sees
  the actual markup.

The converter is regex-based to keep the dependency surface small (no
bs4, no lxml). It is deliberately conservative — anything we don't
recognise is dropped to plain text.
"""

from __future__ import annotations

import html
import re

# Tags Telegram allows verbatim. We keep the *opening* tag as-is when the
# attribute set is empty, and emit a tag-specific reconstruction when there
# are attributes (only ``<a href>``, ``<span class="tg-spoiler">``,
# ``<tg-emoji emoji-id>``, ``<code class="language-...">`` carry meaning).
_ALLOWED_BARE = {
    "b", "strong", "i", "em", "u", "ins", "s", "strike", "del",
    "code", "pre", "blockquote", "tg-spoiler",
}

# Tags we strip but keep their inner text. ``<p>`` is special-cased to a
# trailing ``\n``; the rest we just unwrap. ``<span>`` is intentionally
# *not* in this set — Telegram's ``<span class="tg-spoiler">`` is
# meaningful, so spans go through ``_render_open_tag`` which keeps the
# tg-spoiler variant and drops everything else.
_UNWRAP = {"p", "div", "section", "article", "header", "footer"}

# Self-closing tags that map to whitespace.
_BREAK = {"br", "hr"}

# Pre-compiled patterns.
_TAG_RE = re.compile(r"<(?P<closing>/?)(?P<name>[A-Za-z][A-Za-z0-9-]*)(?P<attrs>[^>]*)>")
_ATTR_RE = re.compile(
    r"""(?P<key>[A-Za-z_:][\w:.\-]*)\s*=\s*(?:"(?P<dq>[^"]*)"|'(?P<sq>[^']*)'|(?P<bare>[^\s>]+))"""
)


def _attrs_to_dict(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in _ATTR_RE.finditer(raw):
        val = m.group("dq")
        if val is None:
            val = m.group("sq")
        if val is None:
            val = m.group("bare") or ""
        out[m.group("key").lower()] = val
    return out


def _render_open_tag(name: str, attrs: dict[str, str]) -> str:
    """Render an opening tag using only the attributes Telegram cares about."""
    if name == "a":
        href = attrs.get("href", "").strip()
        if not href:
            # Anchor without href is meaningless to Telegram — unwrap.
            return ""
        return f'<a href="{html.escape(href, quote=True)}">'
    if name == "tg-emoji":
        emoji_id = attrs.get("emoji-id", "").strip()
        if not emoji_id:
            return ""
        return f'<tg-emoji emoji-id="{html.escape(emoji_id, quote=True)}">'
    if name == "span":
        # Only ``class="tg-spoiler"`` is meaningful on a span.
        if "tg-spoiler" in attrs.get("class", "").split():
            return '<span class="tg-spoiler">'
        return ""  # plain span — unwrap
    if name == "code":
        lang = attrs.get("class", "")
        # Telegram supports ``<code class="language-xyz">`` only inside <pre>.
        if lang.startswith("language-"):
            return f'<code class="{html.escape(lang, quote=True)}">'
        return "<code>"
    if name in _ALLOWED_BARE:
        return f"<{name}>"
    return ""


def _render_close_tag(name: str, *, had_open: bool) -> str:
    """Match the close tag to whatever ``_render_open_tag`` produced."""
    if not had_open:
        return ""
    if name in _ALLOWED_BARE or name in {"a", "tg-emoji", "span", "code"}:
        return f"</{name}>"
    return ""


def to_telegram_html(src: str | None) -> str:
    """Sanitize TipTap-flavoured HTML down to Telegram's whitelist.

    Empty / falsy input returns an empty string. The result is safe to pass
    as ``parse_mode="HTML"`` to ``sendMessage`` / ``sendPhoto.caption``.
    """
    if not src:
        return ""

    # Unwrap escaped Telegram-only tags the editor saved as text. We do this
    # BEFORE parsing so the rest of the pipeline sees real tags. Limit the
    # rewrite to the known Telegram tags so we don't accidentally re-open
    # arbitrary HTML the user typed.
    s = src
    s = re.sub(r"&lt;(/?)tg-emoji([^&]*?)&gt;", r"<\1tg-emoji\2>", s, flags=re.IGNORECASE)
    s = re.sub(r"&lt;(/?)tg-spoiler([^&]*?)&gt;", r"<\1tg-spoiler\2>", s, flags=re.IGNORECASE)
    s = re.sub(
        r"&lt;span\s+class=&quot;tg-spoiler&quot;&gt;",
        '<span class="tg-spoiler">',
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(r"&lt;/span&gt;", "</span>", s, flags=re.IGNORECASE)

    out: list[str] = []
    # Track whether each tag we entered had a real opening output, so we
    # can decide whether to emit the matching close tag.
    open_stack: list[tuple[str, bool]] = []

    pos = 0
    for m in _TAG_RE.finditer(s):
        # Text before this tag.
        if m.start() > pos:
            out.append(s[pos : m.start()])
        pos = m.end()

        name = m.group("name").lower()
        is_close = bool(m.group("closing"))
        attrs = _attrs_to_dict(m.group("attrs") or "")

        if is_close:
            # Pop matching open from the stack.
            had_open = False
            for i in range(len(open_stack) - 1, -1, -1):
                if open_stack[i][0] == name:
                    had_open = open_stack[i][1]
                    del open_stack[i]
                    break
            if name == "p":
                out.append("\n\n")
                continue
            if name in _UNWRAP:
                continue
            out.append(_render_close_tag(name, had_open=had_open))
            continue

        # Opening tag.
        if name in _BREAK:
            out.append("\n")
            continue
        if name == "p":
            # Opening <p> emits nothing; closing </p> emits the linebreak so
            # consecutive empty paragraphs collapse predictably.
            open_stack.append((name, False))
            continue
        if name in _UNWRAP:
            open_stack.append((name, False))
            continue

        rendered = _render_open_tag(name, attrs)
        out.append(rendered)
        open_stack.append((name, bool(rendered)))

    # Trailing text after the last tag.
    if pos < len(s):
        out.append(s[pos:])

    # Close any tags the user forgot to close (defensive — Telegram is strict).
    for name, had_open in reversed(open_stack):
        if had_open:
            out.append(_render_close_tag(name, had_open=True))

    result = "".join(out)
    # Collapse runs of 3+ newlines to 2 (one blank line max), trim trailing
    # whitespace — TipTap likes to leave a stray trailing <p></p>.
    result = re.sub(r"\n{3,}", "\n\n", result).strip()
    return result


__all__ = ["to_telegram_html"]
