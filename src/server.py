"""
FastAPI server — Routes, SSE streaming, static file serving.
The main entry point for the AI Story Engine.
"""

import asyncio
import json
import os
import re
import sys
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config
from src.adventure import Adventure, StoryEntry
from src.context_assembler import assemble_context, get_context_debug
from src.llm_client import stream_chat_completion, check_connection
from src.summarizer import generate_summary, should_summarize, estimate_events_tokens
from src.story_cards import StoryCard
from src.token_manager import count_tokens
from src.auto_cards import AutoCardsEngine

# ─── App Setup ───────────────────────────────────────────────────────────
app = FastAPI(title="AI Story Engine", version="1.0.0")

# Current active adventure (in-memory)
current_adventure: Adventure | None = None


# ─── Pydantic Models ────────────────────────────────────────────────────
class ActionRequest(BaseModel):
    text: str
    action_type: str = "do"  # "do", "say", "story"


class NewAdventureRequest(BaseModel):
    name: str


class TextUpdateRequest(BaseModel):
    text: str


class StoryCardRequest(BaseModel):
    name: str
    keywords: list[str]
    entry: str
    priority: int = 5
    enabled: bool = True
    use_regex: bool = False


class StoryCardUpdateRequest(BaseModel):
    name: Optional[str] = None
    keywords: Optional[list[str]] = None
    entry: Optional[str] = None
    priority: Optional[int] = None
    enabled: Optional[bool] = None
    use_regex: Optional[bool] = None


class SettingsRequest(BaseModel):
    llm_endpoint: Optional[str] = None
    context_size: Optional[int] = None
    temperature: Optional[float] = None
    min_p: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    repetition_penalty: Optional[float] = None
    max_tokens: Optional[int] = None
    summary_interval: Optional[int] = None


class EditEntryRequest(BaseModel):
    index: int
    text: str


# ─── Helper Functions ───────────────────────────────────────────────────
async def stream_with_cutoff(stream_gen):
    """
    Enforces a strict generation cutoff to approximately 150 tokens.
    Stops at exactly 2 paragraphs or a sentence boundary after ~110 words.
    """
    full_text = ""
    async for token in stream_gen:
        test_text = full_text + token
        stripped = test_text.lstrip()
        
        # 1. Paragraph Cutoff (max 2 paragraphs)
        breaks = len(re.findall(r'\n\s*\n', stripped))
        if breaks >= 2:
            break
            
        full_text += token
        yield token
        
        # 2. Word Count Fallback (~150 tokens ≈ 110 words)
        words = len(stripped.split())
        if words >= 110:
            if re.search(r'[.!?]["\']?(\s+|\n)$', full_text):
                break

def get_adventure() -> Adventure:
    global current_adventure
    if current_adventure is None:
        raise HTTPException(status_code=400, detail="No active adventure. Create or load one first.")
    return current_adventure


async def maybe_summarize(adventure: Adventure):
    """Check if we should auto-summarize and do it if needed."""
    events = adventure.get_events_since_summary()
    events_tokens = estimate_events_tokens(events)

    if not should_summarize(adventure.turn_count, adventure.last_summary_turn, events_tokens):
        return

    if len(events) < 2:
        return

    try:
        new_summary = await generate_summary(
            existing_summary=adventure.summary,
            new_events=events,
        )
        adventure.summary = new_summary
        adventure.last_summary_turn = adventure.turn_count

        # Add to memory bank
        adventure.memory_bank.add_memory(
            text=new_summary,
            turn=adventure.turn_count,
            memory_type="summary",
        )

        # Auto-save after summarization
        adventure.save()

    except Exception as e:
        print(f"[WARN] Auto-summarization failed: {e}")


async def maybe_auto_cards(adventure: Adventure):
    """Run the Auto-Cards pipeline: scan, generate, update memories."""
    ac = adventure.auto_cards
    if not ac.enabled:
        return

    turn = adventure.turn_count

    # Step cooldown
    ac.step_cooldown()

    # Scan recent text for entities
    scan_depth = config.AUTO_CARD_SCAN_DEPTH
    recent_entries = adventure.history[-scan_depth:] if adventure.history else []
    for entry in recent_entries:
        ac.scan_text(entry.text, turn)
    ac.last_scan_turn = turn

    # Check for ready candidates
    ready = ac.get_ready_candidates(adventure.card_engine)
    if ready:
        # Build story context from recent history
        context_parts = [e.text for e in adventure.history[-8:]]
        story_context = "\n\n".join(context_parts)

        # Generate one card per cycle (avoid spamming the LLM)
        candidate = ready[0]
        card = await ac.generate_card(candidate, story_context, adventure.card_engine)
        if card:
            print(f"[Auto-Cards] Generated card: {card.name}")

    # Update memories for existing auto-cards
    if adventure.history:
        last_text = adventure.history[-1].text
        ac.update_memories(adventure.card_engine, last_text, turn)

    # Compress memories if needed
    await ac.maybe_compress_memories(adventure.card_engine)

    # Save
    adventure.save()


async def maybe_npc_thoughts(adventure: Adventure):
    """Run Inner-Self thought cycles for NPCs mentioned in recent text."""
    ise = adventure.inner_self
    if not ise.enabled or not ise.brains:
        return

    turn = adventure.turn_count

    # Build recent text corpus
    recent = adventure.history[-4:] if adventure.history else []
    recent_text = " ".join(e.text for e in recent)
    if not recent_text:
        return

    # Determine which NPCs should think
    thinkers = ise.get_npcs_to_think(recent_text, turn)
    if not thinkers:
        return

    # Build story context
    context_parts = [e.text for e in adventure.history[-6:]]
    story_context = "\n\n".join(context_parts)

    for brain in thinkers:
        success = await ise.run_thought_cycle(brain, story_context, turn)
        if success:
            print(f"[Inner-Self] {brain.name} thought (turn {turn})")

    adventure.save()


# ─── API Routes ─────────────────────────────────────────────────────────

# --- Adventure Management ---

@app.post("/api/adventure/new")
async def create_adventure(req: NewAdventureRequest):
    global current_adventure
    current_adventure = Adventure(name=req.name)
    current_adventure.save()
    return {"status": "ok", "id": current_adventure.id, "name": current_adventure.name}


@app.post("/api/adventure/load")
async def load_adventure(req: dict):
    global current_adventure
    adventure_id = req.get("id")
    if not adventure_id:
        raise HTTPException(status_code=400, detail="Missing adventure ID")
    try:
        current_adventure = Adventure.load(adventure_id)
        return {"status": "ok", "id": current_adventure.id, "name": current_adventure.name}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Adventure not found")


@app.post("/api/adventure/save")
async def save_adventure():
    adv = get_adventure()
    adv.save()
    return {"status": "ok"}


@app.get("/api/adventures")
async def list_adventures():
    return Adventure.list_adventures()


@app.delete("/api/adventure/{adventure_id}")
async def delete_adventure(adventure_id: str):
    global current_adventure
    if current_adventure and current_adventure.id == adventure_id:
        current_adventure = None
    success = Adventure.delete_adventure(adventure_id)
    if not success:
        raise HTTPException(status_code=404, detail="Adventure not found")
    return {"status": "ok"}


@app.get("/api/adventure")
async def get_adventure_state():
    adv = get_adventure()
    return {
        "id": adv.id,
        "name": adv.name,
        "instructions": adv.instructions,
        "plot_essentials": adv.plot_essentials,
        "author_note": adv.author_note,
        "summary": adv.summary,
        "turn_count": adv.turn_count,
        "history": [e.to_dict() for e in adv.history],
        "story_cards": adv.card_engine.to_list(),
        "sampling": adv.sampling,
        "context_size": adv.context_size,
        "memory_count": adv.memory_bank.count,
        "auto_cards_enabled": adv.auto_cards.enabled,
        "inner_self_enabled": adv.inner_self.enabled,
        "npc_brains": [b.to_dict() for b in adv.inner_self.brains.values()],
    }


# --- Story Actions ---

@app.post("/api/action")
async def submit_action(req: ActionRequest):
    adv = get_adventure()

    # Process and add the player action
    adv.add_player_action(req.text, req.action_type)
    player_text = adv.history[-1].text

    # Assemble context
    messages = assemble_context(adv, player_text)

    async def event_stream():
        full_response = ""
        try:
            async for token in stream_with_cutoff(stream_chat_completion(
                messages, sampling=adv.sampling
            )):
                full_response += token
                yield f"data: {json.dumps({'token': token})}\n\n"

            # Add the full response to history
            adv.add_narrator_response(full_response)

            # Auto-save
            adv.save()

            # Check for auto-summarization (non-blocking)
            asyncio.create_task(maybe_summarize(adv))
            asyncio.create_task(maybe_auto_cards(adv))
            asyncio.create_task(maybe_npc_thoughts(adv))

            yield f"data: {json.dumps({'done': True, 'full_text': full_response})}\n\n"

        except Exception as e:
            error_msg = str(e)
            # Remove the player action if generation failed
            if adv.history and adv.history[-1].role == "player":
                adv.history.pop()
            yield f"data: {json.dumps({'error': error_msg})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/retry")
async def retry_last():
    adv = get_adventure()

    # Remove the last narrator response
    if adv.history and adv.history[-1].role == "narrator":
        adv.history.pop()

    # Get the last player action
    if not adv.history or adv.history[-1].role != "player":
        raise HTTPException(status_code=400, detail="No action to retry")

    player_text = adv.history[-1].text

    # Reassemble context
    messages = assemble_context(adv, player_text)

    async def event_stream():
        full_response = ""
        try:
            async for token in stream_with_cutoff(stream_chat_completion(
                messages, sampling=adv.sampling
            )):
                full_response += token
                yield f"data: {json.dumps({'token': token})}\n\n"

            adv.add_narrator_response(full_response)
            adv.save()
            yield f"data: {json.dumps({'done': True, 'full_text': full_response})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/continue")
async def continue_narration():
    """Continue the story from where it left off, appending to the last narrator response."""
    adv = get_adventure()

    if not adv.history:
        raise HTTPException(status_code=400, detail="No story to continue")

    # Build context with a continuation prompt
    messages = assemble_context(adv, "")

    # Add a continuation nudge
    messages.append({
        "role": "user",
        "content": "[Continue the narration from exactly where you left off. Do not repeat anything. Write the next two paragraphs.]"
    })

    async def event_stream():
        full_response = ""
        try:
            async for token in stream_with_cutoff(stream_chat_completion(
                messages, sampling=adv.sampling
            )):
                full_response += token
                yield f"data: {json.dumps({'token': token})}\n\n"

            # Append to the last narrator entry or add new one
            if adv.history and adv.history[-1].role == "narrator":
                adv.history[-1].text += "\n\n" + full_response.strip()
            else:
                adv.add_narrator_response(full_response)

            adv.save()
            yield f"data: {json.dumps({'done': True, 'full_text': full_response})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/undo")
async def undo_last():
    adv = get_adventure()
    success = adv.undo()
    if not success:
        raise HTTPException(status_code=400, detail="Nothing to undo")
    adv.save()
    return {"status": "ok", "history": [e.to_dict() for e in adv.history]}


@app.post("/api/edit")
async def edit_entry(req: EditEntryRequest):
    adv = get_adventure()
    if req.index < 0 or req.index >= len(adv.history):
        raise HTTPException(status_code=400, detail="Invalid entry index")
    adv.history[req.index].text = req.text
    adv.save()
    return {"status": "ok"}


@app.post("/api/rewind")
async def rewind_to_entry(req: dict):
    """Delete all entries after the given index (keep entry at index)."""
    adv = get_adventure()
    index = req.get("index", -1)
    if index < 0 or index >= len(adv.history):
        raise HTTPException(status_code=400, detail="Invalid index")
    adv.history = adv.history[:index + 1]
    adv.updated_at = __import__("time").time()
    adv.save()
    return {"status": "ok", "history": [e.to_dict() for e in adv.history]}


@app.post("/api/delete-entry")
async def delete_single_entry(req: dict):
    """Delete a single entry from history."""
    adv = get_adventure()
    index = req.get("index", -1)
    if index < 0 or index >= len(adv.history):
        raise HTTPException(status_code=400, detail="Invalid index")
    adv.history.pop(index)
    adv.updated_at = __import__("time").time()
    adv.save()
    return {"status": "ok", "history": [e.to_dict() for e in adv.history]}


# --- Context Configuration ---

@app.put("/api/instructions")
async def update_instructions(req: TextUpdateRequest):
    adv = get_adventure()
    adv.instructions = req.text
    adv.save()
    return {"status": "ok", "tokens": count_tokens(req.text)}


@app.put("/api/plot-essentials")
async def update_plot_essentials(req: TextUpdateRequest):
    adv = get_adventure()
    adv.plot_essentials = req.text
    adv.save()
    return {"status": "ok", "tokens": count_tokens(req.text)}


@app.put("/api/author-note")
async def update_author_note(req: TextUpdateRequest):
    adv = get_adventure()
    adv.author_note = req.text
    adv.save()
    return {"status": "ok", "tokens": count_tokens(req.text)}


# --- Story Cards ---

@app.get("/api/story-cards")
async def get_story_cards():
    adv = get_adventure()
    return adv.card_engine.to_list()


@app.post("/api/story-cards")
async def create_story_card(req: StoryCardRequest):
    adv = get_adventure()
    card = StoryCard(
        name=req.name,
        keywords=req.keywords,
        entry=req.entry,
        priority=req.priority,
        enabled=req.enabled,
        use_regex=req.use_regex,
    )
    adv.card_engine.add_card(card)
    adv.save()
    return {"status": "ok", "card": card.to_dict()}


@app.put("/api/story-cards/{card_id}")
async def update_story_card(card_id: str, req: StoryCardUpdateRequest):
    adv = get_adventure()
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    success = adv.card_engine.update_card(card_id, updates)
    if not success:
        raise HTTPException(status_code=404, detail="Card not found")
    adv.save()
    return {"status": "ok"}


@app.delete("/api/story-cards/{card_id}")
async def delete_story_card(card_id: str):
    adv = get_adventure()
    success = adv.card_engine.remove_card(card_id)
    if not success:
        raise HTTPException(status_code=404, detail="Card not found")
    adv.save()
    return {"status": "ok"}


# --- Auto-Cards ---

@app.put("/api/auto-cards/toggle")
async def toggle_auto_cards(req: dict):
    adv = get_adventure()
    enabled = req.get("enabled")
    if enabled is None:
        adv.auto_cards.enabled = not adv.auto_cards.enabled
    else:
        adv.auto_cards.enabled = bool(enabled)
    adv.save()
    return {"status": "ok", "enabled": adv.auto_cards.enabled}


@app.get("/api/auto-cards/candidates")
async def get_auto_card_candidates():
    adv = get_adventure()
    candidates = [
        {"name": c.name, "count": c.count, "first_turn": c.first_turn}
        for c in adv.auto_cards.candidates.values()
    ]
    candidates.sort(key=lambda c: c["count"], reverse=True)
    return {
        "enabled": adv.auto_cards.enabled,
        "cooldown": adv.auto_cards.cooldown,
        "candidates": candidates,
        "generated_count": len(adv.auto_cards.generated_ids),
    }


# --- Inner-Self (NPC Brains) ---

@app.put("/api/inner-self/toggle")
async def toggle_inner_self(req: dict):
    adv = get_adventure()
    enabled = req.get("enabled")
    if enabled is None:
        adv.inner_self.enabled = not adv.inner_self.enabled
    else:
        adv.inner_self.enabled = bool(enabled)
    adv.save()
    return {"status": "ok", "enabled": adv.inner_self.enabled}


@app.get("/api/npc-brains")
async def list_npc_brains():
    adv = get_adventure()
    return {
        "enabled": adv.inner_self.enabled,
        "brains": [b.to_dict() for b in adv.inner_self.brains.values()],
    }


@app.post("/api/npc-brains")
async def register_npc_brain(req: dict):
    adv = get_adventure()
    name = req.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="NPC name required")

    brain = adv.inner_self.register_npc(name, auto=False)

    # Seed initial thoughts if story has context
    if not brain.thoughts and adv.history:
        context_parts = [e.text for e in adv.history[-8:]]
        story_context = "\n\n".join(context_parts)
        await adv.inner_self.seed_brain(brain, story_context)

    adv.save()
    return {"status": "ok", "brain": brain.to_dict()}


@app.put("/api/npc-brains/{npc_name}")
async def update_npc_brain(npc_name: str, req: dict):
    adv = get_adventure()
    thoughts = req.get("thoughts")
    enabled = req.get("enabled")

    brain = adv.inner_self.get_brain(npc_name)
    if not brain:
        raise HTTPException(status_code=404, detail="NPC brain not found")

    if thoughts is not None and isinstance(thoughts, dict):
        brain.thoughts = {str(k): str(v) for k, v in thoughts.items()}
    if enabled is not None:
        brain.enabled = bool(enabled)

    adv.save()
    return {"status": "ok", "brain": brain.to_dict()}


@app.delete("/api/npc-brains/{npc_name}")
async def delete_npc_brain(npc_name: str):
    adv = get_adventure()
    success = adv.inner_self.unregister_npc(npc_name)
    if not success:
        raise HTTPException(status_code=404, detail="NPC brain not found")
    adv.save()
    return {"status": "ok"}


@app.post("/api/npc-brains/promote/{card_id}")
async def promote_card_to_brain(card_id: str):
    """Promote an auto-generated story card to an Inner-Self NPC brain."""
    adv = get_adventure()
    card = adv.card_engine.get_card(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Story card not found")

    # Check if brain already exists
    existing = adv.inner_self.get_brain(card.name)
    if existing:
        return {"status": "ok", "brain": existing.to_dict(), "already_existed": True}

    # Register and seed the brain
    brain = adv.inner_self.register_npc(card.name, auto=True)
    if adv.history:
        context_parts = [e.text for e in adv.history[-8:]]
        story_context = "\n\n".join(context_parts)
        await adv.inner_self.seed_brain(brain, story_context)

    adv.save()
    return {"status": "ok", "brain": brain.to_dict()}


# --- Debug & Settings ---

@app.get("/api/context-debug")
async def context_debug():
    adv = get_adventure()
    last_action = ""
    if adv.history and adv.history[-1].role == "player":
        last_action = adv.history[-1].text
    return get_context_debug(adv, last_action)


@app.get("/api/token-usage")
async def token_usage():
    adv = get_adventure()
    # Quick token count for each component
    return {
        "instructions": count_tokens(adv.instructions),
        "plot_essentials": count_tokens(adv.plot_essentials),
        "author_note": count_tokens(adv.author_note),
        "summary": count_tokens(adv.summary),
        "history_entries": len(adv.history),
        "story_cards": len(adv.card_engine.cards),
        "memories": adv.memory_bank.count,
        "context_size": adv.context_size,
    }


@app.put("/api/settings")
async def update_settings(req: SettingsRequest):
    adv = get_adventure()

    if req.llm_endpoint is not None:
        config.save_user_config({
            **config.load_user_config(),
            "LLM_ENDPOINT": req.llm_endpoint,
        })

    if req.context_size is not None:
        adv.context_size = req.context_size

    sampling_fields = {
        "temperature": req.temperature,
        "min_p": req.min_p,
        "top_p": req.top_p,
        "top_k": req.top_k,
        "repetition_penalty": req.repetition_penalty,
        "max_tokens": req.max_tokens,
    }
    for key, value in sampling_fields.items():
        if value is not None:
            adv.sampling[key] = value

    adv.save()
    return {"status": "ok"}


@app.get("/api/connection")
async def check_llm_connection():
    return await check_connection()


# ─── Static Files & SPA ─────────────────────────────────────────────────

# Mount static files
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


@app.get("/")
async def serve_index():
    index_path = os.path.join(config.STATIC_DIR, "index.html")
    with open(index_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


# ─── Main ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    print("\n  ╔══════════════════════════════════════╗")
    print("  ║        AI STORY ENGINE v1.0          ║")
    print("  ║   http://localhost:8000               ║")
    print("  ╚══════════════════════════════════════╝\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)
