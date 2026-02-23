"""
Example script to test NASA FIRMS API connection (no database required)
"""

import sys
sys.path.insert(0, '.')

# Import only the client, not the ingester
import requests
import pandas as pd
from io import StringIO

# Your NASA FIRMS API key
MAP_KEY = "9ae1e0c7f5a6ae110169c38075aba8aa"

# Indonesia bounding box
INDONESIA_BBOX = [95, -11, 141, 6]

def fetch_firms_data(satellite="VIIRS_SNPP_NRT", days=5):
    """Fetch data from FIRMS API"""
    bbox_str = ",".join(map(str, INDONESIA_BBOX))
    url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/{satellite}/{bbox_str}/{days}"
    
    print(f"Fetching from: {url}")
    
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    
    # Parse CSV
    df = pd.read_csv(StringIO(response.text))
    return df

# Test 1: Fetch VIIRS data
print("="*60)
print("TEST 1: Fetching VIIRS data for Indonesia (last 5 days)")
print("="*60)

df = fetch_firms_data(satellite="VIIRS_SNPP_NRT", days=5)

print(f"\n✅ Successfully fetched {len(df)} hotspots")
print(f"\nColumns: {list(df.columns)}")
print(f"\nFirst 5 rows:")
print(df.head())

print(f"\n📊 Data Summary:")
print(f"  Date range: {df['acq_date'].min()} to {df['acq_date'].max()}")
print(f"  FRP range: {df['frp'].min():.2f} - {df['frp'].max():.2f} MW")
print(f"  Average FRP: {df['frp'].mean():.2f} MW")

print(f"\n🔥 Confidence Distribution:")
print(df['confidence'].value_counts())

print(f"\n🛰️ Satellite Distribution:")
print(df['satellite'].value_counts())

# Test 2: Fetch from multiple satellites
print("\n" + "="*60)
print("TEST 2: Fetching from ALL satellites (last 1 day)")
print("="*60)

satellites = ["VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "MODIS_NRT"]
all_data = []

for sat in satellites:
    try:
        print(f"\nFetching {sat}...")
        df_sat = fetch_firms_data(satellite=sat, days=1)
        print(f"  ✅ Got {len(df_sat)} hotspots")
        all_data.append(df_sat)
    except Exception as e:
        print(f"  ❌ Failed: {e}")

if all_data:
    df_combined = pd.concat(all_data, ignore_index=True)
    print(f"\n✅ Total combined: {len(df_combined)} hotspots")
    print(f"\n🛰️ Breakdown by satellite:")
    print(df_combined['satellite'].value_counts())
    
    # Show top 10 highest FRP (if data exists)
    if len(df_combined) > 0:
        print(f"\n🔥 Top 10 Highest FRP Hotspots:")
        # Ensure FRP is numeric
        df_combined['frp'] = pd.to_numeric(df_combined['frp'], errors='coerce')
        top_frp = df_combined.nlargest(min(10, len(df_combined)), 'frp')[['latitude', 'longitude', 'frp', 'acq_date', 'satellite']]
        print(top_frp.to_string(index=False))


print("\n" + "="*60)
print("✅ All tests completed successfully!")
print("="*60)

