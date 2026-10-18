# PulseNotify

A flight price monitoring service. Users set price alerts on routes they care about — if the
price drops below their threshold, PulseNotify fires a notification. It runs entirely in the
background: the API responds instantly, and Celery handles the checking.

This is the backend behind Google Flights alerts, Skyscanner price notifications, and Hopper's
price prediction.

## How it works

```
  User sets alert:  route=DEL-BOM, threshold=₹4500
                    ↓
  POST /api/alerts/          →  PriceAlert saved to DB
                    ↓
  Celery Beat fires every 60 seconds
                    ↓
  check_prices task wakes up
                    ↓
  GET /api/flights/price/?route=DEL-BOM     ← our own mock endpoint
                    ↓
  { "route": "DEL-BOM", "price": 4200 }
                    ↓
  4200 <= 4500 ?  YES
                    ↓
  send_notification.delay()   ← async, never blocks Beat
                    ↓
  NotificationLog written to DB, alert marked TRIGGERED
                    ↓
  GET /api/admin/summary/     →  admin sees platform stats
```

Two Celery tasks:

| Task | Trigger | What it does |
|---|---|---|
| `check_prices` | Celery Beat, every 60s | Fetches the price for each route that has active alerts, and for every alert whose threshold is met, fires `send_notification` |
| `send_notification` | `.delay()` from `check_prices` | Writes the `NotificationLog` row and marks the alert TRIGGERED so it fires only once |

## Requirements

- Python 3.12+
- PostgreSQL 16 (Docker)
- Redis 7 (Docker)

## Setup

```bash
# 1. Install dependencies
uv sync                      # or: pip install -r requirements.txt

# 2. Start PostgreSQL + Redis
docker compose up -d db redis

# 3. Configure the environment
cp .env.example .env         # then edit DJANGO_SETTINGS_MODULE if you deploy

# 4. Migrate
python manage.py migrate
```

`.env` holds every secret — `SECRET_KEY`, DB credentials, broker URL. It's in `.gitignore` and
must never be committed. `.env.example` is the committed template.

```bash
DJANGO_SETTINGS_MODULE=config.settings.local      # → config.settings.production when deploying
```

## Running — three terminals

The system needs three processes at once. Start them in this order.

```bash
# Terminal 1 — the API
python manage.py runserver
```

```bash
# Terminal 2 — the Celery worker (executes the tasks)
celery -A config worker --loglevel=info
```

```bash
# Terminal 3 — Celery Beat (fires check_prices every 60s)
celery -A config beat --loglevel=info
```

Watch **Terminal 3** for `check-flight-prices-every-minute` firing every 60 seconds, and
**Terminal 2** for `send_notification` tasks arriving whenever a threshold is met.

To trigger a check immediately instead of waiting for Beat:
`celery -A config call pulse.tasks.check_prices`.

> macOS note: billiard 4.3 uses the `spawn` start method on macOS, which breaks Celery's
> prefork pool unless `FORKED_BY_MULTIPROCESSING=1` is set. `config/celery.py` sets it for
> you, so the plain `celery -A config worker` command above works as-is.

## API

Base URL: `http://localhost:8000`

| Method | Endpoint | Auth | Purpose |
|---|---|---|---|
| POST | `/api/auth/register/` | public | Create a user, return a JWT |
| POST | `/api/auth/login/` | public | Validate credentials, return a JWT |
| GET | `/api/alerts/` | JWT | List the caller's alerts |
| POST | `/api/alerts/` | JWT | Create an alert for the caller |
| DELETE | `/api/alerts/<id>/` | JWT | Deactivate the caller's alert |
| GET | `/api/flights/price/?route=DEL-BOM` | public | Mock price feed (called by Celery) |
| GET | `/api/admin/summary/` | admin | Platform-wide statistics |

### Register

```bash
curl -X POST http://localhost:8000/api/auth/register/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"securepass123","email":"alice@example.com"}'
```

`201 Created`

```json
{
  "username": "alice",
  "email": "alice@example.com",
  "role": "user",
  "access": "eyJ...",
  "refresh": "eyJ..."
}
```

`role` is never read from the request body — it always defaults to `user`. A duplicate
username returns `400`.

### Login

```bash
curl -X POST http://localhost:8000/api/auth/login/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"securepass123"}'
```

Returns `200` with a fresh JWT, or `401` for invalid credentials.

### Create an alert

```bash
curl -X POST http://localhost:8000/api/alerts/ \
  -H 'Authorization: Bearer <access_token>' \
  -H 'Content-Type: application/json' \
  -d '{"origin":"DEL","destination":"BOM","threshold_price":4500}'
```

The user is taken from the JWT (`request.user`), never from the body — so you can't create an
alert on someone else's behalf.

### List alerts

```bash
curl http://localhost:8000/api/alerts/ \
  -H 'Authorization: Bearer <access_token>'
```

The queryset is scoped to `request.user` in `get_queryset()`. A user with no alerts gets `[]`,
not a `404`.

### Delete an alert

```bash
curl -X DELETE http://localhost:8000/api/alerts/1/ \
  -H 'Authorization: Bearer <access_token>'
```

`200 { "status": "inactive" }`

This sets `status = INACTIVE` — it does **not** delete the row. An inactive alert stops being
checked by Beat. Deleting someone else's alert returns `404`, never `403`, so the existence of
another user's alert is never leaked.

### Mock price feed

```bash
curl 'http://localhost:8000/api/flights/price/?route=DEL-BOM'
```

```json
{ "route": "DEL-BOM", "price": 4200 }
```

Prices are random integers inside a per-route range. Hit it repeatedly and the price changes.

| Route | Range |
|---|---|
| DEL-BOM | ₹3,000 – ₹7,000 |
| BLR-HYD | ₹1,500 – ₹4,000 |
| DEL-BLR | ₹4,000 – ₹9,000 |
| BOM-GOA | ₹2,000 – ₹5,000 |

Unknown routes return `404`. This endpoint is unauthenticated — it's the one Celery calls
internally with `requests.get()`.

### Admin summary

```bash
curl http://localhost:8000/api/admin/summary/ \
  -H 'Authorization: Bearer <admin_access_token>'
```

```json
{
  "total_alerts": 24,
  "active_alerts": 18,
  "triggered_alerts": 4,
  "total_notifications": 11,
  "top_routes": [
    { "route": "DEL-BOM", "alert_count": 8 },
    { "route": "BLR-HYD", "alert_count": 6 }
  ]
}
```

Admin-only — regular user tokens get `403`. All counting happens in the database via
`aggregate()` / `annotate()`; there are no Python loops counting rows.

## Creating an admin

`IsAdminUser` checks `UserProfile.role`, not `User.is_staff`. Promote a user in the Django
admin, or directly:

```bash
python manage.py shell -c "
from django.contrib.auth.models import User
u = User.objects.get(username='alice')
u.profile.role = 'admin'
u.profile.save()
print(u.profile.role)
"
```

Then log in again to get a token carrying the admin role.

## Project layout

```
pulsenotify/
├── config/
│   ├── __init__.py          imports the Celery app
│   ├── celery.py            Celery application + autodiscovery
│   ├── urls.py              all 7 routes
│   └── settings/
│       ├── base.py          shared: INSTALLED_APPS, DRF, JWT, Celery, Beat schedule
│       ├── local.py         DEBUG=True, local DB, browsable API
│       ├── production.py    DEBUG=False, mandatory env secrets
│       └── test.py          SQLite + eager Celery for the test suite
├── pulse/
│   ├── models.py            UserProfile, PriceAlert, NotificationLog
│   ├── signals.py           post_save → auto-create UserProfile
│   ├── apps.py              ready() connects the signals
│   ├── tasks.py             check_prices, send_notification
│   ├── views.py             the 7 endpoints
│   ├── permissions.py       custom IsAdminUser
│   ├── admin.py
│   └── tests.py             32 tests
├── postman/                 PulseNotify.postman_collection.json
├── docker-compose.yml       PostgreSQL + Redis
├── requirements.txt         pinned
└── .env.example
```

## Tests

```bash
# Fast — SQLite, no Docker needed
DJANGO_SETTINGS_MODULE=config.settings.test python manage.py test

# Against your real PostgreSQL
python manage.py test
```

The three required unit tests live in `pulse/tests.py`:

1. `PriceThresholdTest` — threshold comparison logic
2. `NotificationLogTest` — `NotificationLog` is created correctly
3. `AlertScopingTest` — users see only their own alerts

Alongside them: profile auto-creation, the admin permission, all 7 endpoints, and both
Celery tasks — 32 tests in total.

`scripts/verify_e2e.py` drives the same 13 scenarios over real HTTP against a running server.

## Postman

Import `postman/PulseNotify.postman_collection.json`. Set `base_url` (defaults to
`http://localhost:8000`), then run the collection in order — the scripts save the access token
and the created alert id into collection variables for you.

The 15 requests cover all 13 required scenarios plus the admin-success and second-user setup
cases. Request 15 needs an admin JWT pasted into `admin_token`.

## Design notes

**Why a mock price feed instead of a real flight API?** Real providers (Skyscanner, Amadeus,
RapidAPI) require registration, API keys, credit cards, and often enforce rate limits tight
enough to silently block you for hours. The `requests.get()` pattern is identical either way,
so the learning outcome is the same with none of the blockers — and you keep full control over
the price data.

**Why `.delay()` for the notification?** `check_prices` runs on a schedule, so anything slow
inside it delays every other check. `send_notification.delay()` puts the work on the queue and
returns immediately, so Beat keeps its 60-second cadence regardless of how long notifications
take.

**Why deactivate instead of delete?** An alert is a record of what the user asked for. Setting
`status = INACTIVE` keeps that history and stops the checks; deleting the row would lose the
`NotificationLog` trail with it.
