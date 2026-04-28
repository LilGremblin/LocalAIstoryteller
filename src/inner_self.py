"""
Inner-Self — NPC Brain Simulation Engine.
Inspired by LewdLeah's Inner-Self for AI Dungeon.
Gives NPCs autonomous inner states: goals, secrets, opinions, memories.
Each turn, NPCs mentioned in the story may "think" and update their brain.
"""

import re
import json
import random
from dataclasses import dataclass, field, asdict
from src import config
from src.llm_client import chat_completion
from src.token_manager import count_tokens, truncate_to_tokens


# ─── Prompts ─────────────────────────────────────────────────────────────
THOUGHT_CYCLE_PROMPT = """\
You are simulating the inner thoughts of {npc_name}, a character in an interactive fiction story.

{npc_name}'s current inner state:
{brain_json}

Based on the recent story events below, think as {npc_name}. \
Update, add, or remove 1-3 inner thoughts. Each thought is a key-value pair.

Rules:
- Keys should be short, snake_case descriptors (e.g. "my_goal", "opinion_of_player", "my_secret", "current_plan", "fear", "desire")
- Values should be first-person, 1-2 sentences max
- Only change thoughts that are affected by recent events
- Remove thoughts that are no longer relevant
- Keep total thoughts under {max_thoughts}
- Return ONLY a valid JSON object, nothing else"""

BRAIN_SEED_PROMPT = """\
You are creating the initial inner state for {npc_name}, a character in an interactive fiction story.

Based on what the story has established about {npc_name}, create their inner thoughts as a JSON object.
Each key is a snake_case descriptor, each value is a first-person thought (1-2 sentences).
Create 3-5 initial thoughts covering: their primary goal, their opinion of the player, and any secrets or desires.

Story context:
{story_context}

Return ONLY a valid JSON object, nothing else."""


# ─── Data Classes ────────────────────────────────────────────────────────
@dataclass
class NPCBrain:
    """An NPC's inner state — their thoughts, goals, secrets."""
    name: str
    thoughts: dict[str, str] = field(default_factory=dict)
    auto_registered: bool = False  # True if detected by Auto-Cards
    enabled: bool = True
    last_thought_turn: int = 0
    thought_count: int = 0  # Total thoughts ever generated

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "NPCBrain":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def format_for_context(self) -> str:
        """Format brain state for injection into the AI context."""
        if not self.thoughts:
            return ""
        lines = [f"[{self.name}'s Inner State]"]
        for key, value in self.thoughts.items():
            label = key.replace("_", " ").title()
            lines.append(f"- {label}: {value}")
        return "\n".join(lines)


# ─── Inner-Self Engine ──────────────────────────────────────────────────
class InnerSelfEngine:
    """
    Manages NPC brains and their thought cycles.
    Each turn, NPCs mentioned in the story may update their inner state.
    """

    def __init__(self):
        self.enabled: bool = True
        self.brains: dict[str, NPCBrain] = {}  # keyed by lowercase name

    # ── Brain Management ─────────────────────────────────────────────

    def register_npc(self, name: str, auto: bool = False) -> NPCBrain:
        """Register an NPC for brain simulation."""
        key = name.lower()
        if key not in self.brains:
            self.brains[key] = NPCBrain(name=name, auto_registered=auto)
        return self.brains[key]

    def unregister_npc(self, name: str) -> bool:
        """Remove an NPC brain."""
        key = name.lower()
        if key in self.brains:
            del self.brains[key]
            return True
        return False

    def get_brain(self, name: str) -> NPCBrain | None:
        return self.brains.get(name.lower())

    def update_brain(self, name: str, thoughts: dict[str, str]) -> bool:
        """Manually update an NPC's thoughts."""
        brain = self.get_brain(name)
        if not brain:
            return False
        brain.thoughts.update(thoughts)
        return True

    # ── Thought Cycles ───────────────────────────────────────────────

    def get_npcs_to_think(self, recent_text: str, turn: int) -> list[NPCBrain]:
        """
        Determine which NPCs should think this turn.
        An NPC thinks if:
        1. They are mentioned in recent text
        2. Random chance passes (configurable probability)
        3. They haven't thought this exact turn already
        """
        if not self.enabled:
            return []

        thinkers = []
        text_lower = recent_text.lower()

        for key, brain in self.brains.items():
            if not brain.enabled:
                continue
            if brain.last_thought_turn >= turn:
                continue  # Already thought this turn
            if brain.name.lower() not in text_lower:
                continue  # Not mentioned
            if random.random() > config.NPC_THOUGHT_CHANCE:
                continue  # Didn't pass probability check
            thinkers.append(brain)

        return thinkers

    async def run_thought_cycle(
        self, brain: NPCBrain, story_context: str, turn: int
    ) -> bool:
        """
        Run a thought cycle for one NPC.
        Fires an LLM call to update the NPC's inner state.
        """
        brain_json = json.dumps(brain.thoughts, indent=2) if brain.thoughts else "{}"

        prompt = THOUGHT_CYCLE_PROMPT.format(
            npc_name=brain.name,
            brain_json=brain_json,
            max_thoughts=config.NPC_MAX_THOUGHTS,
        )
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Recent story events:\n{story_context}"},
        ]

        try:
            response = await chat_completion(
                messages, sampling={"temperature": 0.8, "max_tokens": 200},
            )
            new_thoughts = self._parse_json_response(response)
            if new_thoughts is None:
                return False

            # Merge new thoughts into existing brain
            brain.thoughts.update(new_thoughts)

            # Prune if over max
            while len(brain.thoughts) > config.NPC_MAX_THOUGHTS:
                oldest_key = next(iter(brain.thoughts))
                del brain.thoughts[oldest_key]

            brain.last_thought_turn = turn
            brain.thought_count += 1
            return True

        except Exception as e:
            print(f"[Inner-Self] Thought cycle failed for {brain.name}: {e}")
            return False

    async def seed_brain(self, brain: NPCBrain, story_context: str) -> bool:
        """Generate initial thoughts for a newly registered NPC."""
        prompt = BRAIN_SEED_PROMPT.format(
            npc_name=brain.name, story_context=story_context,
        )
        messages = [
            {"role": "system", "content": prompt},
        ]
        try:
            response = await chat_completion(
                messages, sampling={"temperature": 0.8, "max_tokens": 200},
            )
            thoughts = self._parse_json_response(response)
            if thoughts:
                brain.thoughts = thoughts
                return True
            return False
        except Exception as e:
            print(f"[Inner-Self] Brain seeding failed for {brain.name}: {e}")
            return False

    # ── Context Building ─────────────────────────────────────────────

    def build_context_block(
        self, recent_text: str, max_tokens: int
    ) -> str:
        """
        Build the [Character Minds] context block for NPCs present in recent text.
        Only includes brains for NPCs mentioned recently.
        """
        if not self.enabled or not self.brains:
            return ""

        text_lower = recent_text.lower()
        blocks = []
        total_tokens = count_tokens("[Character Minds]\n")

        for key, brain in self.brains.items():
            if not brain.enabled or not brain.thoughts:
                continue
            if brain.name.lower() not in text_lower:
                continue

            block = brain.format_for_context()
            block_tokens = count_tokens(block + "\n")
            if total_tokens + block_tokens > max_tokens:
                break
            blocks.append(block)
            total_tokens += block_tokens

        if not blocks:
            return ""

        return "[Character Minds]\n" + "\n\n".join(blocks)

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _parse_json_response(text: str) -> dict | None:
        """Extract a JSON object from an LLM response, handling markdown fences."""
        text = text.strip()
        # Strip markdown code fences
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last fence lines
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()
        try:
            result = json.loads(text)
            if isinstance(result, dict):
                # Ensure all values are strings
                return {str(k): str(v) for k, v in result.items()}
        except json.JSONDecodeError:
            # Try to find JSON within the text
            match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
            if match:
                try:
                    result = json.loads(match.group())
                    if isinstance(result, dict):
                        return {str(k): str(v) for k, v in result.items()}
                except json.JSONDecodeError:
                    pass
        return None

    # ── Serialisation ────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "brains": {k: v.to_dict() for k, v in self.brains.items()},
        }

    def from_dict(self, data: dict):
        self.enabled = data.get("enabled", True)
        self.brains = {
            k: NPCBrain.from_dict(v)
            for k, v in data.get("brains", {}).items()
        }
