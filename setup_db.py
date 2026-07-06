import sqlite3
import pandas as pd
from pathlib import Path

# Paths
base_dir = Path(__file__).resolve().parent
csv_path = base_dir / "docs" / "nvidia_gpu_sales_synthetic_2026.csv"
db_path = base_dir / "data" / "live_data.db"

def main():
    print(f"Loading {csv_path.name} into {db_path}...")
    df = pd.read_csv(csv_path)
    
    # Standardize column names to be SQL friendly
    df.columns = [c.lower().replace(" ", "_").replace("-", "_") for c in df.columns]
    
    with sqlite3.connect(db_path) as conn:
        df.to_sql("gpu_sales", conn, if_exists="replace", index=False)
        
    print(f"Loaded {len(df)} rows into 'gpu_sales' table.")

if __name__ == "__main__":
    main()
