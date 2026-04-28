"""
Story Cards — Keyword-triggered world information.
Scans recent actions/responses for trigger keywords and injects relevant lore.
"""

import re
from dataclasses import dataclass, field, asdict
from src.token_manager import count_tokens, truncate_to_tokens


@dataclass
class StoryCard:
    """A single story card with trigger keywords and lore entry."""
    name: str
    keywords: list[str]
    entry: str
    priority: int = 5  # 1 (lowest) to 10 (highest)
    enabled: bool = True
    use_regex: bool = False
    auto_generated: bool = False
    id: str = ""

    def __post_init__(self):
        if not self.id:
            # Generate a simple ID from the name
            self.id = re.sub(r"[^a-z0-9]", "_", self.name.lower()).strip("_")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "StoryCard":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class StoryCardEngine:
    """Manages story cards and triggers them based on recent text."""

    def __init__(self):
        self.cards: list[StoryCard] = []

    def add_card(self, card: StoryCard):
        """Add a new story card."""
        # Ensure unique ID
        existing_ids = {c.id for c in self.cards}
        if card.id in existing_ids:
            counter = 2
            base_id = card.id
            while f"{base_id}_{counter}" in existing_ids:
                counter += 1
            card.id = f"{base_id}_{counter}"
        self.cards.append(card)

    def update_card(self, card_id: str, updates: dict):
        """Update an existing card."""
        for card in self.cards:
            if card.id == card_id:
                for key, value in updates.items():
                    if hasattr(card, key) and key != "id":
                        setattr(card, key, value)
                return True
        return False

    def remove_card(self, card_id: str) -> bool:
        """Remove a card by ID."""
        before = len(self.cards)
        self.cards = [c for c in self.cards if c.id != card_id]
        return len(self.cards) < before

    def get_card(self, card_id: str) -> StoryCard | None:
        """Get a card by ID."""
        for card in self.cards:
            if card.id == card_id:
                return card
        return None

    def scan_for_triggers(
        self,
        recent_actions: list[str],
        recent_responses: list[str],
    ) -> list[StoryCard]:
        """
        Scan recent text for keyword matches.
        Returns triggered cards sorted by priority (highest first).
        """
        # Combine all recent text into a single search corpus
        corpus = " ".join(recent_actions + recent_responses).lower()

        triggered = []
        for card in self.cards:
            if not card.enabled:
                continue
            if self._card_matches(card, corpus):
                triggered.append(card)

        # Sort by priority (highest first)
        triggered.sort(key=lambda c: c.priority, reverse=True)
        return triggered

    def _card_matches(self, card: StoryCard, corpus: str) -> bool:
        """Check if any of the card's keywords match the corpus."""
        for keyword in card.keywords:
            if card.use_regex:
                try:
                    if re.search(keyword, corpus, re.IGNORECASE):
                        return True
                except re.error:
                    continue
            else:
                if keyword.lower() in corpus:
                    return True
        return False

    def build_triggered_text(
        self,
        recent_actions: list[str],
        recent_responses: list[str],
        max_tokens: int,
    ) -> str:
        """
        Build the world lore block from triggered cards,
        respecting the token budget.
        """
        triggered = self.scan_for_triggers(recent_actions, recent_responses)
        if not triggered:
            return ""

        lines = ["[World Lore]"]
        total_tokens = count_tokens("[World Lore]\n")

        for card in triggered:
            entry_line = f"- {card.name}: {card.entry}"
            entry_tokens = count_tokens(entry_line + "\n")
            if total_tokens + entry_tokens > max_tokens:
                # Try to fit a truncated version
                remaining = max_tokens - total_tokens - count_tokens(f"- {card.name}: ")
                if remaining > 20:
                    truncated_entry = truncate_to_tokens(card.entry, remaining)
                    lines.append(f"- {card.name}: {truncated_entry}")
                break
            lines.append(entry_line)
            total_tokens += entry_tokens

        if len(lines) <= 1:
            return ""

        return "\n".join(lines)

    def to_list(self) -> list[dict]:
        """Serialize all cards."""
        return [c.to_dict() for c in self.cards]

    def from_list(self, data: list[dict]):
        """Load cards from serialized data."""
        self.cards = [StoryCard.from_dict(d) for d in data]
