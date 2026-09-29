"""Telegram text formatting and HTML normalization utilities."""

from __future__ import annotations

import html
import re

ALLOWED_TAGS = {"b", "strong", "i", "em", "code", "pre", "a", "u", "s", "tg-spoiler"}

TAG_PATTERN = re.compile(r"<(/?[a-zA-Z0-9_-]+)(?:\s+[^>]*)?>")
HTML_STRIP_PATTERN = re.compile(r"<[^>]+>")


def strip_html_tags(text: str) -> str:
    """Strip all HTML tags from text, unescaping entities."""
    if not text:
        return ""
    stripped = HTML_STRIP_PATTERN.sub("", text)
    return html.unescape(stripped)


def markdown_to_telegram_html(text: str) -> str:
    """
    Convert basic markdown constructs to Telegram-compatible HTML.
    Preserves existing valid HTML tags.
    """
    if not text:
        return ""

    out = text

    # Convert code blocks ```lang\ncode\n```
    out = re.sub(
        r"```(?:[a-zA-Z0-9_+-]+)?\n?(.*?)```",
        r"<pre><code>\1</code></pre>",
        out,
        flags=re.DOTALL,
    )

    # Convert inline code `code`
    out = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", out)

    # Convert markdown headers: ### Header -> <b>Header</b>
    out = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", out, flags=re.MULTILINE)

    # Convert bold **text** or __text__
    out = re.sub(r"\*\*([^\*\n]+)\*\*", r"<b>\1</b>", out)
    out = re.sub(r"__([^_\n]+)__", r"<b>\1</b>", out)

    # Convert bullet points * or - at start of line to \u2022
    out = re.sub(r"^[\*\-]\s+", "• ", out, flags=re.MULTILINE)

    return out


def telegram_format(text: str) -> str:
    """Format and normalize text for Telegram HTML delivery."""
    return markdown_to_telegram_html(text)
