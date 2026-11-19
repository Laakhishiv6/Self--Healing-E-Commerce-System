#!/usr/bin/env python3
"""
ShopCore Latency Spike Demo — Self-Healing with Alertmanager
------------------------------------------------------------
Simulates a slow downstream dependency (e.g. slow database):
  1. Injects a 2s artificial delay into every backend response
  2. Floods with concurrent requests so the histogram fills with slow samples
  3. Prometheus detects P99 latency > 1s → HighLatency alert fires
  4. Alertmanager routes to Healer → Healer calls POST /latency/clear
  5. Responses return to normal speed

Watch in Grafana:
  • P95 Latency by Endpoint → spikes to ~2000ms
  • Overall Availability → stays at 100% (requests succeed, just slow)

Run:
    pip install httpx
    python load-test/latency_spike.py
"""
import asyncio
import sys
import time
import httpx

BASE_URL   = "http://localhost:8001"
CONCURRENT = 20
DURATION   = 60
SEP        = "─" * 60


async def hit(client: httpx.AsyncClient, sem: asyncio.Semaphore, counts: dict):
    async with sem:
        try:
            r = await client.get(f"{BASE_URL}/products", timeout=10.0)
            key = "ok" if r.status_code == 200 else "slow_fail"
        except Exception:
            key = "slow_fail"
        counts[key] += 1


async def flood_slow():
    sem    = asyncio.Semaphore(CONCURRENT)
    counts = {"ok": 0, "slow_fail": 0}
    start  = time.time()
    last   = start

    async with httpx.AsyncClient() as client:
        while time.time() - start < DURATION:
            batch = [
                asyncio.create_task(hit(client, sem, counts))
                for _ in range(CONCURRENT)
            ]
            await asyncio.gather(*batch)

            if time.time() - last >= 5:
                elapsed = time.time() - start
                total   = counts["ok"] + counts["slow_fail"]
                bar     = "█" * int(elapsed / DURATION * 30)
                print(f"  [{elapsed:5.1f}s] {bar:<30} "
                      f"total={total:4d}  ✓{counts['ok']}  ✗{counts['slow_fail']}")
                last = time.time()

    return counts


async def check_recovery():
    print("\n  Polling for latency recovery (up to 90s)…")
    async with httpx.AsyncClient() as client:
        for i in range(18):
            await asyncio.sleep(5)
            try:
                t0 = time.time()
                r  = await client.get(f"{BASE_URL}/products", timeout=5.0)
                rt = (time.time() - t0) * 1000
                if r.status_code == 200 and rt < 500:
                    return True
                print(f"  [{(i+1)*5}s] Still slow ({rt:.0f}ms)…")
            except Exception as e:
                print(f"  [{(i+1)*5}s] Request failed: {e}")
    return False


async def main():
    print(f"\n{SEP}")
    print("  ⏱️   Latency Spike Demo — Self-Healing with Alertmanager")
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

    # ── Step 1: baseline latency ───────────────────────────────────
    print("\n▶ Step 1 — Measuring baseline latency…")
    async with httpx.AsyncClient() as c:
        times = []
        for _ in range(5):
            t0 = time.time()
            await c.get(f"{BASE_URL}/products", timeout=3.0)
            times.append((time.time() - t0) * 1000)
    print(f"  Baseline P99: ~{max(times):.0f}ms  avg: {sum(times)/len(times):.0f}ms")

    # ── Step 2: inject latency ─────────────────────────────────────
    print("\n▶ Step 2 — Injecting 2s artificial delay into all responses…")
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{BASE_URL}/latency/inject?delay=2.0", timeout=5.0)
    print(f"  {r.json()['message']}")
    print("  latency_injected_seconds  →  2.0")
    print("  Every request will now take ~2 seconds")

    # ── Step 3: flood ──────────────────────────────────────────────
    print(f"\n▶ Step 3 — Flooding with {CONCURRENT} concurrent requests for {DURATION}s…")
    print("  Watch Grafana → P95 Latency spikes to ~2000ms")
    print("  Watch Prometheus → histogram_quantile(0.99, ...) > 1")
    print("  Watch Alertmanager → HighLatency alert (fires after 20s)\n")

    counts = await flood_slow()
    total  = counts["ok"] + counts["slow_fail"]
    print(f"\n  Done. {total} requests completed (all ~2s each)")

    # ── Step 4: wait for Alertmanager → Healer ────────────────────
    print(f"\n▶ Step 4 — Waiting for Alertmanager → Healer to clear latency…")
    print("  Timeline:")
    print("    ~20s  HighLatency enters PENDING (P99 > 1s for 20s)")
    print("    ~30s  Alert becomes FIRING → sent to Alertmanager")
    print("    ~40s  Alertmanager group_wait expires → webhook to Healer")
    print("    ~41s  Healer calls POST /latency/clear")
    print("    ~42s  Responses back to normal speed  ✓")

    recovered = await check_recovery()

    # ── Result ────────────────────────────────────────────────────
    print()
    print(SEP)
    if recovered:
        print("  ✅  SELF-HEAL SUCCESS — latency is back to normal!")
        print()
        print("  What just happened:")
        print("    1. 2s delay injected  →  P99 latency > 1s")
        print("    2. Prometheus fired HighLatency alert after 20s")
        print("    3. Alertmanager routed it to the Healer webhook")
        print("    4. Healer called POST /latency/clear")
        print("    5. Responses back to <50ms")
        print()
        print("  Check the healer log:")
        print("    http://localhost:9001/log")
    else:
        print("  ⚠️   Latency did not recover automatically within 90s.")
        print("  Check Alertmanager : http://localhost:9093")
        print("  Check Healer log   : http://localhost:9001/log")
        print(f"  Manual fix         : curl -X POST {BASE_URL}/latency/clear")
    print(SEP + "\n")


if __name__ == "__main__":
    asyncio.run(main())
