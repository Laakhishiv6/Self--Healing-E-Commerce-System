# ShopCore — Self- Healing E-commerce

A full-stack e-commerce app with a React frontend, a single FastAPI backend, full SRE observability (SLIs, SLOs, error budgets, burn-rate alerts), and a self-healing infrastructure pipeline.

---

## Architecture

```
React Frontend (5173)
       │
       └──▶ Backend API (8001)  ← Prometheus scrapes /metrics
                 └── Products + Orders + Payments (CRUD)

Prometheus (9091) → Grafana (3002)
Loki      (3100)  → Grafana (3002)   ← Promtail ships container logs
Alertmanager (9093) → Healer (9001) → Backend /recover
```

---

## Quick Start

```bash
docker compose up --build
# Everything starts in ~60 seconds.
```

| Service      | URL                                  |
|--------------|--------------------------------------|
| Frontend     | http://localhost:5173                |
| API docs     | http://localhost:8001/docs           |
| Prometheus   | http://localhost:9091                |
| Alertmanager | http://localhost:9093                |
| Healer log   | http://localhost:9001/log            |
| Grafana      | http://localhost:3002 (admin/admin)  |
| Loki         | http://localhost:3100                |

---

## API Endpoints

| Method   | Path                   | Description         |
|----------|------------------------|---------------------|
| GET      | `/products`            | List all products   |
| POST     | `/products`            | Create product      |
| PUT      | `/products/{id}`       | Update product      |
| DELETE   | `/products/{id}`       | Delete product      |
| GET      | `/orders`              | List all orders     |
| POST     | `/orders`              | Place order         |
| DELETE   | `/orders/{id}`         | Cancel order        |
| GET      | `/health`              | Health check        |
| GET      | `/metrics`             | Prometheus metrics  |

---

## Prometheus Metrics

| Metric                          | Description                              |
|---------------------------------|------------------------------------------|
| `app_requests_total`            | Total requests — labels: method, path, status |
| `app_request_latency_seconds`   | Request latency histogram — label: path  |
| `app_up`                        | 1 = healthy, 0 = down                    |
| `payment_total`                 | Payment attempts — labels: status (success/failed) |
| `payment_gateway_up`            | 1 = gateway healthy, 0 = gateway down    |
| `system_cpu_percent`            | System CPU usage % (updated every 5s via psutil) |
| `system_memory_percent`         | System memory usage % (updated every 5s via psutil) |

---

## SRE — SLIs, SLOs, and Error Budgets

### SLI / SLO Definitions

| SLI | What it measures | SLO Target | Error Budget (30 days) |
|-----|-----------------|------------|----------------------|
| **Availability** | `app_up` — is the service responding? | 99.9% | ~43 minutes |
| **Request Success Rate** | % of requests that return non-5xx | 99% | ~7.3 hours |
| **Latency** | % of requests served within 500ms | 95% | Not time-bounded |
| **Payment Success Rate** | % of payments that succeed | 99.5% | ~3.6 hours |

### How Error Budget Burn Rate Works

A burn rate of **1x** means you're consuming the budget at exactly the rate that exhausts it at month-end.
A burn rate of **14.4x** means the budget will be gone in **2 days** — page immediately.
A burn rate of **6x** means gone in **5 days** — investigate.

### SLO Alerts (in `prometheus/slo_alerts.yml`)

| Alert | Condition | Severity |
|-------|-----------|----------|
| `SLOBreach_Availability` | 1h availability < 99.9% | critical |
| `SLOBreach_RequestSuccess_FastBurn` | Error budget burning 14.4x (1h + 5m windows) | critical |
| `SLOBreach_RequestSuccess_SlowBurn` | Error budget burning 6x (6h + 1h windows) | warning |
| `SLOBreach_Latency` | < 95% of requests within 500ms over 1h | warning |
| `SLOBreach_PaymentSuccess_FastBurn` | Payment budget burning 14.4x | critical |
| `SLOBreach_PaymentSuccess_SlowBurn` | Payment budget burning 6x | warning |

### SLO Dashboard — Grafana Panels

Create a dashboard named **ShopCore SLO Dashboard** and add the panels below.
Open Grafana → `+` → New dashboard → Add visualization → select **Prometheus**.

---

#### Panel 1 — Overall Availability
| Setting | Value |
|---------|-------|
| Panel type | **Stat** |
| Title | `Overall Availability` |
| Unit | `Percent (0–100)` |

```promql
clamp_max(
  100 * sum(rate(app_requests_total{status!~"5.."}[2m]))
  / sum(rate(app_requests_total[2m])),
100)
```

> `clamp_max(..., 100)` prevents values above 100% caused by Prometheus rate extrapolation after container restarts.

**Thresholds:** Base → Red · `99` → Green

---

#### Panel 2 — Endpoint-specific Error Rates
| Setting | Value |
|---------|-------|
| Panel type | **Time series** |
| Title | `Error Rate by Endpoint` |
| Unit | `Percent (0–1)` |
| Legend | `{{path}}` |

```promql
clamp_max(
  sum by (path) (rate(app_requests_total{status=~"5.."}[5m]))
  / sum by (path) (rate(app_requests_total[5m])),
1)
```
Add threshold line at `0.01` (1% = SLO boundary)

---

#### Panel 3 — Endpoint Latency Comparison (P95)
| Setting | Value |
|---------|-------|
| Panel type | **Time series** |
| Title | `P95 Latency by Endpoint` |
| Unit | `Milliseconds (ms)` |
| Legend | `{{path}}` |

```promql
histogram_quantile(0.95,
  sum by (le, path) (rate(app_request_latency_seconds_bucket[5m]))
) * 1000
```
Add threshold line at `500` (500ms SLO boundary)

---

#### Panel 4 — Request Distribution
| Setting | Value |
|---------|-------|
| Panel type | **Pie chart** or **Bar chart** |
| Title | `Request Distribution by Endpoint` |
| Unit | `Requests/sec (rps)` |
| Legend | `{{path}}` |

```promql
sum by (path) (rate(app_requests_total[5m]))
```

---

#### Panel 5 — CPU Usage %
| Setting | Value |
|---------|-------|
| Panel type | **Time series** |
| Title | `CPU Usage %` |
| Unit | `Percent (0–100)` |

```promql
process_cpu_percent
```
> Use `process_cpu_percent` (not `system_cpu_percent`) — this tracks only the backend process so it visibly spikes during the load test and drops back to ~0 after recovery.

**Thresholds:** Base → Green · `50` → Yellow · `80` → Red

---

#### Panel 6 — Memory Usage %
| Setting | Value |
|---------|-------|
| Panel type | **Time series** |
| Title | `Memory Usage %` |
| Unit | `Percent (0–100)` |

```promql
system_memory_percent
```
**Thresholds:** Base → Green · `75` → Yellow · `90` → Red

---

### Before Running the Load Test — Grafana Setup

Set this **before** starting the script so you catch every change live:

1. Open your dashboard → top-right corner → time range: **Last 15 minutes**
2. Auto-refresh dropdown (next to time range) → **5s**
3. Click **Run query** on each panel once to prime it

**What you should see when `run.py` runs:**

| Metric | During load test | After self-heal |
|--------|-----------------|-----------------|
| Overall Availability | drops to **0%** | recovers to **~100%** within 5 min |
| Error Rate by Endpoint | `/products` spikes to **100%** | drops back to 0 |
| CPU Usage % | spikes (40 concurrent workers) | drops back to baseline |
| Memory | slight increase | returns to baseline |

> The recording rules evaluate every **30s**, so panels update with up to 30s lag. If you look immediately after starting the test, wait one refresh cycle.

### Verify SLIs in Prometheus

Open `http://localhost:9091` → Graph, and query:
```promql
sli:request_success_rate:ratio_5m
sli:payment_success_rate:ratio_5m
slo:request_success_rate:burn_rate_1h
```

To trigger SLO breach alerts, run either load test:
```bash
python load-test/run.py              # triggers ServiceDown + SLO burn rate alerts
python load-test/payment_failure.py  # triggers PaymentGatewayDown + payment SLO alerts
```

---

## Chaos Scripts

All scripts live in `load-test/`. Install dependency once: `pip install httpx`

| Script | Failure type | Alerts fired | What healer does |
|--------|-------------|--------------|-----------------|
| `run.py` | Service overload (503 on all) | `ServiceDown` `HighErrorRate` | `POST /recover` |
| `payment_failure.py` | Payment gateway down (402) | `PaymentGatewayDown` `HighPaymentFailureRate` | `POST /payments/restore` |
| `latency_spike.py` | Artificial 2s delay injected | `HighLatency` | `POST /latency/clear` |
| `spike_traffic.py` | 10x organic traffic burst | _(none — service stays healthy)_ | n/a |
| `cascade_failure.py` | Service overload + payment failure simultaneously | All 4 alerts at once | Both `/recover` + `/payments/restore` |

### Script details

#### `run.py` — Service Overload
Calls `POST /overload` then floods `GET /products` for 60s.
Backend returns 503 on everything → `app_up` drops to 0 → Prometheus alerts → Healer calls `/recover`.

#### `payment_failure.py` — Payment Gateway Failure
Makes 5 baseline payments → breaks gateway → floods payment requests for 60s.
All payments return 402 → `payment_gateway_up` drops to 0 → Healer calls `/payments/restore`.

#### `latency_spike.py` — Latency Injection
Injects a 2s artificial delay via `POST /latency/inject?delay=2.0`.
Service stays available but slow → P99 > 1s → `HighLatency` alert fires → Healer calls `/latency/clear`.

```bash
python load-test/latency_spike.py
```

#### `spike_traffic.py` — Organic Traffic Spike _(no failure)_
Three phases: 5 workers (30s) → 50 workers (60s) → 5 workers (30s).
Mixed e-commerce traffic: products, orders, payments. No chaos injected.
Use this to see CPU, request rate, and latency panels move in Grafana without triggering alerts.

```bash
python load-test/spike_traffic.py
```

#### `cascade_failure.py` — Cascade Failure
Breaks payment gateway AND triggers service overload simultaneously.
Fires 4 alerts at once. Alertmanager groups them. Healer independently restores both systems.

```bash
python load-test/cascade_failure.py
```

---

## Self-Healing Demo (Load Test + Alertmanager)

### How it works

```
Load Test Script
    │
    └──▶ POST /overload  →  backend returns 503 on all requests
                             app_up metric drops to 0
                                │
                                ▼
                         Prometheus detects:
                           • app_up == 0      (ServiceDown alert)
                           • error rate > 30% (HighErrorRate alert)
                                │
                                ▼  fires after 10–15s
                         Alertmanager (port 9093)
                                │
                                ▼  webhook after 10s group_wait
                         Healer service (port 9001)
                                │
                                └──▶ POST /recover  →  backend resets
                                                        app_up = 1
                                                        503s stop
```

### Step-by-step

**1. Start the stack**
```bash
docker compose up --build
```

**2. Install the load test dependency**
```bash
pip install httpx
```

**3. Run the load test**
```bash
python load-test/run.py
```

The script will:
- Trigger overload mode on the backend
- Flood it with 40 concurrent requests for 60 seconds
- Print live error rate stats
- Wait and confirm automatic recovery

**4. Watch it heal in real time**

Open these tabs side by side:
- **Grafana** → your dashboard → watch Error Rate spike and Availability drop to 0
- **Alertmanager** → http://localhost:9093 → see `ServiceDown` and `HighErrorRate` fire
- **Healer log** → http://localhost:9001/log → see the healing event appear

**Timeline after the load test starts:**
| Time | Event |
|------|-------|
| 0s   | `/overload` called — backend returns 503, `app_up = 0` |
| 5s   | Prometheus scrapes the 503s and `app_up=0` |
| 10s  | `ServiceDown` alert enters **PENDING** state |
| 20s  | `ServiceDown` becomes **FIRING** — sent to Alertmanager |
| 30s  | Alertmanager waits `group_wait: 10s` then POSTs webhook to healer |
| 31s  | Healer calls `POST /recover` on the backend |
| 32s  | Backend resets: `app_up = 1`, 503s stop |
| 40s  | Prometheus sees healthy metrics again |
| 50s  | Alerts resolve in Alertmanager |

### Alert rules (prometheus/alerts.yml)

| Alert | Condition | For |
|---|---|---|
| `ServiceDown` | `app_up == 0` | 10s |
| `HighErrorRate` | >30% of requests are 5xx | 15s |
| `HighLatency` | P99 latency > 1s | 20s |

### Manual test (without the script)
```bash
# Break it
curl -X POST http://localhost:8001/overload

# Fix it manually (skip waiting for auto-heal)
curl -X POST http://localhost:8001/recover

# Check healer activity
curl http://localhost:9001/log
```

---

## Building Your Grafana Dashboard

Open **http://localhost:3001**, log in with `admin / admin`.

**Create a dashboard:**  
`+` → New dashboard → Add visualization → select **Prometheus** as data source.

For each panel below: paste the query, set the panel type and unit, click **Apply**.

---

### Panel 1 — Availability

| Setting    | Value |
|------------|-------|
| Panel type | **Stat** |
| Title      | `Service Availability` |
| Unit       | None |

**Query:**
```promql
100 * sli:request_success_rate:ratio_5m
```

**Value mappings** (Value mappings tab):
- `0` → `DOWN`
- `1` → `UP`

**Thresholds:**
- Base → Red
- `1` → Green

**Color mode:** Background (makes it bold red/green)

---

### Panel 2 — Request Rate

| Setting    | Value |
|------------|-------|
| Panel type | **Time series** |
| Title      | `Request Rate` |
| Unit       | `Throughput → requests/sec (rps)` |

**Query:**
```promql
sum(rate(app_requests_total[1m]))
```

To break it down by endpoint, use:
```promql
sum by (path) (rate(app_requests_total[1m]))
```
**Legend:** `{{path}}`

---

### Panel 3 — Error Rate

| Setting    | Value |
|------------|-------|
| Panel type | **Time series** |
| Title      | `Error Rate` |
| Unit       | `Throughput → requests/sec (rps)` |

**Query** (4xx + 5xx responses):
```promql
sum(rate(app_requests_total{status=~"4..|5.."}[1m]))
```

**Tip:** In **Standard options → Color scheme** pick **Fixed color → Red** so errors always appear red.

---

### Panel 4 — Request Latency (P99 / P50)

| Setting    | Value |
|------------|-------|
| Panel type | **Time series** |
| Title      | `Request Latency` |
| Unit       | `Time → seconds (s)` |

Add two queries:

**Query A** — Label: `p99`
```promql
histogram_quantile(0.99, sum by (le) (rate(app_request_latency_seconds_bucket[1m])))
```

**Query B** — Label: `p50 (median)`
```promql
histogram_quantile(0.50, sum by (le) (rate(app_request_latency_seconds_bucket[1m])))
```

---

### Panel 5 — CPU Usage

| Setting    | Value |
|------------|-------|
| Panel type | **Time series** |
| Title      | `CPU Usage` |
| Unit       | `Percent (0.0–1.0)` |

**Query:**
```promql
rate(process_cpu_seconds_total[1m])
```

> This metric is automatically exposed by the Python `prometheus_client` library — no extra code needed.

---

### Panel 6 — Memory Usage

| Setting    | Value |
|------------|-------|
| Panel type | **Time series** |
| Title      | `Memory Usage` |
| Unit       | `Data → mebibytes (MiB)` |

**Query:**
```promql
process_resident_memory_bytes / 1024 / 1024
```

---

### Save & watch live

1. Click the floppy disk icon → name it `ShopCore Dashboard` → **Save**
2. Set time range to **Last 5 minutes**, auto-refresh to **5s** (top-right dropdowns)
3. Use the frontend to add products and place orders — watch the panels update in real time

---

## Viewing Logs in Grafana (Loki)

Promtail automatically ships all container logs to Loki. You can explore them in Grafana:

**Open Explore:**
`Grafana → Explore (compass icon) → select "Loki" data source`

### Useful LogQL queries

| What you want | Query |
|---|---|
| All backend logs | `{service="backend"}` |
| All healer logs | `{service="healer"}` |
| Only errors across all services | `{service=~"backend\|healer"} \|= "ERROR"` |
| Payment failures | `{service="backend"} \|= "Payment FAILED"` |
| Healing events | `{service="healer"} \|= "ALERT FIRING"` |
| Gateway restored | `{service="healer"} \|= "Payment gateway restored"` |

### Add a Logs panel to your dashboard

1. Edit your dashboard → **Add visualization**
2. Data source: **Loki**
3. Query: `{service="backend"} |= "ERROR"` (or any LogQL above)
4. Panel type: **Logs**
5. Set time range to **Last 5 minutes**, auto-refresh **5s**

This lets you see error logs and healing events side-by-side with your Prometheus metrics panels.

---

## Useful curl Commands

```bash
# List products
curl http://localhost:8001/products

# Add a product
curl -X POST http://localhost:8001/products \
  -H "Content-Type: application/json" \
  -d '{"name": "Mechanical Keyboard", "price": 89.99, "stock": 20, "category": "Electronics"}'

# Place an order
curl -X POST http://localhost:8001/orders \
  -H "Content-Type: application/json" \
  -d '{"product_id": 1, "quantity": 2, "customer_name": "Alex"}'

# View raw Prometheus metrics
curl http://localhost:8001/metrics
```
