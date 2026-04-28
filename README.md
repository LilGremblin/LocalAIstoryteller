# AI Story Engine (Work in Progress)

A local-first interactive fiction engine designed for immersive storytelling powered by Large Language Models (LLMs). This project focuses on deep state management, character consistency, and dynamic world-building.

**Status: Active Development / Work in Progress**

## Features

### NPC Brains (Inner-Self System)
Characters are equipped with an internal state management system that tracks thoughts, motivations, and internal monologues. These factors dynamically influence AI-generated actions and dialogue, providing higher behavioral consistency than standard prompting.

### Story Cards (Lorebook)
A keyword-triggered world information system. Lore cards are injected into the LLM context only when relevant keywords are detected in the recent story history, allowing for complex world-building without exceeding token limits.

### Automated Context Management
- **Smart Summarization**: Periodically condenses the story history into a concise summary to preserve long-term memory.
- **Context Debugging**: A dedicated interface to inspect the raw prompt structure and token distribution being sent to the backend.

### Multi-Mode Interaction
Steer the narrative using three distinct interaction modes:
- **Do**: Player actions.
- **Say**: Character dialogue.
- **Story**: Direct narrative intervention or world-state changes.

### Technical UI
A dark-themed interface built with Vanilla JS and CSS, utilizing a glassmorphic design system optimized for long-form reading and writing.

## Installation

### Prerequisites
- Python 3.10 or higher.
- A GGUF-formatted model (e.g., Llama-3, Mistral, or Magnum). Place models in the `models/` directory.

### Setup
1. Clone the repository:
   ```bash
   git clone https://github.com/LilGremblin/LocalAIstoryteller.git
   cd LocalAIstoryteller
   ```
2. Download the KoboldCPP backend:
   ```bash
   setup_koboldcpp.bat
   ```
3. Initialize the environment and launch the server:
   ```bash
   run.bat
   ```

## Architecture
- **Server**: Python FastAPI / Uvicorn.
- **LLM Backend**: KoboldCPP (via llama.cpp).
- **Frontend**: Single-page application using modern CSS and standard DOM APIs.
- **Storage**: Local JSON-based persistence for adventures and configurations.
