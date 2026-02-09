# Fix: "Copy for AI" Button Not Working

## Problem
The "Copy for AI" button in `SessionsPanel.jsx` and `SwarmView.jsx` used `navigator.clipboard.writeText()` after an async API call. This caused two issues:

1. **Hanging promise**: `navigator.clipboard.writeText()` can hang indefinitely (never resolve or reject) when the document doesn't have focus — e.g. PWA mode, unfocused tab, or browser extensions stealing focus.
2. **Permission revocation**: Browsers revoke clipboard write permission after an async gap between the user gesture and the API call.

Both issues caused the button to either get stuck on "Generating..." forever or silently fail.

## Root Cause (confirmed via Chrome debugging)
- API endpoint `/api/sessions/{id}/export` and `/api/swarm/export-latest-sessions` both return 200 with valid `export_text`
- `navigator.clipboard.writeText()` promise **never settles** when document lacks focus — neither `.then()` nor `.catch()` fires
- This left the component in `loading` state permanently

## Fix
Replaced the async `navigator.clipboard.writeText()` with synchronous `document.execCommand('copy')` via a temporary textarea. This approach:
- Is synchronous — no hanging promises
- Works regardless of document focus state
- Works after async gaps (API calls)
- Returns a boolean indicating success/failure

Applied to both:
- `frontend/src/components/SessionsPanel.jsx` — session detail "Copy for AI" button
- `frontend/src/components/SwarmView.jsx` — swarm overview "Copy Latest Sessions for AI" button

## Files Changed
- `frontend/src/components/SessionsPanel.jsx`
- `frontend/src/components/SwarmView.jsx`

## Testing

### Programmatic
1. Build succeeds: `cd frontend && npx vite build` — no errors
2. API endpoint returns valid data: `curl http://localhost:8000/api/sessions/{id}/export` returns JSON with `export_text`

### Manual
1. Start backend: `cd backend && python3 -m uvicorn main:app`
2. Start frontend: `cd frontend && npm run dev`
3. Open http://localhost:5173 in browser
4. Navigate to a session detail view (History tab → click a session)
5. Click "Copy for AI" button
6. Verify button changes to "Copied!" with green styling
7. Paste into a text editor — should contain the session export text
8. Test in SwarmView — click "Copy Latest Sessions for AI" button
9. Verify same copy behavior works
10. Test on mobile/PWA if possible

### Verified in Chrome (via extension)
- SwarmView "Copy Latest Sessions for AI": `execCommand copy result: true` ✓
- SessionsPanel "Copy for AI" (session #17): `execCommand copy result: true` ✓
- API calls all return 200 with valid export_text ✓
