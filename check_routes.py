from server_v5 import app
for rule in app.url_map.iter_rules():
    print(f"{rule.endpoint}: {rule.rule}")
