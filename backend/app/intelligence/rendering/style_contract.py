"""Style contract and typography standards for Beru responses.

Enforces:
- Clean ChatGPT-style hierarchy and consistent line spacing
- Concise, bold labels (<b>Time:</b>, <b>Room:</b>, etc.)
- Strict minimal emoji usage (only functional alerts like \u2705 and \u26a0\ufe0f)
- Polite 'Sir' honorific without repetitive greetings (no 'Hey Harsh!')
"""

from __future__ import annotations

import re

HONORIFIC = "Sir"
CHECK_MARK = "\u2705"
WARNING_SIGN = "\u26a0\ufe0f"

# Pattern to strip repetitive greetings from LLM output
REPETITIVE_GREETING_PATTERN = re.compile(
    r"^(?:(?:Hey|Hi|Hello|Good\s+(?:morning|afternoon|evening))\b[^\n,!.?]*[,!.?]\s*)+",
    re.IGNORECASE,
)


def format_badge(content: str) -> str:
    """Format inline code badge for times, codes, percentages."""
    return f"<code>{content}</code>"


def format_time_span(start: str, end: str) -> str:
    """Format start and end time with en-dash inside a code badge."""
    return f"<code>{start} \u2013 {end}</code>"


def format_percentage(val: float) -> str:
    """Format float percentage with one decimal place inside code tag."""
    return f"<code>{val:.1f}%</code>"


def format_label_value(label: str, value: str, indent: str = "   \u2022 ") -> str:
    """Format a bullet point with bold label and value."""
    return f"{indent}<b>{label}:</b> {value}"


def clean_greetings(text: str) -> str:
    """Remove repetitive 'Hey Harsh!', 'Hello [name]!' greetings from text."""
    if not text:
        return ""
    cleaned = REPETITIVE_GREETING_PATTERN.sub("", text.strip()).strip()
    return cleaned


def sanitize_conversational_response(text: str, honorific: str = HONORIFIC) -> str:
    """Sanitize conversational LLM text according to style contract."""
    cleaned = clean_greetings(text)
    if not cleaned:
        return f"How may I assist you, {honorific}?"

    # Ensure honorific is present if not already addressed
    if honorific.lower() not in cleaned.lower():
        # Append honorific politely if appropriate
        if cleaned.endswith("."):
            cleaned = f"{cleaned[:-1]}, {honorific}."
        elif cleaned.endswith("!"):
            cleaned = f"{cleaned[:-1]}, {honorific}!"
        elif cleaned.endswith("?"):
            cleaned = f"{cleaned[:-1]}, {honorific}?"

    return cleaned
