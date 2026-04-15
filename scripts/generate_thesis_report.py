import csv
import pathlib

def generate_report():
    on_file = pathlib.Path("tests/integration/results/batch_report_boost_on.csv")
    off_file = pathlib.Path("tests/integration/results/batch_report_boost_off.csv")
    
    if not on_file.exists() or not off_file.exists():
        print("❌ Waiting for one or both batch reports to be generated...")
        return

    def read_csv(p):
        data = {}
        with open(p, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                data[row["case_id"]] = row
        return data

    on_data = read_csv(on_file)
    off_data = read_csv(off_file)
    
    print("# 📊 Thesis Ablation Study: Laravel Boost Effectiveness")
    print("| Case ID | Category | Status (Boost ON) | Status (Boost OFF) | Iterations (ON) | Iterations (OFF) |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- |")
    
    for case_id in sorted(on_data.keys()):
        on = on_data[case_id]
        off = off_data.get(case_id, {"status": "N/A", "iterations": "N/A"})
        
        # Simple category mapping from manifest id prefix if needed, or just case_id
        cat = "Logic"
        
        status_on = "✅ Success" if on["status"] == "success" else "❌ Failed"
        status_off = "✅ Success" if off["status"] == "success" else "❌ Failed"
        
        print(f"| {case_id} | {cat} | {status_on} | {status_off} | {on['iterations']} | {off['iterations']} |")

if __name__ == "__main__":
    generate_report()
