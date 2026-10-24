# Cloud Dancer & Sandstone Mahjong Suite

> A single-file, zero-dependency traditional **Mahjong Suite** featuring **4-Player Table Mahjong**, **3D Layered Solitaire**, and an AI Sensei powered by **Gemini 3.8 Flash**, built in Python with Tkinter.

---

## ✦ Visual Aesthetic

Inspired by Pantone 11-4201 **Cloud Dancer**, Warm Beige, and Layered Sandstone textures:
- **Cloud Dancer** (`#F0EEE9`) — Soft background canvas and tile faces.
- **Sandstone Tones** — Isometric depth shading and tactile layered tile stacks.
- High-contrast, minimalist iconography for Wan (Characters), Pin (Dots), Sou (Bamboo), Honors (Winds & Dragons).

## 🀄 Suite Components

### 1. Classical 4-Player Table Mahjong
- Play traditional Mahjong against 3 heuristic AI opponents (East, South, West, North).
- Full call mechanics: **Chow (Chi)**, **Pung (Pon)**, **Kong (Kan)**, and **Hu (Win / Ron / Tsumo)**.
- Discard pile tracking, wall tile draw counters, and active turn indicators.

### 2. 3D Layered Mahjong Solitaire
- Classic tile-matching puzzle with genuine isometric 3D layer perspective.
- Pre-built authentic board layouts:
  - **Turtle (Traditional)**
  - **Pyramid**
  - **Fortress**
- Gameplay features: Multi-level **Undo**, **Shuffle Remaining**, and **Hint** calculation.

### 3. Gemini 3.8 Flash Sensei Advisor
- Request strategic discard recommendations and hand potential ratings powered by Google GenAI (`google-genai` Interactions API).
- Graceful offline fallback to local tile valuation heuristics.

## 🛠️ Getting Started

### Prerequisites

- Python 3.10+ (Tkinter included in standard library)
- *(Optional)* `google-genai` package for Gemini AI Sensei integration

### Installation & Run

1. Clone the repository:
   ```bash
   git clone https://github.com/ZengLLQ/mahjong.git
   cd mahjong
   ```

2. *(Optional)* Install Google GenAI SDK:
   ```bash
   pip install google-genai
   export GEMINI_API_KEY="your_api_key_here"  # Windows PowerShell: $env:GEMINI_API_KEY="your_key"
   ```

3. Launch the game suite:
   ```bash
   python main.py
   ```

## 📄 License

This project is licensed under the [MIT License](LICENSE) - see the LICENSE file for details.
