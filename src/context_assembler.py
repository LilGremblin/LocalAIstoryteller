"""
Context Assembler — The core prompt builder.
Assembles the full prompt following AI Dungeon's exact priority hierarchy.
"""

from src import config
from src.token_manager import TokenBudget, count_tokens, count_messages_tokens
from src.adventure import Adventure


def assemble_context(adventure: Adventure, current_action: str = "") -> list[dict]:
    """
    Build the complete prompt from all context components.
    
    Priority order (last to be cut = highest priority):
    1. AI Instructions (system prompt)
    2. Plot Essentials
    3. Triggered Story Cards
    4. Story Summary (rolling auto-summary)
    5. Memory Bank retrievals
    6. Story History (recent turns)
    7. Author's Note
    8. Last Action (current player input)
    
    Returns a list of chat messages: [{"role": ..., "content": ...}]
    """
    budget = TokenBudget(
        max_context=adventure.context_size,
        response_budget=adventure.sampling.get(
            "max_tokens", config.RESPONSE_TOKEN_BUDGET
        ),
    )

    messages = []

    # ─── 1. System prompt (AI Instructions) ──────────────────────────
    system_parts = []

    # Base instructions
    instructions = budget.allocate(
        "instructions",
        adventure.instructions,
        config.BUDGET_INSTRUCTIONS,
    )
    if instructions:
        system_parts.append(instructions)

    # ─── 2. Plot Essentials ──────────────────────────────────────────
    plot = budget.allocate(
        "plot_essentials",
        adventure.plot_essentials,
        config.BUDGET_PLOT_ESSENTIALS,
    )
    if plot:
        system_parts.append(f"[Plot Essentials]\n{plot}")

    # ─── 3. Story Cards (triggered) ─────────────────────────────────
    recent_actions = adventure.get_recent_actions()
    recent_responses = adventure.get_recent_responses()

    # Include the current action in the scan
    scan_actions = recent_actions + ([current_action] if current_action else [])

    cards_text = adventure.card_engine.build_triggered_text(
        scan_actions,
        recent_responses,
        config.BUDGET_STORY_CARDS,
    )
    if cards_text:
        cards_text = budget.allocate(
            "story_cards", cards_text, config.BUDGET_STORY_CARDS
        )
        if cards_text:
            system_parts.append(cards_text)
    else:
        budget.allocations["story_cards"] = 0

    # ─── 4. Story Summary ───────────────────────────────────────────
    if adventure.summary:
        summary_text = budget.allocate(
            "summary",
            f"[Story So Far]\n{adventure.summary}",
            config.BUDGET_SUMMARY,
        )
        if summary_text:
            system_parts.append(summary_text)
    else:
        budget.allocations["summary"] = 0

    # ─── 5. Memory Bank retrievals ──────────────────────────────────
    # Build a query from the current action + recent context
    memory_query = current_action
    if recent_actions:
        memory_query = " ".join(recent_actions[-2:]) + " " + memory_query

    memory_text = adventure.memory_bank.build_memory_text(
        memory_query, config.BUDGET_MEMORY_BANK
    )
    if memory_text:
        memory_text = budget.allocate(
            "memory_bank", memory_text, config.BUDGET_MEMORY_BANK
        )
        if memory_text:
            system_parts.append(memory_text)
    else:
        budget.allocations["memory_bank"] = 0

    # ─── 5b. NPC Brains (Inner-Self) ────────────────────────────────
    recent_corpus = " ".join(recent_actions + recent_responses)
    if current_action:
        recent_corpus += " " + current_action

    brains_text = adventure.inner_self.build_context_block(
        recent_corpus, config.BUDGET_NPC_BRAINS
    )
    if brains_text:
        brains_text = budget.allocate(
            "npc_brains", brains_text, config.BUDGET_NPC_BRAINS
        )
        if brains_text:
            system_parts.append(brains_text)
    else:
        budget.allocations["npc_brains"] = 0

    # Build the system message from all parts
    system_content = "\n\n".join(system_parts)
    messages.append({"role": "system", "content": system_content})

    # ─── 6. Story History (fills remaining budget) ───────────────────
    # Reserve space for author's note and last action
    author_note_tokens = count_tokens(adventure.author_note) if adventure.author_note else 0
    last_action_tokens = count_tokens(current_action) if current_action else 0
    reserved = author_note_tokens + last_action_tokens + 50  # padding

    history_budget = budget.remaining() - reserved
    history_messages = adventure.get_history_for_context()

    # Fit as many recent history messages as possible
    fitted_history = []
    history_tokens_used = 0

    for msg in reversed(history_messages):
        msg_tokens = count_tokens(msg["content"]) + 4  # message overhead
        if history_tokens_used + msg_tokens > history_budget:
            break
        fitted_history.insert(0, msg)
        history_tokens_used += msg_tokens

    budget.allocations["history"] = history_tokens_used
    budget.available -= history_tokens_used

    messages.extend(fitted_history)

    # ─── 7. Author's Note (injected near the end) ───────────────────
    if adventure.author_note:
        author_text = budget.allocate(
            "author_note",
            adventure.author_note,
            config.BUDGET_AUTHOR_NOTE,
        )
        if author_text:
            messages.append({
                "role": "system",
                "content": f"[Author's Note: {author_text}]",
            })
    else:
        budget.allocations["author_note"] = 0

    # ─── 8. Last Action (current player input) ──────────────────────
    if current_action:
        budget.allocations["last_action"] = count_tokens(current_action)
        messages.append({"role": "user", "content": current_action})

    return messages


def get_context_debug(adventure: Adventure, current_action: str = "") -> dict:
    """
    Build context and return a debug view showing exactly what's sent to the AI.
    Like AI Dungeon's "View Context" feature.
    """
    messages = assemble_context(adventure, current_action)

    budget = TokenBudget(
        max_context=adventure.context_size,
        response_budget=adventure.sampling.get(
            "max_tokens", config.RESPONSE_TOKEN_BUDGET
        ),
    )

    # Count actual tokens
    total_tokens = count_messages_tokens(messages)

    debug = {
        "messages": messages,
        "total_tokens": total_tokens,
        "max_context": adventure.context_size,
        "response_budget": adventure.sampling.get(
            "max_tokens", config.RESPONSE_TOKEN_BUDGET
        ),
        "message_count": len(messages),
    }

    return debug
