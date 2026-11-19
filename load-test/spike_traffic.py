#!/usr/bin/env python3
"""
ShopCore Traffic Spike Demo
---------------------------
Simulates a flash sale or viral traffic event — sudden 10x traffic surge
with NO service failure. Shows how the system behaves under organic load:

  Phase 1 (30s): Low baseline  —  5 concurrent workers
  Phase 2 (60s): Traffic spike — 50 concurrent workers (10x)
  Phase 3 (30s): Wind down     —  5 concurrent workers

Traffic is realistic e-commerce: mix of product browsing, order checks,
and payments. No chaos injected — service stays healthy throughout.

Watch in Grafana:
  • Request Rate   → flat → spike → flat
  • CPU Usage %    → rises during spike, drops after
  • P95 Latency    → may rise slightly under load, recovers
  • Availability   → stays at 100% the whole time (no errors)

Run:
    pip install httpx
    python load-test/spike_traffic.py
"""
import asyncio
import sys
import time
import random
import httpx

BASE_URL = "http://localhost:8001"
SEP      = "─" * 60

PHASES = [
    {"name": "Baseline",      "workers":  5, "duration": 30},
    {"name": "Traffic Spike", "workers": 50, "duration": 60},
    {"name": "Wind Down",     "workers":  5, "duration": 30},
]

ENDPOINTS = [
    ("GET",  "/products",       None),
    ("GET",  "/products/1",     None),
    ("GET",  "/products/2",     None),
    ("GET",  "/orders",         None),
    ("POST", "/payments", {"order_id": 1, "amount": 29.99, "card_last4": "4242"}),
]


async def request(client: httpx.AsyncClient, sem: asyncio.Semaphore, counts: dict):
    async with sem:
        method, path, body = random.choice(ENDPOINTS)
        try:
            if method == "GET":
                r = await client.get(f"{BASE_URL}{path}", timeout=5.0)
            else:
                r = await client.post(f"{BASE_URL}{path}", json=body, timeout=5.0)
            key = "ok" if r.status_code < 400 else "err"
        except Exception:
            key = "err"
        counts[key] += 1


async def run_phase(name: str, workers: int, duration: int):
    sem    = asyncio.Semaphore(workers)
    counts = {"ok": 0, "err": 0}
    start  = time.time()
    last   = start

    print(f"\n  ── {name} ({workers} workers, {duration}s) ──")

    async with httpx.AsyncClient() as client:
        while time.time() - start < duration:
            batch = [
                asyncio.create_task(request(client, sem, counts))
                for _ in range(workers)
            ]
            await asyncio.gather(*batch)

            if time.time() - last >= 5:
                elapsed = time.time() - start
                total   = counts["ok"] + counts["err"]
                rps     = total / elapsed if elapsed > 0 else 0
                bar     = "█" * int(elapsed / duration * 20)
                print(f"  [{elapsed:5.1f}s] {bar:<20} "
                      f"rps={rps:5.1f}  ✓{counts['ok']}  ✗{counts['err']}")
                last = time.time()

    elapsed = time.time() - start
    total   = counts["ok"] + counts["err"]
    rps     = total / elapsed if elapsed > 0 else 0
    print(f"  Phase done — {total} requests  avg {rps:.1f} rps  "
          f"errors: {counts['err']}")
    return counts


async def main():
    print(f"\n{SEP}")
    print("  📈  Traffic Spike Demo — Organic Load Test")
    print(SEP)

    # ── Preflight ─────────────────────────────────────────────────
    print("\n▶ Checking backend…")
    try:
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{BASE_URL}/health", timeout=3.0)
        print(f"  Backend: {r.json()}")
    except Exception as e:
        print(f"  ✕ Cannot reach {BASE_URL}: {e}")
        sys.exit(1)

    print()
    print("  This demo does NOT inject failures.")
    print("  Watch Grafana to see request rate and CPU spike, then recover.")
    print("  Availability should stay at 100% throughout.\n")
    print("  Open Grafana: http://localhost:3002")
    print("  Set time range: Last 5 minutes, auto-refresh: 5s\n")

    total_ok  = 0
    total_err = 0

    for phase in PHASES:
        counts = await run_phase(**phase)
        total_ok  += counts["ok"]
        total_err += counts["err"]

    print()
    print(SEP)
    print(f"  ✅  Traffic spike complete")
    print(f"  Total requests: {total_ok + total_err}")
    print(f"  Successful:     {total_ok}")
    print(f"  Errors:         {total_err}  "
          f"({'expected — payments fail when gateway is down' if total_err else 'none'})")
    print()
    print("  What you should have seen in Grafana:")
    print("    • Request Rate:  5 rps → 50 rps → 5 rps")
    print("    • CPU Usage:     low  → high   → low")
    print("    • Availability:  100% throughout")
    print("    • Latency:       stable or slight rise during spike")
    print(SEP + "\n")


if __name__ == "__main__":
    asyncio.run(main())
