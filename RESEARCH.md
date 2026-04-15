# LaraVibe: Research & Experimentation Guide

This guide describes how to use the **Laravel AI Repair Platform** to generate empirical data for the bachelor thesis, specifically focusing on **Ablation Studies** and **Recoil Resistance (Mutation Testing)**.

## 🧪 Experiment Workflow
The core research methodology involves running the same set of broken code cases under different "Ablation" configurations to prove the effectiveness of the platform's features.

### 1. The Dataset
All test cases are located in the `dataset/` directory. Each case (e.g., `case-001`) contains a `code.php` file with a specific architectural or logical defect.
- **Adding Cases**: Create a new folder in `dataset/`, add `code.php`, and register it in `batch_manifest.yaml`.

### 2. Ablation Configuration
Edit `batch_manifest.yaml` to toggle the following research variables:
- `use_boost_context`: Enables/Disables the Laravel-specific schema & dependency injection awareness. Measures the impact of supplying context vs static code analysis.
- `use_mutation_gate`: Enables/Disables the requirement for repaired code to survive mutation testing. Measures the impact of enforcing a robustness standard.

### 3. Running Batch Evaluations
You can trigger experiments via the **Research Hub** in the UI (Admin Dashboard) or via the CLI:
```powershell
# Run full suite defined in batch_manifest.yaml
curl -X POST http://localhost:8000/api/evaluate
```

## 📊 Interpreting Metrics
The platform tracks three primary scientific metrics:

1.  **Success Rate (%)**: Percentage of cases that passed the linting and functional test suites.
2.  **Logic Evolution (Iterations)**: The number of loops required to reach a stable state. Fewer iterations indicate higher AI "Efficiency."
3.  **Recoil Resistance (Mutation Score)**: The ultimate measure of code robustness. A high score means the AI didn't just "fix the bug," but built a resilient solution that makes the application testable and resistant to algorithmic regressions.

## 📋 Scientific Exports
Every batch run generates a persistent record in the database and an exported CSV (`tests/integration/results/batch_report.csv`).
Each row is self-documenting with:
- `ai_model`: The model used (e.g., Qwen, Claude, Gemini).
- `use_boost` / `use_mutation`: The ablation state.
- `timestamp / experiment_id`: Unique identifiers for the cross-referencing thesis runs.

---
**Happy Researching!** 🎓
