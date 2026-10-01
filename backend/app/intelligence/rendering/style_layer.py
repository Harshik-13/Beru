"""Response Style Layer for Beru.

Responsible for sanitization and Telegram formatting:
- Cleans repetitive greetings from outgoing responses.
- Ensures safe Telegram HTML formatting and escaping.
- Normalizes spacing and layout across all outgoing responses.

Note: Persona and honorific ('Sir') are handled directly by Beru's self-model
and conversational response policy, not injected mechanically here.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.intelligence.rendering.style_contract import clean_greetings

if TYPE_CHECKING:
    from app.intelligence.models.context import StudentContext


# Supported Telegram HTML tags (opening or closing)
_ALLOWED_TAG_PATTERN = re.compile(
    r"</?(?:b|i|u|s|code|pre|blockquote|tg-spoiler|strong|em|ins|strike|del)"
    r"(?:\s+[^>]*?)?>|"
    r'<a\s+href="[^"]*"\s*>|</a>|'
    r'<code(?:\s+class="[^"]*")?\s*>|</code>|'
    r'<tg-emoji\s+emoji-id="[^"]*"\s*>|</tg-emoji>',
    re.IGNORECASE,
)


def sanitize_telegram_html(text: str) -> str:
    """
    Sanitize text for Telegram HTML parse mode.

    Preserves valid Telegram HTML tags (<b>, <i>, <code>, <pre>, <a>, etc.)
    and safely escapes unescaped '<', '>', or '&' characters that would
    otherwise cause Telegram API 400 'can't parse entities' errors.
    """
    if not text:
        return ""

    # Split text into allowed tags and non-tag text segments
    tokens = []
    last_end = 0

    for match in _ALLOWED_TAG_PATTERN.finditer(text):
        start, end = match.span()
        # Non-tag text before the matched tag
        if start > last_end:
            non_tag_segment = text[last_end:start]
            # Escape ampersands not already part of HTML entities
            escaped_segment = re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;)", "&amp;", non_tag_segment)
            # Escape raw '<' and '>'
            escaped_segment = escaped_segment.replace("<", "&lt;").replace(">", "&gt;")
            tokens.append(escaped_segment)

        # Append the valid allowed tag as-is
        tokens.append(match.group(0))
        last_end = end

    # Remaining text after the last tag
    if last_end < len(text):
        remaining = text[last_end:]
        escaped_remaining = re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;)", "&amp;", remaining)
        escaped_remaining = escaped_remaining.replace("<", "&lt;").replace(">", "&gt;")
        tokens.append(escaped_remaining)

    return "".join(tokens)


class ResponseStyleLayer:
    """Applies Telegram formatting, sanitization, and layout normalization."""

    def __init__(self, default_honorific: str = "Sir") -> None:
        self.default_honorific = default_honorific

    def apply(
        self,
        raw_text: str,
        student_context: StudentContext | None = None,
        honorific: str | None = None,
    ) -> str:
        """
        Apply formatting and sanitization to rendered text or conversational response.

        Args:
            raw_text: Rendered text or conversational response.
            student_context: Optional student context.
            honorific: Optional honorific override (unused; persona handles 'Sir').

        Returns:
            Sanitized, clean Telegram-safe response.
        """
        if not raw_text or not raw_text.strip():
            return "How may I assist you?"

        # 1. Clean repetitive robotic greetings (e.g. 'Hey Harsh!', 'Hello!')
        cleaned = clean_greetings(raw_text.strip())

        # 2. Sanitize Telegram HTML (escape stray '<' or '>', preserve valid tags)
        cleaned = sanitize_telegram_html(cleaned)

        # 3. Normalize multiple blank lines to at most one empty line
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

        # 4. Strip trailing whitespace per line
        cleaned = "\n".join(line.rstrip() for line in cleaned.split("\n"))

        return cleaned.strip()
