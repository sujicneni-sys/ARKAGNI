import os
import pandas as pd
import numpy as np

def load_and_process_data(file_path):
    """
    Loads and cleans satellite fire data CSV/JSON from disk or uploaded file buffer.
    """
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return pd.DataFrame()
        
    try:
        if file_path.endswith('.json'):
            df = pd.read_json(file_path)
        else:
            df = pd.read_csv(file_path)
    except Exception as e:
        print(f"Error loading {file_path}: {e}")
        return pd.DataFrame()

    if df.empty:
        return df

    # Standardize column names
    df.columns = [str(c).lower().strip() for c in df.columns]
    
    # Identify standard coordinate and metric columns dynamically
    lat_col = next((c for c in df.columns if 'lat' in c), 'latitude')
    lon_col = next((c for c in df.columns if 'lon' in c), 'longitude')
    frp_col = next((c for c in df.columns if 'frp' in c), 'frp')
    
    if lat_col != 'latitude' and lat_col in df.columns:
        df['latitude'] = df[lat_col]
    if lon_col != 'longitude' and lon_col in df.columns:
        df['longitude'] = df[lon_col]
    if frp_col != 'frp' and frp_col in df.columns:
        df['frp'] = df[frp_col]
        
    # Filter valid coordinates
    df = df.dropna(subset=['latitude', 'longitude'])
    df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
    df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
    df = df.dropna(subset=['latitude', 'longitude'])
    
    if 'frp' in df.columns:
        df['frp'] = pd.to_numeric(df['frp'], errors='coerce').fillna(0.0)
    else:
        df['frp'] = 0.0
        
    # Convert acq_date to datetime if exists
    if 'acq_date' in df.columns:
        df['acq_date'] = pd.to_datetime(df['acq_date'])
        
    return df

def get_dataset_metrics(df):
    """
    Calculates primary statistical metrics for the telemetry dashboard.
    """
    if df.empty:
        return {"total_detections": 0, "avg_frp": 0.0, "max_frp": 0.0}
        
    return {
        "total_detections": int(len(df)),
        "avg_frp": float(df['frp'].mean()),
        "max_frp": float(df['frp'].max())
    }
