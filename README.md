# Jarvis – Advanced Offline Windows Voice Assistant

> **Always-on, fully offline, modular voice assistant for Windows built in Python 3.**

---

## Table of Contents
1. [Overview](#overview)
2. [Features](#features)
3. [Architecture](#architecture)
4. [Folder Structure](#folder-structure)
5. [Installation](#installation)
6. [How to Run](#how-to-run)
7. [Example Commands](#example-commands)
8. [Configuration](#configuration)
9. [Future Improvements](#future-improvements)

---

## Overview

Jarvis is a **privacy-first, 100 % offline** Windows voice assistant.
No cloud APIs are used at runtime – speech recognition is handled by
[Vosk](https://alphacephei.com/vosk/), text-to-speech by
[pyttsx3](https://pyttsx3.readthedocs.io/), and (optionally) natural-language
understanding is improved by a local LLM served by
[Ollama](https://ollama.ai/).

Say **"hey windows"**, then speak your command. Jarvis listens, understands, and acts.

---

## Features

| Category | Capabilities |
|---|---|
| **Wake word** | "hey windows" via Vosk keyword spotting |
| **Speech-to-text** | Fully offline, Vosk small English model |
| **Text-to-speech** | Offline Windows SAPI / pyttsx3 |
| **App control** | Open / close any application by name |
| **Volume control** | Up, down, mute, unmute, set percentage |
| **System actions** | Shutdown, restart, sleep, lock, screenshot |
| **File manager** | Open files/folders, delete, list directory |
| **Web actions** | Google search, YouTube search/play, open URL |
| **Multi-command** | Chain commands with "and" or "," – e.g. *"open chrome and play lo-fi"* |
| **Automation modes** | Study mode, coding mode, focus mode, custom routines |
| **Context memory** | Remembers last opened app; follow-ups like *"open it"* |
| **Developer mode** | Run Python files, run git commands, open VS Code projects |
| **Local LLM fallback** | Optional Ollama integration for richer NLU |
| **Safety** | Confirmation prompts for dangerous actions |
| **Logging** | Text log (`jarvis.log`) + structured JSON event log (`logs.json`) |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        main.py                              │
│                  JarvisAssistant (loop)                     │
└────────┬────────────────────────────┬───────────────────────┘
         │  wake event                │  pipeline
         ▼                            ▼
  ┌────────────┐            ┌──────────────────┐
  │  wake.py   │            │  listener.py     │
  │ Vosk KWS   │──fires──►  │  Vosk STT        │
  └────────────┘            └────────┬─────────┘
                                     │ raw text
                                     ▼
                            ┌──────────────────┐
                            │   brain.py       │
                            │ parse_multi()    │
                            │ Rules → Intents  │
                            │ (+ Ollama LLM)   │
                            └────────┬─────────┘
                                     │ list[Intent]
                                     ▼
                            ┌──────────────────┐
                            │   planner.py     │
                            │ Expand → Tasks   │
                            └────────┬─────────┘
                                     │ Task list
                          ┌──────────┴───────────────────────┐
                          ▼          ▼           ▼           ▼
                   ┌──────────┐ ┌────────┐ ┌─────────┐ ┌────────┐
                   │system.py │ │files.py│ │ web.py  │ │ dev.py │
                   └──────────┘ └────────┘ └─────────┘ └────────┘
                          │
                          ▼
                   ┌──────────────┐
                   │  memory.py   │
                   │ memory.json  │
                   │  logs.json   │
                   └──────────────┘
```

**Data flow:** microphone → wake word detection → STT → intent parsing
→ multi-command splitting → task planning → action execution → memory/log update → TTS response.

---

## Folder Structure

```
jarvis-windows-assistant/
│
├── main.py            # Entry point; orchestrates the pipeline
├── wake.py            # Wake-word detection (Vosk keyword grammar)
├── listener.py        # Offline STT – records one utterance via Vosk
├── brain.py           # Hybrid intent engine: rules + optional Ollama LLM
│                      #   parse_multi() splits compound "X and Y" commands
├── planner.py         # Expands intents into Tasks and dispatches them
│                      #   plan_and_run_multi() executes chained commands
├── memory.py          # Read/write persistent memory (memory.json)
├── config.py          # All settings, paths, and flags (edit or use .env)
├── utils.py           # Logger, TTS (speak), text normalisation, log_event
│
├── actions/
│   ├── __init__.py    # Registers all action handlers → dict for Planner
│   ├── system.py      # App control, volume, power management, screenshot
│   ├── files.py       # Open / delete / list files; add app mappings
│   ├── web.py         # Web search, YouTube search/play, open URL
│   └── dev.py         # Developer mode: run Python, git commands, VS Code
│
├── models/            # ← place your downloaded Vosk model here
│   └── vosk-model-small-en-us-0.15/
│
├── memory.json        # Persistent store: app mappings, routines, history
├── logs.json          # Structured NDJSON event log (auto-created at runtime)
├── jarvis.log         # Text debug log (auto-created at runtime)
├── requirements.txt   # Python dependencies
├── .env.example       # Environment variable template
└── README.md          # This file
```

---

## Installation

### Prerequisites
- **Python 3.10+** (64-bit recommended)
- **Windows 10 / 11**
- A working **microphone**
- *(Optional)* [Ollama](https://ollama.ai/) for local LLM fallback

### 1 – Clone the repository
```bash
git clone https://github.com/shlokpawade/helliwindows.git
cd helliwindows
```

### 2 – Create and activate a virtual environment
```bash
python -m venv .venv
.venv\Scripts\activate
```

### 3 – Install dependencies
```bash
pip install -r requirements.txt
```

### 4 – Download a Vosk model
```bash
# Create the models directory
mkdir models
# Download the small English model (~40 MB) from https://alphacephei.com/vosk/models
# and extract it so the path is:
#   models/vosk-model-small-en-us-0.15/
```

Direct download link:
https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip

### 5 – Configure environment variables
```bash
copy .env.example .env
# Edit .env with your preferred settings
```

### 6 – (Optional) Enable Ollama LLM fallback
```bash
# Install Ollama from https://ollama.ai/
ollama pull mistral          # or llama3, phi3, etc.
# Then in .env set:
#   USE_LOCAL_LLM=true
#   OLLAMA_MODEL=mistral
```

### 7 – (Optional) Enable developer mode
```bash
# In .env set:
#   DEVELOPER_MODE=true
#   VSCODE_PATH=code   # or full path to VS Code binary
```

---

## How to Run

```bash
# Make sure your virtual environment is active
.venv\Scripts\activate

# Start the assistant
python main.py
```

You will hear: *"Jarvis is ready. Say 'hey windows' to start."*

Speak **"hey windows"** – wait for the *"Listening …"* prompt – then say your command.

---

## Example Commands

```
# App control
hey windows … open notepad
hey windows … open it          ← re-opens last app
hey windows … close chrome

# Volume
hey windows … volume up
hey windows … set volume to 50
hey windows … mute

# Multi-command (chain with "and" or ",")
hey windows … open chrome and search for Python tutorials
hey windows … open notepad and play lo-fi
hey windows … mute, open vs code, run routine coding

# Web
hey windows … search for Python tutorials
hey windows … play lofi music on YouTube
hey windows … play lo-fi                   ← direct YouTube search
hey windows … open https://github.com

# Files
hey windows … open file C:\Users\Me\notes.txt
hey windows … list files in Downloads
hey windows … delete file C:\Users\Me\old_report.txt

# System
hey windows … shutdown
hey windows … restart
hey windows … lock
hey windows … screenshot
hey windows … what is the time
hey windows … what is the date

# Automation modes / routines
hey windows … activate study mode
hey windows … activate coding mode
hey windows … activate focus mode
hey windows … run routine my morning routine

# Memory
hey windows … remember that vlc is vlc.exe

# Developer mode (DEVELOPER_MODE=true required)
hey windows … run file C:\scripts\daily.py
hey windows … git status
hey windows … git add .
hey windows … git commit -m fix bug
hey windows … open project C:\code\myapp

# Meta
hey windows … help
hey windows … stop
```

---

## Configuration

All settings are in `config.py` and can be overridden via `.env`:

| Variable | Default | Description |
|---|---|---|
| `VOSK_MODEL_PATH` | `models/vosk-model-small-en-us-0.15` | Path to Vosk model dir |
| `USE_LOCAL_LLM` | `false` | Enable Ollama LLM fallback |
| `OLLAMA_MODEL` | `mistral` | Ollama model name |
| `OLLAMA_URL` | `http://localhost:11434/api/generate` | Ollama endpoint |
| `DEVELOPER_MODE` | `false` | Unlock dev-mode actions |
| `VSCODE_PATH` | `code` | VS Code CLI path |

---

## Future Improvements

- **Porcupine wake word** – more accurate, low-CPU wake detection (requires API key; swap `wake.py`)
- **Streaming STT** – real-time partial transcription for faster response
- **Multi-language support** – swap Vosk model for other languages
- **GUI tray icon** – system-tray indicator with mute/unmute toggle
- **Plugin system** – drop-in `actions/` modules auto-discovered at startup
- **Conversation context window** – multi-turn dialogue ("search for Python ... open the first result")
- **Custom wake words** – train a personal keyword model with Vosk
- **Home automation** – MQTT / Home Assistant integration via local network
- **Calendar & reminders** – local SQLite-backed scheduler
- **Whisper STT** – optional OpenAI Whisper local model for higher accuracy