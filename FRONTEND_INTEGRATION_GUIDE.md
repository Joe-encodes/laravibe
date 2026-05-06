# LaraVibe Frontend Integration & Design Guide

This guide defines how the LaraVibe React frontend consumes the hardened FastAPI backend. It covers the communication protocols, state machine transitions, and UI mapping for the "Glass-Industrial" dashboard.

---

## 1. Communication Protocol

### A. Authentication
All API requests must include the master token in the header:
```http
Authorization: Bearer <REPAIR_TOKEN>
```

### B. Repair Workflow
1. **Submission**: `POST /api/repair`
   - Returns `202 Accepted` + `submission_id`.
   - The repair runs in the background.
2. **Streaming**: `GET /api/repair/{submission_id}/stream`
   - Connect via **Server-Sent Events (SSE)**.
   - Replays history on reconnect (native persistence).
3. **Polling (Optional)**: `GET /api/repair/{submission_id}`
   - Fetch the full nested JSON object (useful for deep-dive history views).

---

## 2. SSE Event Specification

The frontend must handle the following event types emitted by the backend:

| Event Type | UI Impact | Payload Highlights |
|---|---|---|
| `submission_start` | Initialize HUD | `submission_id`, `original_code` |
| `iteration_start` | Pulsing iteration counter | `num` (1-index) |
| `log_line` | Append to terminal | `message` (Look for `🔄` for AI fallbacks) |
| `boost_queried` | Highlight context panel | `context_text` (Laravel schema/docs) |
| `ai_thinking` | Pulse "Thinking" indicator | `role` (Planning/Executing/Reviewing) |
| `pest_result` | Green/Red badge on Tests | `success` (bool), `output` (full Pest stdout) |
| `mutation_result`| Progress bar / Score | `score` (0-100), `success` (bool) |
| `patch_applied` | Flash green on code lines | `patches` (list of actions/files) |
| `error` | Red alert banner | `message` (Fatal system error) |
| `complete` | Reveal "Download" / "Apply" | `status` (success/failed), `final_code` |

---

## 3. The 3-Panel HUD Mapping

To maintain the "Glass-Industrial" aesthetic, map backend states to these panels:

### Panel 1: Context & Discovery (Left)
- **Source**: `boost_queried` events.
- **Visuals**: Tree view of detected Models/Migrations.
- **Logic**: When a new `boost_context` arrives, highlight the affected DB tables.

### Panel 2: The Repair Terminal (Center)
- **Source**: `log_line` and `ai_thinking` events.
- **Visuals**: Monospace log scroller (JetBrains Mono).
- **Behavior**: 
  - Auto-scroll to bottom.
  - Highlight `🔄` lines in Amber (Amber-400) to show the system is self-healing from rate limits.
  - Dim "Thinking" roles as they complete.

### Panel 3: Code & Diffs (Right)
- **Source**: `patch_applied` and `complete` events.
- **Visuals**: CodeMirror side-by-side diff.
- **Logic**: Use the `patches` array from `patch_applied` to show exactly which file changed in real-time.

---

## 4. State Machine: Handling Success & Failure

The UI should drive its primary "Success Gate" based on the `complete` event:

- **SUCCESS**: `status === "success"`
  - Logic: Iteration loop hit the `MUTATION_SCORE_THRESHOLD` (80%) OR the functional baseline passed.
  - UI: Large green "Repair Verified" glow.
- **FAILURE**: `status === "failed"`
  - Logic: All iterations exhausted OR `AIServiceError` (all fallback providers dead).
  - UI: Red "Repair Exhausted" banner with "Retry with different model" option.

---

## 5. Resilience: The "Retry" Logic
If the FE sees a `log_line` containing `Rate-limited by...`, it should **NOT** show an error to the user.
- **Action**: Show a subtle "Pivoting Providers..." toast.
- **Why**: The backend is already handling the sleep and fallback; the UI just needs to remain alive.

---

## 6. CSS Tokens (Glass-Industrial)
- **Primary Machined**: `slate-950`
- **Glass Panel**: `bg-white/5 backdrop-blur-xl border border-white/10`
- **Success Glow**: `shadow-[0_0_30px_rgba(34,197,94,0.2)]`
- **Thinking Pulse**: `animate-pulse text-indigo-400`
