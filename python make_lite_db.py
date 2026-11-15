import sqlite3
import pandas as pd

print("Creating lightweight demo database...")
conn = sqlite3.connect("data.db")

# Load a clean sample (10,000 rows each) from your cleaned CSVs
files_tables = [
    ("MODIS_SP_cleaned.csv", "modis_fires"),
    ("VIIRS_NOAA20_SP_cleaned.csv", "viirs_noaa20"),
    ("VIIRS_SNPP_SP_cleaned.csv", "viirs_snpp"),
]

for csv_file, table_name in files_tables:
  try:
    print(f"Processing {csv_file}...")
    df = pd.read_csv(csv_file, nrows=10000)
    df.to_sql(table_name, conn, if_exists="replace", index=False)
    print(f"-> Added {table_name} to SQLite.")
  except Exception as e:
    print(f"Could not load {csv_file}: {e}")

conn.close()
print("Success! New lightweight data.db created.")