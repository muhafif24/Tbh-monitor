# Steam Market Tracker - Task Bar Hero (TBH)

A robust, modern desktop GUI application designed to track Steam Community Market prices for the in-game economy of **Task Bar Hero** (App ID: `3678970`). 

This tool assists players in monitoring item price trends, tracking owned items from local inventories, and managing price alerts.

---

## Key Features

- **🛡️ Robust API Request Client**:
  - Leverages persistent `requests.Session` with a browser-like user agent.
  - Built-in multi-layered retry logic (`tenacity`) with configurable exponential backoff delays.
  - Handles response status codes gracefully (including server errors and limit warnings).
  - Proper encoding helper for item names to ensure clean query requests.

- **🔄 Local Inventory Integration**:
  - Automatically loads inventory data from local game save files (`SaveFile_Live.es3`).
  - Matches raw in-game item indices to official Steam Community Market names using dynamically cached definitions from the `taskbarhero.wiki` items list.

- **🗄️ Locally Cached Storage (SQLite & Config)**:
  - Cache-backed database (`prices.db`) stores historical pricing, items seen, active inventory counts, and image assets.
  - Optimizes startup speeds and reduces network traffic by caching static image resources locally.

- **⚙️ Multithreaded Background Workers**:
  - Uses daemon background threads (`PriceWorker` and `ListingWorker`) to manage polling tasks in the background.
  - Features collision protection and clean thread termination controls to ensure stability.

- **🎨 Modern Dark Mode GUI**:
  - Built with `CustomTkinter` for a clean, responsive layout.
  - Features fixed headers/footers with a scrollable list of tracked items.
  - Provides interactive card components displaying current price status, local inventory counts, and customizable alert thresholds.

- **🔔 Discord Webhook Integration**:
  - Supports sending custom alerts and notification messages directly to a designated Discord webhook.

---

## Technical Stack

- **Core**: Python 3.9+
- **GUI Framework**: `CustomTkinter`
- **Database**: SQLite3 (persistent file)
- **API Request Management**: `requests`, `tenacity`
- **Plotting & Visuals**: `matplotlib`, `pillow`
- **Encryption Helper**: `pycryptodome`

---

## Project Structure

```text
├── data/                       # Local data folder (git-ignored, holds SQLite & config)
├── referensi/                  # Research documents & code prototypes
├── src/                        # Main Application Code
│   ├── gui/                    # UI Windows, dialogs, and components
│   │   ├── app.py              # Main Application Entry / Controller Window
│   │   ├── add_dialog.py       # Modal Dialog to add tracked items
│   │   └── item_card.py        # Individual UI grid component for tracked items
│   ├── config.py               # Steam Currency configurations
│   ├── database.py             # SQLite3 local database managers & migrations
│   ├── item_catalog.py         # Caching and fetch controller for market catalog
│   ├── item_mapping.py         # Translator maps (ItemKey <=> Steam Market Name)
│   ├── notifier.py             # Discord webhook notifier
│   ├── save_reader.py          # Inventory save integration module
│   ├── steam_api.py            # API request controller & retry policies
│   └── worker.py               # Background daemon threads
├── tests/                      # Unit & integration tests
├── .env.example                # Sample environment configurations
├── requirements.txt            # System dependencies manifest
└── main.py                     # Primary runtime entrypoint
```

---

## Installation & Setup

1. **Clone the Repository**:
   ```bash
   git clone <repository_url>
   cd Tbh-monitor
   ```

2. **Setup Virtual Environment**:
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # macOS/Linux:
   source .venv/bin/activate
   ```

3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment Configurations**:
   Copy the example environment template and configure your paths:
   ```bash
   cp .env.example .env
   ```
   Open the newly created `.env` file and adjust:
   - `STEAM_SAVE_PATH`: Full absolute directory path pointing to your Task Bar Hero saves folder (where `SaveFile_Live.es3` is stored).
   - `DISCORD_WEBHOOK_URL`: Optional Discord Webhook endpoint to receive alerts.

---

## How to Run

1. **Start the Application**:
   Ensure your virtual environment is active, then execute:
   ```bash
   python main.py
   ```

2. **Run Tests**:
   To verify database, notifier, and worker thread functions, run:
   ```bash
   python -m unittest discover tests/
   ```

---

## License

Distributed under the MIT License. See `LICENSE` for more details.

---

## Disclaimer

This project is an unofficial fan-made tool and is not affiliated, associated, authorized, endorsed by, or in any way officially connected with Steam, Valve Corporation, or the developers of Task Bar Hero.

- **Steam ToS Compliance**: This application retrieves public market prices at polite intervals. However, using automated tools to query Steam services is at your own risk. The developer is not responsible for any temporary IP bans or restrictions imposed by Steam.
- **Savegame Safety**: The save file integration is strictly read-only. It parses local data to display item quantities and does not modify, tamper with, or write back to your game files.
