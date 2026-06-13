# Configuration Guide

This document describes how to configure the Steam Market Tracker.

## Environment Variables (`.env`)

The application reads configuration parameters from a `.env` file in the root directory. To set this up:

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Open `.env` and fill in the required variables.

### Available Options

| Variable Name | Description | Required | Default Value |
| --- | --- | --- | --- |
| `STEAM_SAVE_PATH` | The absolute directory path where your local game save file (`SaveFile_Live.es3`) is located. | Yes (for inventory sync) | None |
| `DISCORD_WEBHOOK_URL` | The Discord Webhook URL used to send alerts when a tracked item's price drops below the defined threshold. | No | None |

*Example `.env` configuration:*
```env
STEAM_SAVE_PATH=C:/Users/ASUS/AppData/LocalLow/GameDeveloper/TaskBarHero/Saves
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/1234567890/abcde_fg
```

---

## Local Config Database (`data/config.json`)

The application automatically saves user preferences (such as selected currency) to `data/config.json`. You do not need to edit this file manually.

### Active Settings
- **`currency_code`**: The internal Steam code representing the active currency (e.g., `1` for USD, `10` for IDR).
- **`currency_name`**: The currency shorthand (e.g., `"USD"`, `"IDR"`).
- **`currency_symbol`**: The currency symbol (e.g., `"$"` or `"Rp"`).

These settings are updated dynamically when you select a different currency in the main window dropdown list.
