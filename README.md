# 🖋️ AI Story Engine

A professional-grade, local-first interactive fiction engine. Experience immersive storytelling powered by state-of-the-art Large Language Models (LLMs), with deep state management and dynamic world-building tools.

![AI Story Engine UI](https://github.com/LilGremblin/LocalAIstoryteller/raw/main/static/preview.png) *(Placeholder for preview image)*

## ✨ Key Features

- **🧠 NPC Brains (Inner-Self)**: Characters have their own thoughts, motivations, and internal monologues that influence their actions and dialogue.
- **🗂️ Story Cards (Lorebook)**: Sophisticated world-building with "World Info" cards that trigger based on keywords, ensuring the AI maintains consistency with your setting.
- **📝 Smart Summarization**: Automatically condenses long-running adventures to maintain context without hitting token limits.
- **🎭 Multi-Mode Narrator**: Switch between "Do" (actions), "Say" (dialogue), and "Story" (narrative control) to steer the adventure.
- **🛠️ Context Debugger**: Peek under the hood to see exactly what information is being sent to the AI at any moment.
- **🎨 Premium Interface**: A sleek, glassmorphic dark theme designed for long writing sessions and immersive play.

## 🚀 Quick Start

### Prerequisites
- **Python 3.10+**
- **A GGUF Model**: Recommended models like `Magnum-7b-v4` or `Llama-3-8B-Instruct`. Place them in the `models/` directory.

### Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/LilGremblin/LocalAIstoryteller.git
   cd LocalAIstoryteller
   ```
2. Run the setup script to download the KoboldCPP backend:
   ```bash
   setup_koboldcpp.bat
   ```
3. Launch the engine:
   ```bash
   run.bat
   ```

## 🛠️ Technology Stack
- **Backend**: FastAPI (Python)
- **AI Backend**: KoboldCPP (llama.cpp)
- **Frontend**: Vanilla JS + CSS3 (Glassmorphism design system)
- **State**: JSON-based adventure storage

## 📜 License
This project is for personal use and creative exploration.

---
*Built with ❤️ for storytellers.*
