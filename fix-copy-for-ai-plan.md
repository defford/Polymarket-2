# Fix: "Copy for AI" Button Not Working

## Problem
The "Copy for AI" button in `SessionsPanel.jsx` and `SwarmView.jsx` uses `navigator.clipboard.writeText()` after an async API call. Browsers (especially Safari, Firefox, and mobile browsers) revoke clipboard write permission when there's an async gap between the user gesture (click) and the clipboard API call. The `await get(...)` introduces this gap, causing the clipboard write to silently fail.

## Fix
Added a `copyToClipboard()` helper that:
1. Tries `navigator.clipboard.writeText()` first
2. Falls back to `document.execCommand('copy')` via a temporary textarea if the Clipboard API throws (permission revoked after async gap)

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
4. Navigate to a session detail view (Sessions tab → click a session)
5. Click "Copy for AI" button
6. Verify button changes to "Copied!" with green styling
7. Paste into a text editor — should contain the session export text
8. Test on Safari/mobile if possible (most likely to trigger the fallback path)
9. Test in SwarmView — click "Copy Latest Sessions for AI" button
10. Verify same copy behavior works
