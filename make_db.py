import sqlite3
import pandas as pd
conn = sqlite3.connect("data.db")
for f, t in [("MODIS_SP_cleaned.csv", "modis_fires"), ("VIIRS_NOAA20_SP_cleaned.csv", "viirs_noaa20"), ("VIIRS_SNPP_SP_cleaned.csv", "viirs_snpp")]:
    df = pd.read_csv(f, nrows=10000, dtype=str)
    df.to_sql(t, conn, if_exists="replace", index=False)
conn.close()
print("Database created successfully!")