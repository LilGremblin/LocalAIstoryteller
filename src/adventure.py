"""
Adventure state management — save, load, and manage story adventures.
"""

import os
import json
import time
import re
from dataclasses import dataclass, field, asdict
from src import config
from src.story_cards import StoryCardEngine, StoryCard
from src.memory_bank import MemoryBank
from src.auto_cards import AutoCardsEngine
from src.inner_self import InnerSelfEngine


@dataclass
class StoryEntry:
    """A single entry in the story history."""
    role: str  # "player" or "narrator"
    text: str
    action_type: str = "story"  # "do", "say", "story"
    turn: int = 0
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "StoryEntry":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class Adventure:
    """
    Full adventure state — the central data model.
    Holds everything: story, settings, cards, memory.
    """

    def __init__(self, name: str = "Untitled Adventure"):
        self.name = name
        self.id = re.sub(r"[^a-z0-9]", "_", name.lower()).strip("_") or "untitled"
        self.created_at = time.time()
        self.updated_at = time.time()

        # Story content
        self.history: list[StoryEntry] = []
        self.summary: str = ""
        self.last_summary_turn: int = 0

        # User-configured context blocks
        self.instructions: str = config.DEFAULT_INSTRUCTIONS
        self.plot_essentials: str = config.DEFAULT_PLOT_ESSENTIALS
        self.author_note: str = config.DEFAULT_AUTHOR_NOTE

        # Systems
        self.card_engine = StoryCardEngine()
        self.memory_bank = MemoryBank()
        self.auto_cards = AutoCardsEngine()
        self.inner_self = InnerSelfEngine()

        # Settings
        self.sampling: dict = dict(config.DEFAULT_SAMPLING)
        self.context_size: int = config.MAX_CONTEXT_TOKENS

    @property
    def turn_count(self) -> int:
        """Current turn number (counts player actions only)."""
        return sum(1 for e in self.history if e.role == "player")

    def add_player_action(self, text: str, action_type: str = "do"):
        """Add a player action to the history."""
        processed = self._process_action(text, action_type)
        entry = StoryEntry(
            role="player",
            text=processed,
            action_type=action_type,
            turn=self.turn_count + 1,
            timestamp=time.time(),
        )
        self.history.append(entry)
        self.updated_at = time.time()

    def add_narrator_response(self, text: str):
        """Add the AI's narrative response to the history."""
        entry = StoryEntry(
            role="narrator",
            text=text,
            action_type="story",
            turn=self.turn_count,
            timestamp=time.time(),
        )
        self.history.append(entry)
        self.updated_at = time.time()

    def _process_action(self, text: str, action_type: str) -> str:
        """
        Transform player input based on action type:
        - do:  "pick up the sword" → "You pick up the sword."
        - say: "I am good" → 'You say "I am good."'
        - story: raw text, no transformation
        """
        text = text.strip()
        if not text:
            return text

        if action_type == "do":
            # ── First-person → second-person conversion ──
            # "I walk to the city"  → "You walk to the city."
            # "i walk to the city"  → "You walk to the city."
            # "I'm walking"         → "You're walking."
            # "pick up the sword"   → "You pick up the sword."

            # Handle "I " / "i " at the start → replace with "You "
            if re.match(r"^[Ii] ", text):
                text = "You " + text[2:]
            # Handle "I'm" / "i'm" at the start
            elif re.match(r"^[Ii][''']m\b", text):
                text = "You're" + text[3:]
            # Handle "I'd" / "I'll" / "I've" at the start
            elif re.match(r"^[Ii][''']d\b", text):
                text = "You'd" + text[3:]
            elif re.match(r"^[Ii][''']ll\b", text):
                text = "You'll" + text[4:]
            elif re.match(r"^[Ii][''']ve\b", text):
                text = "You've" + text[4:]
            # Already starts with "You/you" — keep as-is
            elif text.lower().startswith("you "):
                text = "You " + text[4:]
            else:
                # Generic action: "pick up the sword" → "You pick up the sword"
                if text[0].isupper():
                    text = text[0].lower() + text[1:]
                text = "You " + text

            # Ensure period at end
            if text[-1] not in ".!?":
                text += "."
            return text

        elif action_type == "say":
            # Wrap in speech
            # Remove surrounding quotes if user already added them
            text = text.strip('"').strip("'")
            return f'You say "{text}"'

        else:  # story
            return text

    def undo(self) -> bool:
        """Remove the last action+response pair."""
        if not self.history:
            return False

        # Remove last entry
        self.history.pop()

        # If the previous entry is a player action, remove it too
        # (remove the pair: narrator response + player action)
        if self.history and self.history[-1].role == "player":
            self.history.pop()

        self.updated_at = time.time()
        return True

    def get_recent_actions(self, depth: int | None = None) -> list[str]:
        """Get the text of the last N player actions."""
        depth = depth or config.CARD_SCAN_DEPTH
        actions = [e.text for e in self.history if e.role == "player"]
        return actions[-depth:]

    def get_recent_responses(self, depth: int | None = None) -> list[str]:
        """Get the text of the last N narrator responses."""
        depth = depth or config.CARD_SCAN_DEPTH
        responses = [e.text for e in self.history if e.role == "narrator"]
        return responses[-depth:]

    def get_history_for_context(self) -> list[dict]:
        """
        Format history as chat messages for context assembly.
        Returns [{"role": "user"|"assistant", "content": "..."}]
        """
        messages = []
        for entry in self.history:
            if entry.role == "player":
                messages.append({"role": "user", "content": entry.text})
            else:
                messages.append({"role": "assistant", "content": entry.text})
        return messages

    def get_events_since_summary(self) -> list[dict]:
        """Get story events that haven't been summarized yet."""
        events = []
        for entry in self.history:
            if entry.turn > self.last_summary_turn:
                events.append({
                    "role": entry.role,
                    "text": entry.text,
                })
        return events

    def save(self, directory: str | None = None):
        """Save the adventure to disk."""
        directory = directory or config.ADVENTURES_DIR
        adv_dir = os.path.join(directory, self.id)
        os.makedirs(adv_dir, exist_ok=True)

        # Save main state
        state = {
            "name": self.name,
            "id": self.id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "summary": self.summary,
            "last_summary_turn": self.last_summary_turn,
            "instructions": self.instructions,
            "plot_essentials": self.plot_essentials,
            "author_note": self.author_note,
            "sampling": self.sampling,
            "context_size": self.context_size,
            "history": [e.to_dict() for e in self.history],
            "story_cards": self.card_engine.to_list(),
            "auto_cards": self.auto_cards.to_dict(),
            "inner_self": self.inner_self.to_dict(),
        }

        state_path = os.path.join(adv_dir, "adventure.json")
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)

        # Save memory bank
        self.memory_bank.save(adv_dir, "memory")

    @classmethod
    def load(cls, adventure_id: str, directory: str | None = None) -> "Adventure":
        """Load an adventure from disk."""
        directory = directory or config.ADVENTURES_DIR
        adv_dir = os.path.join(directory, adventure_id)
        state_path = os.path.join(adv_dir, "adventure.json")

        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)

        adv = cls(name=state["name"])
        adv.id = state["id"]
        adv.created_at = state.get("created_at", time.time())
        adv.updated_at = state.get("updated_at", time.time())
        adv.summary = state.get("summary", "")
        adv.last_summary_turn = state.get("last_summary_turn", 0)
        adv.instructions = state.get("instructions", config.DEFAULT_INSTRUCTIONS)
        adv.plot_essentials = state.get("plot_essentials", "")
        adv.author_note = state.get("author_note", "")
        adv.sampling = state.get("sampling", dict(config.DEFAULT_SAMPLING))
        adv.context_size = state.get("context_size", config.MAX_CONTEXT_TOKENS)

        # Load history
        adv.history = [
            StoryEntry.from_dict(e) for e in state.get("history", [])
        ]

        # Load story cards
        adv.card_engine.from_list(state.get("story_cards", []))

        # Load auto-cards state
        ac_data = state.get("auto_cards")
        if ac_data:
            adv.auto_cards.from_dict(ac_data)

        # Load inner-self state
        is_data = state.get("inner_self")
        if is_data:
            adv.inner_self.from_dict(is_data)

        # Load memory bank
        adv.memory_bank.load(adv_dir, "memory")

        return adv

    @staticmethod
    def list_adventures(directory: str | None = None) -> list[dict]:
        """List all saved adventures with basic info."""
        directory = directory or config.ADVENTURES_DIR
        adventures = []

        if not os.path.exists(directory):
            return adventures

        for entry in os.listdir(directory):
            state_path = os.path.join(directory, entry, "adventure.json")
            if os.path.exists(state_path):
                try:
                    with open(state_path, "r", encoding="utf-8") as f:
                        state = json.load(f)
                    adventures.append({
                        "id": state["id"],
                        "name": state["name"],
                        "created_at": state.get("created_at", 0),
                        "updated_at": state.get("updated_at", 0),
                        "turns": sum(
                            1
                            for e in state.get("history", [])
                            if e.get("role") == "player"
                        ),
                    })
                except (json.JSONDecodeError, KeyError):
                    continue

        adventures.sort(key=lambda a: a["updated_at"], reverse=True)
        return adventures

    @staticmethod
    def delete_adventure(adventure_id: str, directory: str | None = None) -> bool:
        """Delete an adventure from disk."""
        import shutil
        directory = directory or config.ADVENTURES_DIR
        adv_dir = os.path.join(directory, adventure_id)
        if os.path.exists(adv_dir):
            shutil.rmtree(adv_dir)
            return True
        return False
