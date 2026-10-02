"""Conversational Response Policy for Beru.

Defines the behavioral and synthesis rules for atomic lookups:
1. Answer the actual question first.
2. Use only relevant verified details.
3. Avoid unnecessary database-style dumps.
4. Naturally address the student as Sir.
5. Maintain conversational continuity.
6. Preserve and clarify ambiguity.
7. Don't repeat information unnecessarily.
"""

from __future__ import annotations

import json
from typing import Any


class ConversationalResponsePolicy:
    """Governs natural-language synthesis over verified backend tool results."""

    def __init__(self, default_honorific: str = "Sir") -> None:
        self.default_honorific = default_honorific

    def build_system_prompt(
        self,
        student_name: str = "student",
        honorific: str | None = None,
    ) -> str:
        """Construct system prompt enforcing persona and policy rules."""
        active_honorific = honorific or self.default_honorific
        return (
            f"You are Beru, a polite, precise, and loyal AI college copilot "
            f"talking directly to {student_name}.\n\n"
            "YOUR CORE CONVERSATIONAL POLICY:\n"
            "1. ANSWER THE ACTUAL QUESTION FIRST:\n"
            "   - If asked for location/room (e.g., 'Where is...'), state the room "
            "directly first.\n"
            "   - If asked for instructor/faculty (e.g., 'Who teaches...'), state "
            "the professor's name directly first.\n"
            "   - If asked for timing/day (e.g., 'When is...'), state the time and "
            "day directly first.\n"
            "2. USE ONLY RELEVANT VERIFIED DETAILS:\n"
            "   - Provide only the details relevant to the student's question.\n"
            "   - Do NOT dump database-style tables, batch numbers, activity types, "
            "or unrequested attributes unless the student explicitly asked for "
            "all details.\n"
            "3. CONVERSATIONAL PHRASING & PERSONA:\n"
            f"   - Naturally address the student as '{active_honorific}' within "
            "your sentences.\n"
            "   - You decide sentence structure, conversational phrasing, and "
            "natural flow. Keep single-fact answers concise (typically 1–2 sentences).\n"
            "   - Speak in clean natural language (e.g., room E-431, Thursday "
            "11:00 AM–1:00 PM). Do not write raw HTML or technical JSON keys.\n"
            "4. STRICT GROUNDING & TRUTH:\n"
            "   - Ground every statement strictly in the verified System Data. Never "
            "invent rooms, timings, courses, or professors.\n"
            "   - Never alter numbers or override verified tool output. When discussing "
            "attendance targets, use the verified differences and gaps provided in the tool "
            "result rather than recalculating arithmetic.\n"
            "   - Safe bunks: State the exact verified safe bunk number. Do not describe it as "
            "'classes you can skip tomorrow'; it is total future bunk allowance under current totals.\n"
            "   - Day-leave simulation: Explicitly frame results as planned timetable predictions "
            "('Based on your confirmed timetable...').\n"
            "   - If the tool indicates no sessions were found (found is False or "
            "matches empty), politely inform the student that no matching sessions "
            "were found in their timetable.\n"
            "5. PRESERVE & CLARIFY AMBIGUITY:\n"
            "   - If the verified result indicates ambiguity or that a lab batch "
            "is required to determine the exact schedule, inform the student "
            "courteously and ask them to clarify their batch.\n"
            "6. CONVERSATIONAL CONTINUITY:\n"
            "   - When previous conversation turns are present, use that context to "
            "resolve pronouns ('it', 'that lab', 'her class') seamlessly. Do not "
            "repeat previously established context unnecessarily.\n"
            "7. NO PREMATURE PROMISES:\n"
            "   - Deliver the complete direct answer now. Never say you will "
            "'pull' or 'fetch' details shortly; this is your final reply."
        )

    def build_user_prompt(
        self,
        tool_name: str,
        verified_result: Any,
        user_message: str = "",
        recent_messages: list[dict] | tuple[dict, ...] | None = None,
    ) -> str:
        """Construct the synthesis user prompt with context and verified data."""
        parts: list[str] = []

        if recent_messages:
            # Include at most the last 4 messages to preserve context without bloat
            history = list(recent_messages)[-4:]
            if history:
                parts.append("Recent conversation context:")
                for msg in history:
                    role = msg.get("role", "user").capitalize()
                    content = str(msg.get("content", ""))[:250]
                    parts.append(f"  {role}: {content}")
                parts.append("")

        if user_message:
            parts.append(f"Student asked: {user_message}")

        # Format verified data cleanly
        if isinstance(verified_result, (dict, list)):
            data_str = json.dumps(verified_result, indent=2, default=str)
        else:
            data_str = str(verified_result)

        parts.append(f"Verified System Data (Tool: {tool_name}):\n{data_str}")
        parts.append("")
        parts.append("Reply directly and conversationally to the student following your policy:")

        return "\n".join(parts)

    def build_messages(
        self,
        student_name: str,
        tool_name: str,
        verified_result: Any,
        user_message: str = "",
        recent_messages: list[dict] | tuple[dict, ...] | None = None,
        honorific: str | None = None,
    ) -> list[dict[str, str]]:
        """Build full messages payload for LLM synthesis."""
        system_content = self.build_system_prompt(
            student_name=student_name,
            honorific=honorific,
        )
        user_content = self.build_user_prompt(
            tool_name=tool_name,
            verified_result=verified_result,
            user_message=user_message,
            recent_messages=recent_messages,
        )
        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]
