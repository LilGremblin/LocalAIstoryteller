"""
Rolling auto-summary engine.
Periodically compresses story history into a concise summary.
"""

from src import config
from src.llm_client import chat_completion
from src.token_manager import count_tokens

SUMMARY_SYSTEM_PROMPT = """\
You are a story summarizer. Your job is to create concise, information-dense summaries of interactive fiction.

Rules:
- Preserve ALL key plot points, character introductions, important decisions, and consequences.
- Maintain character names, relationships, and significant dialogue.
- Track location changes and important objects/items.
- Write in past tense, third person.
- Be concise but never omit plot-critical information.
- If given an existing summary, merge the new events into it seamlessly."""

SUMMARY_USER_TEMPLATE = """\
{existing_section}
NEW EVENTS TO INCORPORATE:
{new_events}

Write the updated summary. Be concise but preserve all important plot details."""


async def generate_summary(
    existing_summary: str,
    new_events: list[dict],
    sampling: dict | None = None,
) -> str:
    """
    Generate an updated rolling summary by merging new events into the existing one.
    
    Args:
        existing_summary: The current rolling summary (may be empty).
        new_events: List of {"role": "player"|"narrator", "text": "..."} entries.
        sampling: Optional sampling parameter overrides.
    
    Returns:
        The updated summary string.
    """
    # Format the new events for the prompt
    events_text = ""
    for event in new_events:
        role = event.get("role", "narrator")
        text = event.get("text", "")
        if role == "player":
            events_text += f"> Player: {text}\n"
        else:
            events_text += f"{text}\n\n"

    # Build the prompt
    existing_section = ""
    if existing_summary:
        existing_section = f"EXISTING SUMMARY:\n{existing_summary}\n\n"

    user_msg = SUMMARY_USER_TEMPLATE.format(
        existing_section=existing_section,
        new_events=events_text.strip(),
    )

    messages = [
        {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    # Use lower temperature for factual summarization
    sum_sampling = {
        "temperature": 0.4,
        "max_tokens": config.BUDGET_SUMMARY,
        "min_p": 0.05,
    }
    if sampling:
        sum_sampling.update(sampling)

    result = await chat_completion(messages, sampling=sum_sampling)
    return result.strip()


def should_summarize(
    turn_count: int,
    last_summary_turn: int,
    history_tokens: int,
) -> bool:
    """
    Determine if we should trigger auto-summarization.
    Triggers on either interval or token threshold.
    """
    interval = config.get("SUMMARY_INTERVAL", config.SUMMARY_INTERVAL)
    threshold = config.get(
        "SUMMARY_HISTORY_THRESHOLD", config.SUMMARY_HISTORY_THRESHOLD
    )

    turns_since = turn_count - last_summary_turn

    if turns_since >= interval:
        return True
    if history_tokens > threshold:
        return True
    return False


def estimate_events_tokens(events: list[dict]) -> int:
    """Estimate token count for a list of story events."""
    total = 0
    for event in events:
        total += count_tokens(event.get("text", ""))
    return total
