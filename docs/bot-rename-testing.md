# Bot Rename Feature Testing Plan

## Overview
This document outlines testing procedures for the bot rename functionality added to both the Swarm view (BotCard) and Dashboard view (BotDetailView).

## Feature Summary
- Users can rename bots from the Swarm menu (bot cards)
- Users can rename bots from the Dashboard menu (bot detail view)
- Changes persist to the database via `PUT /api/swarm/{bot_id}`

---

## Programmatic Testing

### Backend API Test
The existing endpoint `PUT /api/swarm/{bot_id}` already supports name updates.

```bash
# Test the rename API directly
curl -X PUT http://localhost:8000/api/swarm/1 \
  -H "Content-Type: application/json" \
  -d '{"name": "Test Bot Renamed"}'
```

### Frontend Component Tests (if test infrastructure exists)
1. **BotCard Component**
   - Clicking edit icon shows input field
   - Enter key saves the name
   - Escape key cancels editing
   - Blur saves the name
   - Empty name is rejected (reverts to original)

2. **BotDetailView Component**
   - Clicking edit icon shows input field
   - Enter key saves the name
   - Escape key cancels editing
   - Blur saves the name
   - Empty name is rejected

---

## Manual Testing Checklist

### Swarm View (BotCard)

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Start the app: `npm run dev` | App loads with Swarm view visible |
| 2 | Hover over a bot card | Pencil icon appears next to chevron |
| 3 | Click the pencil icon | Input field replaces bot name, focused |
| 4 | Type a new name and press Enter | Name saves, input disappears, new name visible |
| 5 | Refresh the page | New name persists |
| 6 | Click pencil icon, press Escape | Input disappears, name unchanged |
| 7 | Click pencil icon, clear name, press Enter | Name reverts to original (empty not allowed) |
| 8 | Click pencil icon, type same name, blur | Input disappears, name unchanged |

### Dashboard View (BotDetailView)

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click a bot card to open detail view | Bot detail view opens with bot name in header |
| 2 | Click the pencil icon next to name | Input field replaces name, focused |
| 3 | Type a new name and press Enter | Name saves, input disappears |
| 4 | Navigate back to Swarm view | New name visible in bot card |
| 5 | Return to bot detail view | New name persists in header |
| 6 | Click pencil icon, press Escape | Input disappears, name unchanged |
| 7 | Click pencil icon, clear name, blur | Name reverts to original |

### Edge Cases

| Case | Test | Expected Behavior |
|------|------|-------------------|
| Long name | Enter a very long name (50+ chars) | Name should truncate with ellipsis in card view |
| Special characters | Enter name with emojis, unicode | Should save and display correctly |
| Whitespace | Enter name with leading/trailing spaces | Should trim and save |
| Concurrent edits | Open same bot in two tabs, rename in each | Last edit wins (no conflict detection) |

---

## Files Modified

1. `frontend/src/components/BotCard.jsx`
   - Added `Pencil` icon import
   - Added `isEditing`, `editName` state
   - Added `handleEditName`, `handleSaveName`, `handleNameKeyDown` handlers
   - Added inline input for editing

2. `frontend/src/components/BotDetailView.jsx`
   - Added `Pencil` icon import
   - Added `isEditingName`, `editName` state
   - Added `handleEditName`, `handleSaveName`, `handleNameKeyDown` handlers
   - Added inline input for editing in header

---

## API Reference

### Update Bot Name
```
PUT /api/swarm/{bot_id}
Content-Type: application/json

{
  "name": "New Bot Name"
}
```

Response: Updated `BotRecord` object
