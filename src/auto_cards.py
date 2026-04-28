"""
Auto-Cards — Automatic story card generation engine.
Inspired by LewdLeah's Auto-Cards for AI Dungeon.
Detects named entities from story text and automatically generates/updates story cards.
"""

import re
from dataclasses import dataclass, asdict
from src import config
from src.llm_client import chat_completion
from src.story_cards import StoryCard, StoryCardEngine


# ─── Banned Words ────────────────────────────────────────────────────────
# Words that should never become entity candidates
BANNED_ENTITIES = {
    # Directions
    "north", "south", "east", "west", "northeast", "northwest", "southeast", "southwest",
    # Days & Months
    "sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
    # Common words sometimes capitalised in fiction
    "chapter", "part", "scene", "act", "book", "volume",
    # Pronouns & determiners
    "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "us", "them",
    "my", "your", "his", "its", "our", "their", "mine", "yours", "ours", "theirs",
    "this", "that", "these", "those", "who", "what", "where", "when", "why", "how",
    # Connectors & prepositions
    "the", "a", "an", "and", "but", "or", "so", "yet", "for", "nor",
    "in", "on", "at", "to", "by", "from", "with", "about", "into", "through",
    # Common sentence starters / transitions
    "however", "meanwhile", "suddenly", "then", "after", "before", "while",
    "although", "because", "since", "until", "unless", "once", "if",
    "here", "there", "now", "just", "still", "already", "even", "also",
    "perhaps", "maybe", "certainly", "obviously", "clearly",
    "fortunately", "unfortunately", "apparently", "eventually", "finally",
    "something", "someone", "somehow", "somewhere", "nothing", "nobody",
    "everything", "everyone", "anywhere", "nowhere",
    "several", "many", "few", "some", "most", "all", "any", "each", "every",
    "another", "other", "both", "either", "neither",
    "again", "away", "back", "down", "off", "out", "over", "up",
    "yes", "no", "not", "very", "quite", "too", "only",
}

# ─── Prompts ─────────────────────────────────────────────────────────────
CARD_GENERATION_PROMPT = """\
You are a story-card writer for an interactive fiction engine. \
Based on the story context, write a brief informational entry about {entity_name}.

Rules:
- Third person, present tense
- Focus on lasting, plot-significant details (identity, role, traits, relationships, appearance)
- Skip transient details (current mood, what they just said this moment)
- 2-4 concise sentences maximum
- Mention {entity_name} by name
- Only include information established in the story so far"""

MEMORY_COMPRESSION_PROMPT = """\
Summarize the following memory notes about {entity_name} into one concise paragraph. \
Preserve the most important facts and plot developments. Past tense, third person.

Notes:
{memories}

Compressed summary:"""


# ─── Data Classes ────────────────────────────────────────────────────────
@dataclass
class EntityCandidate:
    """A potential named entity detected from story text."""
    name: str
    count: int = 0
    first_turn: int = 0
    last_turn: int = 0

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ─── Entity Extraction ──────────────────────────────────────────────────
def extract_entities(text: str) -> list[str]:
    """
    Extract potential named entities (proper nouns) from text.
    Checks both mid-sentence and sentence-start capitalised words.
    """
    if not text or len(text) < 10:
        return []

    entities = []
    sentences = re.split(r'(?<=[.!?])\s+', text)

    for sentence in sentences:
        words = sentence.split()
        if not words:
            continue

        # Process ALL words (including first) for capitalised proper nouns
        i = 0
        while i < len(words):
            raw = words[i]
            clean = re.sub(r'[^a-zA-Z\'-]', '', raw)

            if not clean or len(clean) < 2:
                i += 1
                continue

            if clean[0].isupper() and clean.lower() not in BANNED_ENTITIES:
                # Potential entity — collect consecutive capitalised words
                parts = [clean]
                j = i + 1
                while j < len(words):
                    nxt = re.sub(r'[^a-zA-Z\'-]', '', words[j])
                    if not nxt:
                        break
                    if nxt[0].isupper() and nxt.lower() not in BANNED_ENTITIES:
                        parts.append(nxt)
                        j += 1
                    elif nxt.lower() in ("the", "of", "de", "von", "van"):
                        # Allow connectors only if followed by a cap word
                        if j + 1 < len(words):
                            peek = re.sub(r'[^a-zA-Z\'-]', '', words[j + 1])
                            if peek and peek[0].isupper():
                                parts.append(nxt)
                                j += 1
                                continue
                        break
                    else:
                        break
                entity = " ".join(parts)
                if len(entity) > 1:
                    entities.append(entity)
                i = j
            else:
                i += 1

    return entities


# ─── Auto-Cards Engine ──────────────────────────────────────────────────
class AutoCardsEngine:
    """
    Manages automatic story card generation.
    Scans story text for named entities, tracks candidates,
    and generates cards when entities appear frequently enough.
    """

    def __init__(self):
        self.enabled: bool = True
        self.candidates: dict[str, EntityCandidate] = {}
        self.generated_ids: set[str] = set()
        self.card_memories: dict[str, list[str]] = {}
        self.cooldown: int = 0
        self.last_scan_turn: int = 0

    # ── Scanning ─────────────────────────────────────────────────────

    def scan_text(self, text: str, turn: int):
        """Scan text for named entities and update candidates."""
        if not self.enabled:
            return
        for entity in extract_entities(text):
            key = entity.lower()
            if key in self.candidates:
                cand = self.candidates[key]
                if turn > cand.last_turn:
                    cand.count += 1
                    cand.last_turn = turn
            else:
                self.candidates[key] = EntityCandidate(
                    name=entity, count=1, first_turn=turn, last_turn=turn,
                )

    def get_ready_candidates(self, card_engine: StoryCardEngine) -> list[EntityCandidate]:
        """Return candidates that have enough mentions and cooldown is clear."""
        if self.cooldown > 0:
            return []

        existing = {c.name.lower() for c in card_engine.cards}
        for card in card_engine.cards:
            for kw in card.keywords:
                existing.add(kw.lower())

        ready = [
            c for key, c in self.candidates.items()
            if c.count >= config.AUTO_CARD_MIN_MENTIONS and key not in existing
        ]
        ready.sort(key=lambda c: c.count, reverse=True)
        return ready

    # ── Generation ───────────────────────────────────────────────────

    async def generate_card(
        self,
        candidate: EntityCandidate,
        story_context: str,
        card_engine: StoryCardEngine,
    ) -> StoryCard | None:
        """Generate a story card for a candidate entity via LLM."""
        prompt = CARD_GENERATION_PROMPT.format(entity_name=candidate.name)
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Story context:\n{story_context}\n\nWrite the entry for {candidate.name}:"},
        ]
        try:
            entry = await chat_completion(
                messages, sampling={"temperature": 0.7, "max_tokens": 150},
            )
            entry = entry.strip()
            if not entry or len(entry) < 10:
                return None

            card = StoryCard(
                name=candidate.name,
                keywords=[candidate.name],
                entry=entry,
                priority=4,
                enabled=True,
                auto_generated=True,
            )
            card_engine.add_card(card)
            self.generated_ids.add(card.id)
            self.card_memories[card.id] = []
            self.cooldown = config.AUTO_CARD_COOLDOWN

            # Remove from candidates
            key = candidate.name.lower()
            self.candidates.pop(key, None)
            return card

        except Exception as e:
            print(f"[Auto-Cards] Generation failed for {candidate.name}: {e}")
            return None

    # ── Memory Updates ───────────────────────────────────────────────

    def update_memories(self, card_engine: StoryCardEngine, new_text: str, turn: int):
        """Append relevant sentences to auto-card memory banks."""
        if not self.enabled or not new_text:
            return
        text_lower = new_text.lower()

        for card_id in list(self.generated_ids):
            card = card_engine.get_card(card_id)
            if not card:
                self.generated_ids.discard(card_id)
                continue

            if not any(kw.lower() in text_lower for kw in card.keywords):
                continue

            # Extract up to 2 sentences mentioning the entity
            sentences = re.split(r'(?<=[.!?])\s+', new_text)
            relevant = []
            for sent in sentences:
                if any(kw.lower() in sent.lower() for kw in card.keywords):
                    relevant.append(sent.strip())
                if len(relevant) >= 2:
                    break

            if relevant:
                memory = f"[Turn {turn}] " + " ".join(relevant)
                if card_id not in self.card_memories:
                    self.card_memories[card_id] = []
                if memory not in self.card_memories[card_id]:
                    self.card_memories[card_id].append(memory)

    async def maybe_compress_memories(self, card_engine: StoryCardEngine):
        """Compress memory banks that have grown too large."""
        limit = config.AUTO_CARD_MEMORY_LIMIT
        for card_id, memories in list(self.card_memories.items()):
            if sum(len(m) for m in memories) < limit:
                continue
            card = card_engine.get_card(card_id)
            if not card:
                continue
            try:
                prompt = MEMORY_COMPRESSION_PROMPT.format(
                    entity_name=card.name, memories="\n".join(memories),
                )
                compressed = await chat_completion(
                    [
                        {"role": "system", "content": "You are a concise summarizer."},
                        {"role": "user", "content": prompt},
                    ],
                    sampling={"temperature": 0.3, "max_tokens": 150},
                )
                card.entry = card.entry.rstrip() + "\n" + compressed.strip()
                self.card_memories[card_id] = []
            except Exception as e:
                print(f"[Auto-Cards] Compression failed for {card.name}: {e}")

    # ── Cooldown ─────────────────────────────────────────────────────

    def step_cooldown(self):
        if self.cooldown > 0:
            self.cooldown -= 1

    # ── Serialisation ────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "candidates": {k: v.to_dict() for k, v in self.candidates.items()},
            "generated_ids": list(self.generated_ids),
            "card_memories": self.card_memories,
            "cooldown": self.cooldown,
            "last_scan_turn": self.last_scan_turn,
        }

    def from_dict(self, data: dict):
        self.enabled = data.get("enabled", True)
        self.candidates = {
            k: EntityCandidate.from_dict(v)
            for k, v in data.get("candidates", {}).items()
        }
        self.generated_ids = set(data.get("generated_ids", []))
        self.card_memories = data.get("card_memories", {})
        self.cooldown = data.get("cooldown", 0)
        self.last_scan_turn = data.get("last_scan_turn", 0)
