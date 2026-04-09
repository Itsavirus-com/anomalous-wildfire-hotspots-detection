# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
import requests

r = requests.get("http://localhost:8000/api/alerts", timeout=5)
data = r.json()
print(f"Status: {r.status_code}")
print(f"Total alerts: {data['total_alerts']}")
print(f"Date: {data['date']}")
print()
for a in data["alerts"][:3]:
    print(f"  Rank {a['rank']}: {a['h3_index'][:12]}...")
    print(f"    Province : {a['province']}")
    print(f"    Regency  : {a['regency']}")
    print(f"    Coords   : ({a['center_lat']:.4f}, {a['center_lng']:.4f})")
    print(f"    Score    : {a['hybrid_score']:.4f} | Coherence: {a['spatial_coherence_level']}")
    print()
