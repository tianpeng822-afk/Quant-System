import akshare as ak
import json
import os
from pathlib import Path

def update_fund_names():
    print("Fetching fund names from AkShare...")
    try:
        df = ak.fund_name_em()
        if df is None or df.empty:
            print("Failed to fetch data (empty dataframe).")
            return
            
        name_map = dict(zip(df["基金代码"], df["基金简称"]))
        
        data_dir = Path(__file__).resolve().parent.parent / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = data_dir / "fund_names.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(name_map, f, ensure_ascii=False, indent=2)
            
        print(f"Successfully saved {len(name_map)} fund names to {file_path}")
    except Exception as e:
        print(f"Error fetching fund names: {e}")

if __name__ == "__main__":
    update_fund_names()
