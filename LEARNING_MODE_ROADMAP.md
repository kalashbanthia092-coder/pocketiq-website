# PocketIQ - Roadmap & Notes

## Done
### Learning Mode
- [x] Full redesign: two states (setup + workspace), 3-column workspace
- [x] Working XP bar (100 XP/step, 200 XP/level, 7 level titles, animated fill, level-up toasts)
- [x] Article opens beside the roadmap (no scrolling to find it)
- [x] Streaks + 4 achievement badges
- [x] Learning assistant decoupled from Decision bot (`/ask_learning`, own persona + own `learning_chat_history` session key)

### Site-wide
- [x] Single design system in `static/ui.css` (tokens, banner, buttons, tabs, cards, footer, all modes, About, Home)
- [x] Shared `templates/partials/header.html` + `footer.html` on every page
- [x] New SVG logo at `static/logo.svg`
- [x] Header nav + segmented mode tabs with per-page active states
- [x] Decision Mode rebuilt (chat card, starter chips, sidebar, reset button, auto-highlighted verdicts)
- [x] Compare Mode rebuilt (product cards, VS + swap, presets, ratio hero, price bars, gap callout)
- [x] About page rebuilt
- [x] `/reset_chat` endpoint (scope: decision | learning | all)
- [x] USD->INR rate corrected to 95 (single `USD_TO_INR` constant)

### Baseline context: two interchangeable methods (Aug 11)
- [x] Setup card now has a toggle: **Write it yourself** (original textarea) or **Quick questions** (rapid-fire)
- [x] Rapid-fire quiz: MCQ, multi-select, 1-5 scale, and short-text question types
- [x] **Variable length via branching.** Each question has an optional `when` predicate, so the run adapts: answering "never save" inserts a blocker question (8 -> 9 questions); answering "already invest" inserts an instruments question instead. Verified both paths.
- [x] **Sufficiency gate.** `REQUIRED` = stage, income, saving, investing, confidence, focus. The build button and review panel stay hidden until all are answered; status shows "N more to go" then "MoBo has enough to build". Remaining questions become optional extras.
- [x] Single-choice and scale answers auto-advance (~180ms) so it actually feels rapid; multi-select and text wait for Next.
- [x] **Both methods converge.** The quiz synthesizes answers into the same first-person paragraph the textarea would produce, then calls the shared `buildRoadmap()`. Switching methods (or "Edit as text") carries answers into the textarea, so nothing is lost either direction.

### Cleanup (Aug 11)
- [x] Removed dead files: `compare.html`, `start.html`, `goals.html` (+ their routes), `chatbot.py`, `static/layout.css`, `static/pocketiq.png`, `delta-ai.zip`, `.DS_Store`. Saved ~2.9 MB. All live routes 200, removed routes 404, no dangling references.
- [x] Footer now scales: content tracks the app's 1460px envelope with percentage side padding, columns spread via flex (was a narrow ~1200px clump).
- [x] Em dashes removed from all templates/CSS/backend copy. Model prompts now instruct MoBo to avoid em dashes in generated articles/chat.

### Production hardening (Aug 11)
- [x] **Server-side sessions.** `Flask-Session` was in requirements but never initialized, so chat history lived in a cookie capped at ~4093 bytes. Worst realistic case measured 3,772 bytes (only ~8% headroom), and it tips over with a longer user background or a fuller MoBo reply; overflow silently drops the cookie and the conversation loses all context. Now `SESSION_TYPE="filesystem"`. Verified: 81,154 chars of history round-trips intact on a constant 71-byte cookie.
- [x] **Absolute paths.** `BASE_DIR` added; `SESSION_FILE_DIR` and `load_dotenv()` no longer depend on `os.getcwd()`, which is not the project folder under WSGI. Verified by importing the app from `/tmp`.
- [x] Hardened cookies: HttpOnly, SameSite=Lax, and Secure when `FLASK_ENV=production`.
- [x] `flask_session/` gitignored and untracked (6 stale June session files were being committed).
- [x] Added `.env.example`, `pythonanywhere_wsgi.py`, `DEPLOYING.md`.

## Up next (pick an order)
See the numbered suggestion list kept in chat. Rough grouping:

### Learning depth
- [ ] Interactive quizzes gating step progression (XP/badge scaffolding already in place; a passed quiz replaces "Mark complete")
- [ ] Better article generation (richer formatting, tighter personalisation)
- [ ] Inline glossary (tap a term for a definition)
- [ ] "Explain it differently" (regenerate simpler/advanced)
- [ ] Embedded mini-calculators in relevant lessons

### Persistence & accounts
- [ ] Persist progress server-side instead of `localStorage` (currently per-browser, lost if storage clears)
- [ ] Optional lightweight accounts so progress follows the user across devices

### Cross-mode
- [ ] "Compare" and "Decision" hand-offs (e.g. a Compare result offers "ask the decision coach about this")
- [ ] Save/history for past decisions and comparisons

### Polish
- [ ] Loading skeletons instead of spinners
- [ ] Empty-state illustrations
- [ ] Downloadable completion certificate
- [ ] Bookmark/revisit favourite lessons

## Known gotchas (don't re-break these)
- In `ui.css`, `.pq-section` / `.pq-page` set ONLY block-axis padding. The `padding` shorthand there overrides `.pq-wrap`'s horizontal padding (same specificity, later rule wins) and content runs edge-to-edge.
- No page uses a bare `<header>` for content; the shared banner partial is the only header. The XP bar is a `<div class="progress-header">` on purpose.
- All layout/visuals live in `static/ui.css`. Keep them out of inline `<style>` blocks.
- Deleting a template will 500 the deployment if a route still renders it. Remove the route in `backend.py` first, then the file. Removing a route is safe only if nothing links to it.
- The two chat histories are separate session keys (`chat_history` = Decision, `learning_chat_history` = Learning tutor). Keep them apart.
- **Never store conversation state in a plain Flask cookie session.** Browsers cap cookies at ~4093 bytes and drop oversized ones *silently*, which reads as "the AI forgot everything" rather than as a storage error. Sessions are filesystem-backed now; keep it that way.
- Anything resolving a path must use `BASE_DIR`, not a relative path or `os.getcwd()`. Under WSGI the working directory is not the project folder.
- **Jinja caches compiled templates when `FLASK_DEBUG` is off.** Editing a template will not show up until you restart the server. Run with `FLASK_DEBUG=true` while developing, or you will test stale markup and think your change did nothing.
- To add a quiz question, append to the `QUIZ` array in `mobo.html`. Add its `id` to `REQUIRED` only if the roadmap genuinely needs it, and add a matching branch in `synthesize()` or the answer will be collected but never reach MoBo.
