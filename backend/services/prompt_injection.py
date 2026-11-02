"""Detects text that tries to steer the AI reviewer (prompt injection).

The AI review sends text written by other people (request description, pull
request title, diffs, file contents) to the model. The system prompt tells the
model to treat all of it as data and to report instructions it finds; this check
does not depend on the model obeying that: when a known injection phrase is
found, the review always gets a red flag, added by code.

It is a heuristic: typical phrases and attempts to imitate the input markers.
It cannot catch every wording, so the review stays advisory and a human decides.
The patterns need words that address the model or its instructions, so ordinary
code ("ignore the previous value") does not match.
"""
import re

_PATTERNS = [
    # "ignore / disregard / forget (all) (the) previous instructions"
    r"\b(ignore|disregard|forget|override|bypass)\s+(all\s+|any\s+)?(of\s+)?(the\s+|your\s+|these\s+|those\s+)?"
    r"(previous|prior|above|earlier|preceding|system|original)\s+(instructions?|prompts?|rules|directions|messages?|guidelines)",
    # "new instructions:", "updated system prompt"
    r"\b(new|updated|real|actual)\s+(system\s+)?(instructions?|prompt)\s*:",
    r"\bsystem\s+prompt\b",
    # "you are now ...", "from now on you ..."
    r"\byou\s+are\s+now\b",
    r"\bfrom\s+now\s+on,?\s+you\b",
    # Addressing the AI reviewer directly.
    r"\b(dear|hey|attention|note\s+to(\s+the)?|instructions?\s+for(\s+the)?)\s+(ai|llm|assistant|language\s+model|"
    r"chatgpt|gpt|model|ai\s+reviewer|reviewer\s+bot)\b",
    r"\bas\s+an?\s+(ai|language\s+model)\b",
    # Steering the verdict: "rate this as low risk", "mark the change as safe"
    r"\b(rate|mark|classify|label|treat|report|assess|score|consider)\b[^.\n]{0,40}\bas\s+"
    r"(low[\s-]risk|safe|harmless|no[\s-]risk|risk[\s-]free|trivial)\b",
    # Pre-written answer fields of the review ("suggested_risk_level": "low").
    r"\b(suggested_risk_level|recommended_reviewer_role|red_flags)\b[\"']?\s*[:=]",
    r"\b(do\s+not|don'?t|never)\s+(report|mention|flag|list)\s+(this|these|it|any|the)\b",
    # Chat-format control tokens.
    r"<\|(im_start|im_end|system|user|assistant)\|>",
    r"\[/?INST\]",
    # Imitations of the markers the input is wrapped in.
    r"<<<\s*(end\s+)?(diff|file|request)\b",
]
_INJECTION = re.compile("|".join(f"(?:{p})" for p in _PATTERNS), re.IGNORECASE)


def looks_like_injection(text: str | None) -> bool:
    return bool(text) and _INJECTION.search(text) is not None


def red_flag(locations: list[str]) -> str:
    """The red flag for a review whose input contained injection phrases."""
    shown = ", ".join(locations[:5]) + (f" and {len(locations) - 5} more" if len(locations) > 5 else "")
    return (
        f"Possible prompt injection: text that tries to instruct the AI reviewer was found in {shown}. "
        "This review may have been manipulated; check the change yourself."
    )
