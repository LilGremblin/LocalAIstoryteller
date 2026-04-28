"""
Configuration for the AI Story Engine.
All settings with sensible defaults for 12GB VRAM setups.
"""

import os
import json

# ─── Paths ───────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADVENTURES_DIR = os.path.join(BASE_DIR, "adventures")
STATIC_DIR = os.path.join(BASE_DIR, "static")
CONFIG_FILE = os.path.join(BASE_DIR, "user_config.json")

# Ensure directories exist
os.makedirs(ADVENTURES_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

# ─── LLM Backend ────────────────────────────────────────────────────────
LLM_ENDPOINT = "http://localhost:5001/v1"  # KoboldCPP default
LLM_MODEL = "local-model"  # Placeholder — local backends ignore this

# ─── Context Window ─────────────────────────────────────────────────────
MAX_CONTEXT_TOKENS = 16384  # Override based on your model
RESPONSE_TOKEN_BUDGET = 350  # 350 max tokens to avoid cutoff, while prompt instructs 150 word limit

# ─── Token Budgets (max tokens per component) ───────────────────────────
BUDGET_INSTRUCTIONS = 600
BUDGET_PLOT_ESSENTIALS = 600
BUDGET_STORY_CARDS = 500
BUDGET_SUMMARY = 800
BUDGET_MEMORY_BANK = 400
BUDGET_AUTHOR_NOTE = 200
BUDGET_LAST_ACTION = 300
# Remaining tokens go to Story History

# ─── Auto-Summary ───────────────────────────────────────────────────────
SUMMARY_INTERVAL = 5  # Summarize every N turns
SUMMARY_HISTORY_THRESHOLD = 2000  # Also trigger if history exceeds this many tokens

# ─── Memory Bank ────────────────────────────────────────────────────────
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
MEMORY_TOP_K = 5  # Number of memories to retrieve per turn
MEMORY_MIN_SCORE = 0.3  # Minimum similarity score to include a memory

# ─── Story Cards ────────────────────────────────────────────────────────
CARD_SCAN_DEPTH = 3  # Scan last N actions + responses for keyword triggers

# ─── Auto-Cards ─────────────────────────────────────────────────────────
AUTO_CARDS_ENABLED = True  # Enabled by default on new adventures
AUTO_CARD_COOLDOWN = 10  # Min turns between card generations
AUTO_CARD_MIN_MENTIONS = 3  # Entity must appear N+ times before generating
AUTO_CARD_MEMORY_LIMIT = 800  # Chars before compressing card memories
AUTO_CARD_SCAN_DEPTH = 6  # How many recent entries to scan for entities

# ─── Inner-Self (NPC Brains) ────────────────────────────────────────────
INNER_SELF_ENABLED = True  # Enabled by default on new adventures
NPC_THOUGHT_CHANCE = 0.5  # Probability of thought per relevant NPC per turn
NPC_MAX_THOUGHTS = 8  # Max brain entries before pruning oldest
BUDGET_NPC_BRAINS = 400  # Token budget for brain context injection
NPC_AUTO_REGISTER = False  # Manual promotion only — use the UI to promote auto-cards to Inner-Self

# ─── Sampling Parameters ────────────────────────────────────────────────
DEFAULT_SAMPLING = {
    "temperature": 0.85,
    "min_p": 0.05,
    "top_p": 1.0,
    "top_k": 0,
    "repetition_penalty": 1.1,
    "max_tokens": RESPONSE_TOKEN_BUDGET,
}

# ─── Default Prompts ────────────────────────────────────────────────────
DEFAULT_INSTRUCTIONS = """\
You are an expert, dynamic Game Master and interactive fiction narrator. You create immersive, living worlds spanning any genre (fantasy, sci-fi, modern, noir, etc.) based on the established context.

ROLE & TONE:
- Write exclusively in the second person ("you") as the narrator. The user is the protagonist.
- Adapt your tone perfectly to the current genre, atmosphere, and established lore.
- Write vivid, evocative prose. Use sensory details (sight, sound, smell, texture) to describe environments. Show, don't tell.

CORE MECHANICS & BIAS:
- Your absolute priority is to build upon what the player wants to do. The player drives the story.
- Bias the narrative toward logical, interesting consequences of the player's actions. 
- Do NOT invent major unprompted plot twists or hijack the story away from the player's current focus.
- NPCs must have distinct voices and motivations, reacting realistically to the player's behavior.
- Ensure the world feels reactive and alive. Ground the player in their immediate surroundings.

NARRATIVE CONSTRAINTS:
- Keep the narrative flowing smoothly. Provide meaningful, in-world consequences for player actions.
- Describe immediate, grounded events—not distant or unrelated exposition.
- Never summarize what just happened. Always move the plot forward.
- Keep sentences varied in length to maintain a literary flow. Avoid clichés and repetitive sentence structures.

STRICT PROHIBITIONS:
- NEVER speak, think, or make decisions for the player character. Only narrate what they perceive and what happens around them.
- NEVER ask the player questions. End each response at a natural story beat, a moment of tension, or a discovery.
- NEVER use phrases like: "What will you do?", "The choice is yours", "You feel compelled to...".
- NEVER break character, provide meta-commentary, or acknowledge being an AI.

LENGTH CONSTRAINT: 
- You must write EXACTLY 2 paragraphs. Keep your total response concise (around 100-150 words). Ensure you finish your thoughts completely and end gracefully.\
"""

DEFAULT_AUTHOR_NOTE = ""
DEFAULT_PLOT_ESSENTIALS = ""


def load_user_config() -> dict:
    """Load user overrides from disk."""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_user_config(overrides: dict):
    """Persist user config overrides."""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(overrides, f, indent=2)


def get(key: str, default=None):
    """Get a config value with user override support."""
    overrides = load_user_config()
    if key in overrides:
        return overrides[key]
    return globals().get(key, default)
