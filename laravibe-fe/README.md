# LaraVibe - Frontend

This is the React-based frontend for the LaraVibe AI Repair Platform, built with Vite and Tailwind CSS.

## Getting Started

### Prerequisites
- Node.js (v18+)
- npm or yarn

### Installation

1. Install dependencies:
   ```bash
   npm install
   ```

2. Configuration:
   The frontend is configured to proxy API requests to the FastAPI backend running at `http://127.0.0.1:8000`. You can adjust this in `vite.config.ts` if needed.

## 🚀 Professional Research Hub
The LaraVibe frontend is a **React + Tailwind** application designed for high-end research observability.

### Key Sections
- **Analyzer**: Live code submission with ablation switches (**Boost** / **Mutation**).
- **History**: Historical trace of all repair iterations.
- **Research Hub** (Admin): Centralized experimentation dashboard for batch runs and scientific metadata aggregation.

### Development
```bash
npm install
npm run dev
```

The frontend uses a Vite proxy (`/api`) to communicate with the FastAPI backend on port 8000. Ensure both services are running for full functionality.

## 📋 Integration
This frontend communicates with the LaraVibe backend to provide AI-driven code analysis and repair recommendations. It specifically supports **Ablation Studies** for automated thesis research.
