"""
Token counting and budget management.
Uses tiktoken for fast, accurate token counting.
"""

import tiktoken

# Use cl100k_base — close enough for most local models and very fast
_encoder = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Count the number of tokens in a string."""
    if not text:
        return 0
    return len(_encoder.encode(text))


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Truncate text to fit within a token budget."""
    if not text:
        return ""
    tokens = _encoder.encode(text)
    if len(tokens) <= max_tokens:
        return text
    return _encoder.decode(tokens[:max_tokens])


def count_messages_tokens(messages: list[dict]) -> int:
    """Count tokens across a list of chat messages."""
    total = 0
    for msg in messages:
        # ~4 tokens overhead per message for role/formatting
        total += 4
        total += count_tokens(msg.get("content", ""))
    total += 2  # priming tokens
    return total


class TokenBudget:
    """
    Manages token allocation across context components.
    Dynamically calculates available space for story history.
    """

    def __init__(self, max_context: int, response_budget: int):
        self.max_context = max_context
        self.response_budget = response_budget
        self.available = max_context - response_budget
        self.allocations: dict[str, int] = {}

    def allocate(self, component: str, text: str, max_budget: int) -> str:
        """
        Allocate tokens for a component. Returns the (possibly truncated) text.
        Tracks how many tokens were actually used.
        """
        if not text:
            self.allocations[component] = 0
            return ""

        truncated = truncate_to_tokens(text, max_budget)
        used = count_tokens(truncated)
        self.allocations[component] = used
        self.available -= used
        return truncated

    def remaining(self) -> int:
        """Tokens remaining for story history."""
        return max(0, self.available)

    def usage_report(self) -> dict:
        """Return a breakdown of token usage."""
        return {
            "max_context": self.max_context,
            "response_budget": self.response_budget,
            "components": dict(self.allocations),
            "used": sum(self.allocations.values()),
            "remaining_for_history": self.remaining(),
        }
