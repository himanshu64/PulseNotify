#!/usr/bin/env python3
"""
End-to-end verification of the PulseNotify flow.

Registers a user, logs in, creates an alert, hits the mock price feed, and
confirms the admin summary — the same 13 scenarios the Postman collection
covers, driven over real HTTP against runserver.
"""
import json
import urllib.request
import urllib.error
import uuid

BASE = "http://127.0.0.1:8000"
# Unique usernames per run so reruns against a persistent Postgres don't collide.
RUN = uuid.uuid4().hex[:6]
ALICE, BOB = f"alice_{RUN}", f"bob_{RUN}"
passed, failed = [], []


def call(method, path, body=None, token=None):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"raw": raw}


def check(name, got, want):
    if got == want:
        passed.append(name)
        print(f"  PASS  {name}")
    else:
        failed.append(name)
        print(f"  FAIL  {name}  (got {got!r}, want {want!r})")


print("=" * 62)
print("1. POST /api/auth/register/  (public)")
s, b = call("POST", "/api/auth/register/",
            {"username": ALICE, "password": "securepass123",
             "email": "alice@example.com"})
check("register -> 201", s, 201)
check("register returns access token", "access" in b, True)
check("register role defaults to USER", b.get("role"), "user")
alice_token = b.get("access")

print("\n2. POST /api/auth/register/  (duplicate username)")
s, b = call("POST", "/api/auth/register/",
            {"username": ALICE, "password": "anotherpass"})
check("duplicate register -> 400", s, 400)

print("\n3. POST /api/auth/login/  (public)")
s, b = call("POST", "/api/auth/login/",
            {"username": ALICE, "password": "securepass123"})
check("login -> 200", s, 200)
check("login returns access token", "access" in b, True)

print("\n4. POST /api/auth/login/  (bad credentials)")
s, b = call("POST", "/api/auth/login/",
            {"username": ALICE, "password": "wrongpass"})
check("bad login -> 401", s, 401)

print("\n5. POST /api/alerts/  (JWT)")
s, b = call("POST", "/api/alerts/",
            {"origin": "DEL", "destination": "BOM", "threshold_price": 4500},
            token=alice_token)
check("create alert -> 201", s, 201)
alert_id = b.get("id")
check("alert origin uppercased", b.get("origin"), "DEL")
check("alert status active", b.get("status"), "active")

print("\n6. GET /api/alerts/  (JWT, own only)")
s, b = call("GET", "/api/alerts/", token=alice_token)
check("list alerts -> 200", s, 200)
check("list is a list", isinstance(b, list), True)
check("sees exactly 1 alert", len(b), 1)

print("\n7. GET /api/alerts/  (no token)")
s, b = call("GET", "/api/alerts/")
check("unauthenticated -> 401", s, 401)

print("\n8. POST /api/alerts/  (no token)")
s, b = call("POST", "/api/alerts/",
            {"origin": "DEL", "destination": "BOM", "threshold_price": 4000})
check("unauthenticated create -> 401", s, 401)

print("\n9. GET /api/flights/price/?route=DEL-BOM  (public mock feed)")
s, b = call("GET", "/api/flights/price/?route=DEL-BOM")
check("price feed -> 200", s, 200)
check("returns route", b.get("route"), "DEL-BOM")
check("price is an int", isinstance(b.get("price"), int), True)

print("\n10. GET /api/flights/price/?route=XXX-YYY  (unknown route)")
s, b = call("GET", "/api/flights/price/?route=XXX-YYY")
check("unknown route -> 404", s, 404)

print("\n11. DELETE /api/alerts/<id>/  (own alert)")
s, b = call("DELETE", f"/api/alerts/{alert_id}/", token=alice_token)
check("delete own alert -> 200", s, 200)
check("returns inactive", b.get("status"), "inactive")

print("\n12. DELETE /api/alerts/<id>/  (someone else's alert)")
s, b = call("POST", "/api/auth/register/",
            {"username": BOB, "password": "bobspass123"})
bob_token = b.get("access")
s, b = call("DELETE", f"/api/alerts/{alert_id}/", token=bob_token)
check("cross-user delete -> 404", s, 404)

print("\n13. GET /api/admin/summary/  (regular user -> 403)")
s, b = call("GET", "/api/admin/summary/", token=alice_token)
check("regular user summary -> 403", s, 403)

print("\n" + "=" * 62)
print(f"RESULT: {len(passed)} passed, {len(failed)} failed")
if failed:
    print("FAILED:", ", ".join(failed))
print("=" * 62)
raise SystemExit(1 if failed else 0)
