#!/usr/bin/env python3
"""
Seed an alert with a threshold high enough that the next Beat tick must fire.

Then poll the DB for the NotificationLog row the worker writes.
"""
import json
import sys
import time
import urllib.request

sys.path.insert(0, "/Users/himanshusharma/PulseNotify")

BASE = "http://127.0.0.1:8000"


def call(method, path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req) as r:
        raw = r.read().decode()
        return r.status, (json.loads(raw) if raw else {})


# Unique username per run so re-runs don't collide.
username = f"watcher_{int(time.time())}"
_, body = call("POST", "/api/auth/register/",
               {"username": username, "password": "watcherpass123"})
token = body["access"]
print(f"registered {username}")

# Threshold of 9000 is above the DEL-BOM ceiling (7000), so it MUST trigger.
_, body = call("POST", "/api/alerts/",
               {"origin": "DEL", "destination": "BOM", "threshold_price": 9000},
               token=token)
alert_id = body["id"]
print(f"created alert id={alert_id}  DEL-BOM threshold=9000 (above the 7000 ceiling)")
print("waiting for Celery Beat to fire check_prices...")
