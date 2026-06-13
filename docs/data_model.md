# Database Schema & Data Models

The Steam Market Tracker uses a local SQLite database (`data/prices.db`) to cache data, record pricing history, and store local inventories.

## Schema Layout

```mermaid
erDiagram
    tracked_items {
        INTEGER id PK
        TEXT name UNIQUE
        TEXT color_hex
        TEXT item_type
        TEXT item_nameid
        TEXT image_url
        REAL alert_price
    }
    price_history {
        INTEGER id PK
        TEXT item_name FK
        REAL price
        TEXT timestamp
    }
    items_seen {
        TEXT hash_name PK
        TEXT item_type
        TEXT color_hex
        TEXT icon_url
        TEXT last_seen
    }
    items_owned {
        TEXT hash_name PK
        INTEGER count
        TEXT last_synced
    }
    price_snapshots {
        TEXT item_name PK
        REAL ask
        REAL buy_highest
        INTEGER buy_count
        TEXT timestamp
    }
    image_cache {
        TEXT hash_name PK
        BLOB image_data
        TEXT cached_at
    }
```

---

## Table Descriptions

### 1. `tracked_items`
Tracks individual items configured by the user for monitoring.
- `name`: Steam Market hash name.
- `color_hex`: Hex code color for UI highlights (based on item rarity).
- `alert_price`: The target price threshold. If the market price falls below this number, a notification is dispatched.

### 2. `price_history`
Stores historical record listings for graph plotting.
- `item_name`: Associated tracked item.
- `price`: Market value at poll time.
- `timestamp`: ISO-8601 formatting of record entry.

### 3. `items_seen`
Acts as an index of all items ever returned from catalog polls.
- Used to populate search lists and dynamic item auto-completes.

### 4. `items_owned`
Stores inventory quantities mapped from local save games.
- Updated during savegame synchronization runs.

### 5. `price_snapshots`
Caches the latest known pricing for rapid startup rendering before background workers fetch live values.

### 6. `image_cache`
Stores raw image data (binary blobs) for item icons.
- Ensures item card components render icons instantly without issuing network requests on every startup.
