"""Interactive Egypt map for the dashboard (governorate-level bubbles).

Uses a scatter_mapbox bubble map (open-street-map tiles rendered client-side),
so it needs no bundled GeoJSON. Bubble size = volume, colour = a chosen metric.
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px

# Approx governorate centroids (lat, lon) for the network's catchment.
GOV_COORDS = {
    "Cairo": (30.0444, 31.2357),
    "Giza": (29.9870, 31.2118),
    "Alexandria": (31.2001, 29.9187),
    "Menoufia": (30.5972, 30.9876),
    "Sharqia": (30.7327, 31.7195),
    "Dakahlia": (31.0409, 31.3785),
    "Qalyubia": (30.4290, 31.2100),
    "Gharbia": (30.8760, 31.0335),
    "Beheira": (30.8480, 30.3436),
    "Aswan": (24.0889, 32.8998),
    "Luxor": (25.6872, 32.6396),
    "Suez": (29.9668, 32.5498),
    "Fayoum": (29.3084, 30.8428),
    "Minya": (28.1099, 30.7503),
    "Beni Suef": (29.0661, 31.0994),
    "Asyut": (27.1809, 31.1837),
    "Sohag": (26.5591, 31.6957),
}


def governorate_map(df: pd.DataFrame, gov_col: str, value_col: str,
                    color_col: str | None = None, title: str = ""):
    """df must be aggregated to one row per governorate."""
    d = df.copy()
    d["lat"] = d[gov_col].map(lambda g: GOV_COORDS.get(g, (26.8, 30.8))[0])
    d["lon"] = d[gov_col].map(lambda g: GOV_COORDS.get(g, (26.8, 30.8))[1])
    fig = px.scatter_mapbox(
        d, lat="lat", lon="lon", size=value_col,
        color=color_col or value_col,
        hover_name=gov_col,
        hover_data={c: True for c in [value_col] + ([color_col] if color_col else [])
                    if c in d.columns} | {"lat": False, "lon": False},
        color_continuous_scale="YlOrRd", size_max=45, zoom=4.6,
        center={"lat": 27.5, "lon": 30.5}, height=560, title=title,
    )
    fig.update_layout(mapbox_style="open-street-map",
                      margin={"r": 0, "t": 40, "l": 0, "b": 0})
    return fig
