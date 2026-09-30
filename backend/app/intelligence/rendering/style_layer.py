"""Response Style Layer for Beru.

Decouples personality and presentation:
- Domain renderers format pure verified structured data without persona elements.
- ResponseStyleLayer injects personality (honorific 'Sir', polite closings, greeting cleanup)
  and ensures clean spacing and typography across all outgoing responses.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.intelligence.rendering.style_contract import (
    CHECK_MARK,
    HONORIFIC,
    WARNING_SIGN,
    clean_greetings,
    format_badge,
    format_percentage,
    format_time_span,
)

if TYPE_CHECKING:
    from app.intelligence.models.context import StudentContext


class ResponseStyleLayer:
    """Applies Beru's persona, honorifics, and tone to rendered structured text."""

    def __init__(self, default_honorific: str = HONORIFIC) -> None:
        self.default_honorific = default_honorific

    def apply(
        self,
        raw_text: str,
        student_context: StudentContext | None = None,
        honorific: str | None = None,
    ) -> str:
        """
        Apply persona and style layer to domain rendered text or conversational response.

        Args:
            raw_text: Pure structured data text or conversational message.
            student_context: Optional student context for customization.
            honorific: Explicit honorific override (defaults to 'Sir').

        Returns:
            Fully styled, polished response text with Beru's persona.
        """
        if not raw_text or not raw_text.strip():
            target_honorific = honorific or self.default_honorific
            return f"How may I assist you, {target_honorific}?"

        target_honorific = honorific or self.default_honorific

        # 1. Clean repetitive greetings (e.g. 'Hey Harsh!', 'Hello!')
        cleaned = clean_greetings(raw_text.strip())

        # 2. Check if honorific is already present
        has_honorific = target_honorific.lower() in cleaned.lower()

        # 3. Inject honorific into primary header or conversational sentence if missing
        if not has_honorific:
            cleaned = self._inject_honorific(cleaned, target_honorific)

        # 4. Normalize multiple blank lines to at most one empty line
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

        return cleaned.strip()

    def _inject_honorific(self, text: str, honorific: str) -> str:
        """Politely inject honorific into header line or message ending."""
        lines = text.split("\n")
        first_line = lines[0].strip()

        # Case A: First line is a bold header, e.g. <b>Schedule for Wednesday:</b> or <b>Good morning.</b>
        match = re.match(r"^(<b>.*?)([:.]?</b>)(.*)$", first_line)
        if match:
            head = match.group(1).rstrip(":.")
            punct = ":" if ":" in match.group(2) else "."
            lines[0] = f"{head}, {honorific}{punct}</b>{match.group(3)}"
            return "\n".join(lines)

        # Case B: First line ends with colon (plain header)
        if first_line.endswith(":"):
            lines[0] = f"{first_line[:-1]}, {honorific}:"
            return "\n".join(lines)

        # Case C: Short conversational text ending with punctuation
        last_line = lines[-1].strip()
        if last_line.endswith("."):
            lines[-1] = f"{last_line[:-1]}, {honorific}."
            return "\n".join(lines)
        if last_line.endswith("!"):
            lines[-1] = f"{last_line[:-1]}, {honorific}!"
            return "\n".join(lines)
        if last_line.endswith("?"):
            lines[-1] = f"{last_line[:-1]}, {honorific}?"
            return "\n".join(lines)

        # Default fallback: append honorific to first sentence or header
        lines[0] = f"{lines[0]}, {honorific}"
        return "\n".join(lines)
