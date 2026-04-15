# LaraVibe Frontend: Technical Specification & Design System
## Main Development Source of Truth

This document defines the current state and architectural standards for the LaraVibe platform, serving as the ground truth for future development and AI-driven maintenance.

---

## 1. Project Vision
LaraVibe is a high-end research observability platform designed for automated code repair and ablation studies. It prioritizes a "Research Hub" aesthetic with high-fidelity feedback loops, live execution streaming, and scientific metadata aggregation.

---

## 2. Frontend Architecture (`laravibe-fe/`)

### 2.1 Technology Stack
- **Core Framework**: [React 19](https://react.dev/) with TypeScript.
- **Build Tool**: [Vite 6](https://vitejs.dev/) (optimized for performance).
- **Styling**: [Tailwind CSS 4.0](https://tailwindcss.com/) using the `@tailwindcss/vite` plugin.
- **Routing**: [React Router 7](https://reactrouter.com/) (URL-driven navigation).
- **Animations**: [Framer Motion (`motion/react`)](https://www.framer.com/motion/) for micro-animations and state transitions.
- **Icons**: [Lucide React](https://lucide.dev/).

### 2.2 Design System
The application uses a custom-tailored "Glass-Industrial" design system defined in `src/index.css`.
- **Color Palette**: 
    - `Primary`: Indigo/Violet-based (`#6366F1`) for core actions.
    - `Secondary`: Emerald/Teal (`#10B981`) for success and optimization states.
    - `Surface`: Deep Zinc/Neutral dark themes with transparent container layers.
- **UI Tokens**:
    - `surface-container-low/high/lowest`: Hierarchical background layers.
    - `on-surface / on-surface-variant`: Tiered typography colors.
    - `mono`: Extensive use of monospace fonts for data-heavy views.
- **Interactive Elements**: Glassmorphism effects, pulsing status indicators, and hover-triggered HUD accents.

### 2.3 Application Routing
| Path | Component | Description |
| :--- | :--- | :--- |
| `/` | `AnalyzerView` | Entry point for code submission and ablation configuration. |
| `/repair/:id` | `RepairView` | Live SSE streaming dashboard for the active repair cycle. |
| `/history` | `HistoryView` | Historical trace of all submission records. |
| `/iteration/:id` | `IterationView` | Deep-dive into specific iteration results and diffs. |
| `/tests/:id` | `TestsView` | Detailed Pest test execution results. |
| `/admin` | `AdminDashboardView` | Combined interface for Training Vaults and Batch Evaluations. |

---

## 3. Data Flow & Backend Integration

### 3.1 REST API Communication
The frontend communicates with a FastAPI backend via a Vite proxy (`/api` -> `http://127.0.0.1:8000`).
- **Submission**: `POST /api/repair` with `code`, `max_iterations`, and ablation toggles (`use_boost`, `use_mutation_gate`).
- **Research Stats**: `GET /api/stats` for global performance metrics.
- **Batching**: `POST /api/evaluate` to trigger multi-case research runs.

### 3.2 Live Streaming (SSE)
The `RepairView` utilizes **Server-Sent Events (SSE)** via `EventSource('/api/repair/${id}/stream')` to visualize the backend workflow in real-time.
- **Events Tracked**: `log_line`, `iteration_start`, `boost_queried`, `pest_result`, `mutation_result`, `ai_thinking`, `patch_applied`, `complete`.
- **State Engine**: The frontend maps these events to a linear stage progression: `SPINNING` → `BOOSTING` → `THINKING` → `PATCHING` → `TESTING` → `MUTATING` → `COMPLETE`.

### 3.3 Admin & Research (Evaluation Hub)
- **Training Vault**: Aggregates successful repair pairs (broken input vs. optimized patch) for model fine-tuning.
- **Evaluation Hub**: Tracks batch experiments, providing "Global Accuracy" and "Recoil Resistance" (mutation scores) metrics.

---

## 4. Current State & Known Implementation Details

- **Mock Data Status**: Substantially purged. The application now prioritizes live API data. `src/constants.ts` is reserved for default editor content.
- **State Management**: Primarily relies on local `useState` and `useEffect` with URL-based synchronization via `react-router-dom`.
- **Theme Support**: Hybrid theme engine supporting `dark` (default) and `light` modes via `App.tsx`.
- **Keyboard Optimization**: Global shortcut listener ('?') for command discovery.

---

## 5. Future Roadmap

### Phase 1: Authentication (Pending)
- Implementation of **Supabase Basic Auth**.
- Requirement: Add `AuthContext` to `laravibe-fe` and protect routes.
- Requirement: Pass JWT tokens in `Authorization` headers for all API requests.

### Phase 2: Enhanced Visualization
- Integration of a dedicated Diff Viewer for `IterationView`.
- Real-time graphing for Mutation Score trends during research runs.

### Phase 3: Model Control
- Admin interface for adjusting AI prompt templates and model parameters directly from the Research Hub.
