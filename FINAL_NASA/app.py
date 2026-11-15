import streamlit as st
import pandas as pd
import plotly.express as px
import os
from processor import load_and_process_data, get_dataset_metrics

# Page Configuration
st.set_page_config(
    page_title="Arkagni",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Header Section
st.title("Arkagni")
st.markdown("---")

# Sidebar Controls
st.sidebar.header("Configuration & Data Sources")
dataset_selection = st.sidebar.selectbox(
    "Active Satellite Dataset",
    ["MODIS", "VIIRS SNPP", "VIIRS NOAA-20", "Trial Evaluation Upload"]
)

data_dir = "./data"
df = pd.DataFrame()

if dataset_selection == "MODIS":
    file_path = os.path.join(data_dir, "MODIS_SP_raw.csv")
    df = load_and_process_data(file_path)
elif dataset_selection == "VIIRS SNPP":
    file_path = os.path.join(data_dir, "VIIRS_SNPP_SP_raw.csv")
    df = load_and_process_data(file_path)
elif dataset_selection == "VIIRS NOAA-20":
    file_path = os.path.join(data_dir, "VIIRS_NOAA20_SP_raw.csv")
    df = load_and_process_data(file_path)
else:
    st.sidebar.markdown("---")
    st.sidebar.subheader("Judge Evaluation File Upload")
    uploaded_file = st.sidebar.file_uploader("Upload CSV or JSON dataset", type=["csv", "json"])
    if uploaded_file is not None:
        temp_path = os.path.join(data_dir, "temp_uploaded_dataset.csv")
        with open(temp_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        df = load_and_process_data(temp_path)

# Main Panel Rendering
if not df.empty:
    metrics = get_dataset_metrics(df)
    
    # Metrics Row
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Fire Detections", f"{metrics['total_detections']:,}")
    with col2:
        st.metric("Mean Fire Radiative Power (MW)", f"{metrics['avg_frp']:.2f}")
    with col3:
        st.metric("Peak Fire Radiative Power (MW)", f"{metrics['max_frp']:.2f}")
        
    st.markdown("---")
    
    # Geospatial Mapping Section
    st.subheader("Global Geospatial Distribution")
    st.markdown("Coordinates rendered via Natural Earth projection grid.")
    
    map_df = df.sample(n=min(len(df), 25000), random_state=42)
    
    # Strictly using scatter_geo to avoid any mapbox token dependency or attribute errors
    fig = px.scatter_geo(
        map_df,
        lat="latitude",
        lon="longitude",
        color="frp" if 'frp' in map_df.columns else None,
        size="frp" if 'frp' in map_df.columns else None,
        projection="natural earth",
        title="Satellite Fire Radiative Power Telemetry"
    )
    fig.update_layout(
        margin={"r":0, "t":40, "l":0, "b":0},
        geo=dict(showland=True, landcolor="rgb(240, 240, 240)", subunitcolor="rgb(210, 210, 210)")
    )
    st.plotly_chart(fig, use_container_width=True)
    
    st.markdown("---")
    
    # Data Inspection Table
    st.subheader("Telemetry Data Inspection")
    st.dataframe(df.head(200), use_container_width=True)
    
else:
    st.info("Awaiting valid telemetry dataset. Select an institutional source from the sidebar or upload an evaluation file.")