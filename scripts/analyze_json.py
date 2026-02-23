import json

# Load JSON data
with open('fire_nrt_SV-C2_714486.json', 'r') as f:
    data = json.load(f)

print(f"Total hotspot records: {len(data):,}")
print(f"\nDate range: {data[0]['acq_date']} to {data[-1]['acq_date']}")

# Check unique dates
dates = sorted(set(record['acq_date'] for record in data))
print(f"\nTotal days of data: {len(dates)}")
print(f"First date: {dates[0]}")
print(f"Last date: {dates[-1]}")

# Sample record
print(f"\nSample record:")
print(json.dumps(data[0], indent=2))

# Statistics
satellites = set(record['satellite'] for record in data)
print(f"\nSatellites: {satellites}")

confidences = {}
for record in data:
    conf = record['confidence']
    confidences[conf] = confidences.get(conf, 0) + 1

print(f"\nConfidence distribution:")
for conf, count in sorted(confidences.items()):
    print(f"  {conf}: {count:,} ({count/len(data)*100:.1f}%)")
