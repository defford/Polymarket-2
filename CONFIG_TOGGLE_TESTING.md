# Config Toggle Feature - Testing Guide

## Overview

The config toggle feature allows you to disable a bot's custom configuration profile, causing it to use default values instead. This is useful when refining the default bot strategy without needing to manually reset each bot's config.

## Changes Made

### Backend
1. **database.py**: Added `config_enabled` column to `bots` table with migration
2. **models.py**: Added `config_enabled` field to `BotRecord` and `UpdateBotRequest`
3. **bot_instance.py**: 
   - `BotConfigManager` now returns default config when `config_enabled=False`
   - Added `saved_config` property to access stored config
   - Added `is_config_enabled()` and `set_config_enabled()` methods
4. **swarm.py**: Passes `config_enabled` through bot creation and includes it in `list_bots()`
5. **main.py**: Updated `/api/swarm/{bot_id}/config` to return config state and `/api/swarm/{bot_id}` to accept `config_enabled`

### Frontend
1. **ConfigPanel.jsx**: Added toggle switch at top of config panel
2. **BotDetailView.jsx**: Added state management and API calls for toggle

## Manual Testing Steps

### 1. Database Migration Test
```bash
# Start the backend - this will run the migration
cd backend
python main.py
```

Verify in the database:
```bash
sqlite3 ../bot_data.db "PRAGMA table_info(bots);"
# Should show config_enabled column
```

### 2. API Testing

#### Get bot config (should show config_enabled field)
```bash
curl http://localhost:8000/api/swarm/1/config
# Response should include: {"config": {...}, "config_enabled": true, "effective_config": {...}}
```

#### Toggle config off
```bash
curl -X PUT http://localhost:8000/api/swarm/1 \
  -H "Content-Type: application/json" \
  -d '{"config_enabled": false}'
```

#### Verify config is disabled
```bash
curl http://localhost:8000/api/swarm/1/config
# config_enabled should be false
# effective_config should show default values
# config should still show the saved custom values
```

#### List bots (should include config_enabled)
```bash
curl http://localhost:8000/api/swarm
# Each bot should have config_enabled field
```

### 3. UI Testing

1. Open the dashboard at http://localhost:8000
2. Navigate to a bot's Config tab
3. Verify the "Custom Config" toggle appears at the top
4. Toggle it off - you should see:
   - Toggle changes to "Using default configuration"
   - Yellow warning message appears
   - Config values still display the saved profile values
5. Start the bot and verify it uses default config values
6. Toggle config back on
7. Verify the bot now uses the custom config

### 4. Bot Runtime Testing

1. Start a bot with custom config enabled
2. Check logs to verify it uses custom parameters
3. Toggle config off while bot is running
4. On next signal evaluation, bot should use default config
5. Verify in trade logs that default parameters were used

## Programmatic Testing

### Python Test Script
```python
import requests

BASE = "http://localhost:8000/api/swarm"

# Get bot list
bots = requests.get(BASE).json()
print(f"Bots: {bots}")

# Get bot 1 config
config = requests.get(f"{BASE}/1/config").json()
print(f"Config enabled: {config['config_enabled']}")

# Disable config
resp = requests.put(f"{BASE}/1", json={"config_enabled": False})
print(f"Disabled: {resp.json()}")

# Verify
config = requests.get(f"{BASE}/1/config").json()
print(f"Config enabled after disable: {config['config_enabled']}")
print(f"Config matches effective_config: {config['config'] == config['effective_config']}")

# Re-enable config
resp = requests.put(f"{BASE}/1", json={"config_enabled": True})
print(f"Re-enabled: {resp.json()}")
```

## Key Behaviors to Verify

1. **Config persistence**: Saved config values are preserved when toggling off
2. **Default values**: When disabled, bot uses `BotConfig()` defaults
3. **Hot reload**: Toggle works without restarting the bot
4. **UI sync**: Toggle state reflects in UI immediately
5. **API consistency**: All endpoints return correct `config_enabled` state
