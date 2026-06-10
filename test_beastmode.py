import urllib.request
import json

try:
    response = urllib.request.urlopen('http://127.0.0.1:5000/api/beastmode')
    data = json.loads(response.read().decode('utf-8'))
    print("HITS COUNT:", data['hits'])
    for s in data['signals']:
        print(f"SYMBOL: {s['symbol']} | STACKS: {s.get('highest_stacked_set', 0)}")
except Exception as e:
    print("Error:", e)
