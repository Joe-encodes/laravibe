# LaraVibe — AI-Enhanced Research & Repair Platform

**Author:** Adamu Joseph Obinna | **Version:** 1.0 — BSc Thesis 2026

LaraVibe is a high-fidelity research observability platform designed to automatically fix broken AI-generated PHP/Laravel code using an isolated Docker sandbox and LLM-driven inference.

---

## ⚡ Quick Start

### 1. Prerequisites
- **Python 3.12+** and **Node.js 20+**
- **Docker Desktop** (with WSL2 integration enabled in settings)
- At least one AI API key (e.g., [Google GenAI Free Tier](https://aistudio.google.com/app/apikey))

### 2. Setup (WSL Ubuntu)
```bash
# Clone the repository
# Copy the environment file and add your AI key
cp .env.example .env

# Run the automated setup script
# This creates the venv, installs deps, and builds the Docker sandbox (~5 mins)
bash start.sh
```

### 3. Launch Frontend
Open a new terminal session for the React app:
```bash
cd laravibe-fe
npm install
npm run dev
```

You can now access the full application layout in your browser, running against the local FastAPI coordinator (`http://localhost:8000`).

---

## 🛠️ Core Technology Stack

| Component | Technology | Role |
| :--- | :--- | :--- |
| **Frontend** | React 19, Tailwind CSS 4, React Router 7 | High-density observability HUD and streaming SSE interface. |
| **Backend** | FastAPI (Python 3.12), SQLite (async) | Service coordinator, metrics tracking, and AI provider routing. |
| **Sandbox** | Docker Engine, PHP 8.3, Laravel 12, Pest 3 | Isolated (`network=none`), safe execution zone for broken code. |
| **AI Models** | Gemini, Groq, DeepSeek, Claude | Performs deterministic inference for patch and test generation. |

---

## 📚 Technical Documentation

For deep-dives into the architecture, design systems, and thesis methodology, consult the authoritative manuals:

1. **[MANUAL.md](MANUAL.md)**
   The Master Technical Manual. Detailed breakdown of DevOps container orchestration, the complex Iterative Repair Loop, and database schemas.
2. **[BACKEND_SPEC.md](BACKEND_SPEC.md)**
   Backend technical ground truth. Includes API routing, AI Fallback mechanisms, and Empirical Validation configuration (Batch testing/Ablations).
3. **[BE_CHECKLIST.md](BE_CHECKLIST.md)**
   Thesis tracking matrix mapping features directly to thesis claims and literature review.

*Built for research. Driven by precision.*
