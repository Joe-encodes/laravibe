# AI Redesign & Architecture Rebuild Specs

This document provides complete context for the AI vibecoding tool that will be handling the frontend modular redesign and backend updates. 

## 1. Project Goal & Requirements

The goal is to rebuild the vanilla HTML/JS frontend into an "amazing modular frontend", introduce Supabase authentication, enhance the history functionality, and provide an Admin control feature for model training based on user data.

**Key Objectives for the Vibecoding AI:**
- **Frontend Redesign**: Move from vanilla HTML/JS/CSS to a modern web app architecture (e.g., React + Vite or Next.js or a robust JS setup) focusing on ultra-premium design aesthetics (vibrant colors, glassmorphism, micro-animations).
- **Authentication**: Implement Supabase Basic Auth.
- **Enhanced History**: Properly link submissions to the logged-in user to store and display private history.
- **Admin Control Panel**: Build functionality allowing an Admin to view an aggregation of all platform data (anonymized/summarized) for model retraining, while keeping the original user's PII private.

---

## 2. Current Backend API & Architecture

The backend is built with **FastAPI** + **SQLite (sqlalchemy + aiosqlite)**. It manages long-running Docker sandbox executions to repair PHP code.

### 2.1 Core Database Schemas  (`api/models.py`)

**Submission Table:**
A Submission represents a full repair flow requested by a user.
- `id` (String UUID, pk)
- `created_at` (DateTime)
- `original_code` (Text)
- `status` (String: pending | running | success | failed)
- `total_iterations` (Integer)
- `final_code` (Text, nullable)
- `error_summary` (Text, nullable)

*→ **Migration Note**: A `user_id` column needs to be added here to link the submission to a Supabase auth identity. Additionally, we need an admin flag or role somewhere to gate the admin logic.*

**Iteration Table:**
A Submission has up to 7 Iterations.
- `id` (String UUID)
- `submission_id` (ForeignKey linking to submissions)
- `iteration_num` (Integer)
- `code_input` (Text)
- `execution_output` (Text)
- `error_logs` (Text)
- `boost_context` (Text)
- `ai_prompt` & `ai_response` (Text)
- `patch_applied` & `pest_test_code` & `pest_test_result` (Text)
- `mutation_score` (Float)
- `status` (String)
- `duration_ms` (Integer)

### 2.2 Endpoints in Use (`api/routers/`)

The Frontend currently talks directly to these API endpoints via `fetch`:

1. **Submit Repair**
   - `POST /api/repair`
   - Payload schema: `{ "code": "string", "max_iterations": 7 }`
   - Response: `202 Accepted` with payload `{ "submission_id": "string", "status": "pending", "message": "..." }`
   - *Logic: validates code size, inserts standard Submission row, spawns a lightning-fast Cerebras background task.*

2. **Stream Live Progress (SSE)**
   - `GET /api/repair/{submission_id}/stream`
   - Return type: `text/event-stream` stream
   - Frontend implementation: The FE executes `const eventSource = new EventSource(...)` and listens for JSON payloads emitted on `data:`. The payload matches the `Iteration` schema above.

3. **Get Full Submission History**
   - `GET /api/repair/{submission_id}`
   - Response Payload: The full `Submission` object including an array of `iterations`.

4. **Get Recent Global History**
   - `GET /api/history?limit=20`
   - Response Payload: An array of the 20 most recent Submissions.
   - *→ **Migration Note**: This needs to be updated to `GET /api/history/me` verifying the Supabase JWT token and filtering by `user_id`.*

5. **Batch Evaluations**
   - `POST /api/evaluate`
   - Parses `batch_manifest.yaml` and maps high-speed repairs over the local `dataset/` directory.

---

## 3. Current Frontend Setup & Scaffold (`laravibe-fe/` directory)

We have cloned an amazing modular React+Vite frontend scaffold located in the `laravibe-fe/` directory. This replaces the old vanilla HTML/JS setup.
The scaffold is incredibly well-designed with Tailwind, motion/react, and sleek UI components (`AnalyzerView`, `RepairView`, `HistoryView`, etc.). However, it currently relies on mocked data (`src/constants.ts`).

**Your job as the Vibecoding Tool is to connect this scaffold to the live FastAPI backend.**

---

## 4. Architectural Steps for the AI Vibecoding Tool

To fulfill the integration and requirements, follow this sequence:

### **Step 1: Backend Auth Upgrade**
- Integrate python Supabase client or simply a JWT middleware in FastAPI.
- Update `api/models.py` by adding a `user_id` to the `Submission` table.
- Modify `POST /api/repair` to save `user_id` if present in the auth token.
- Secure `/api/history` to only return the requesting user's submissions.

### **Step 2: Admin Dashboard API Route**
- Add `api/routers/admin.py`.
- Create a `GET /api/admin/training-dataset` route. Ensure it verifies an admin role (via Supabase token or admin array).
- This route should query the DB to aggregate `original_code`, `error_logs`, and `final_code` while dropping any user/UUID links to maintain privacy.

### **Step 3: Hooking up the `laravibe-fe` Scaffold**
- Open `laravibe-fe/src/components/AnalyzerView.tsx`. Replace the dummy action with a `fetch("/api/repair", { ... })` call to submit the broken code. Store the returned `submission_id` in `App.tsx` state to pass to the next view.
- Open `laravibe-fe/src/components/RepairView.tsx`. Strip out `MOCK_LOGS` and `MOCK_INSIGHT`. Instantiate an `EventSource('/api/repair/${submission_id}/stream')` inside a `useEffect` to listen to the live backend events, parsing JSON and animating the results live.
- Open `laravibe-fe/vite.config.ts` and add a proxy for `/api` to point to `http://127.0.0.1:8000` to prevent any CORS issues during dev.
- Update `HistoryView.tsx` to `fetch('/api/history')` instead of `MOCK_HISTORY`.

### **Step 4: History & Admin Dashboards UI (Supabase)**
- Install `@supabase/supabase-js` inside `laravibe-fe` and wrap the app in an Auth Provider.
- Create an `<AdminRoute>` pointing to the training datasets (`/api/admin/training-dataset`), displaying summaries visually using the awesome bento boxes style from the scaffold. 
