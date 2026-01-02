# RSSDOS — World Feed (Retro Desktop News Terminal)
A **single-file Python desktop app** that aggregates global RSS feeds into a **retro, terminal-style GUI** with **automatic text-to-speech headlines**.
Built for fast scanning, low distraction, and hands-free updates.

---

## Features

### 📰 Multi-Source News Aggregation
- World, News, Finance, Economy, Trade
- Science, Research, Tech
- Weather (Environment Canada warnings)
- RSS + Atom support (best-effort parser)

### 🖥 Retro Three-Pane UI (Tkinter)
- **Top horizontal HEADLINES ribbon**
  - Always shows newest items
  - Click to select, double-click to open
- **Left pane**
  - Dense scan list with fixed columns
  - Color-coded by category
- **Right pane**
  - Clean detail view
  - Wrapped text + clickable links

### 🔊 Built-In Windows TTS (Zero Dependencies)
- Uses **Windows System.Speech.Synthesis**
- No pip installs
- Non-blocking worker thread
- Immediate stop support

### 🔁 Auto-Speak New Headlines (Smart Latch)
- Speaks **only when the newest headline changes**
- No repeats
- Optional summary inclusion
- Periodic auto-refresh loop

---

## Keyboard Controls

| Key | Action |
|----|------|
| `1–9` | Toggle categories |
| `A` | Toggle all categories |
| `R` | Force live refresh |
| `C` | Clear cache + refresh |
| `G` | Group by category / time |
| `F` | Feed status window |
| `Enter` | Open selected article |
| `S` | Speak selected item |
| `H` | Speak newest headline |
| `X` | Stop speaking |

---

## Auto-Refresh & Auto-Speak

Configurable at the top of the file:
AUTO_REFRESH_SECONDS = 180
AUTO_SPEAK_NEWEST_HEADLINE_ON_CHANGE = True
AUTO_SPEAK_ON_START = False
AUTO_SPEAK_INCLUDE_SUMMARY = False 

Behavior:
Refreshes feeds automatically
Tracks newest headline by ID
Speaks only when it changes

Requirements
Windows 10 / 11
Python 3.10+
No external Python dependencies
Internet access for RSS feeds
Linux/macOS: GUI works, TTS section is Windows-specific.

Run:
python rss.py

Cache files will be created locally:

rssdos_cache.json
rssdos_seen.json

Feed Status View
Press F to open:
Per-feed OK / FAIL status
Item counts
Active URL
Error diagnostics
Design Goals
Fast information density
Keyboard-first navigation
Minimal visual noise
Hands-free consumption
Single-file deployability
License - MIT — do what you want, attribution appreciated.

Built by Matt / VE7LTX
