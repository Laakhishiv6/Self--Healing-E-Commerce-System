#!/usr/bin/env python3
"""
ShopCore Load Test — Self-Healing Demo
---------------------------------------
1. Triggers overload mode on the backend (all requests return 503)
2. Floods the backend for 60 seconds so Prometheus metrics spike
3. Prometheus fires alert → Alertmanager → Healer calls /recover
4. Service automatically restores itself

Run:
    pip install httpx
    python load-test/run.py
"""
import asyncio
import sys
import time
import httpx

BASE_URL    = "http://localhost:8001"
HEALER_URL  = "http://localhost:9001"
CONCURRENT  = 40    # parallel workers
DURATION    = 60    # seconds to flood
PRINT_EVERY = 5     # seconds between progress lines


async def hit(client: httpx.AsyncClient, sem: asyncio.Semaphore, counts: dict):
    async with sem:
        try:
            r = await client.get(f"{BASE_URL}/products", timeout=3.0)
            key = "ok" if r.status_code < 400 else "err"
        except Exception:
            key = "err"
        counts[key] += 1


async def flood():
    sem    = asyncio.Semaphore(CONCURRENT)
    counts = {"ok": 0, "err": 0}
    start  = time.time()
    last_print = start

    async with httpx.AsyncClient() as client:
        while True:
            elapsed = time.time() - start
            if elapsed >= DURATION:
                break

            batch = [asyncio.create_task(hit(client, sem, counts)) for _ in range(CONCURRENT)]
            await asyncio.gather(*batch)

            if time.time() - last_print >= PRINT_EVERY:
                total   = counts["ok"] + counts["err"]
                err_pct = counts["err"] / total * 100 if total else 0
                bar     = "█" * int(elapsed / DURATION * 30)
                print(f"  [{elapsed:5.1f}s] {bar:<30} "
                      f"req={total:5d}  ✓{counts['ok']}  ✗{counts['err']}  "
                      f"err={err_pct:.0f}%")
                last_print = time.time()

    return counts


async def check_recovery():
    print("\n  Polling for recovery (up to 90s)…")
    async with httpx.AsyncClient() as client:
        for i in range(18):
            await asyncio.sleep(5)
            try:
                r = await client.get(f"{BASE_URL}/status", timeout=3.0)
                if r.status_code == 200 and not r.json().get("overloaded"):
                    return True
                print(f"  [{(i+1)*5}s] Still overloaded…")
            except Exception:
                print(f"  [{(i+1)*5}s] Backend unreachable…")
    return False


async def main():
    SEP = "─" * 58

    print(f"\n{SEP}")
    print("  🔥  ShopCore Load Test — Self-Healing Demo")
    print(SEP)

    # ── Preflight ────────────────────────────────────────────────
    print("\n▶ Checking backend is reachable…")
    try:
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{BASE_URL}/health", timeout=3.0)
        print(f"  Backend: {r.json()}")
    except Exception as e:
        print(f"  ✕ Cannot reach {BASE_URL}: {e}")
        print("    Make sure docker compose is running.\n")
        sys.exit(1)

    # ── Step 1: trigger overload ──────────────────────────────────
    print("\n▶ Step 1 — Triggering overload mode on backend…")
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{BASE_URL}/overload", timeout=3.0)
    print(f"  {r.json()['message']}")
    print("  app_up  →  0   (Prometheus will detect this)")

    # ── Step 2: flood ─────────────────────────────────────────────
    print(f"\n▶ Step 2 — Flooding with {CONCURRENT} concurrent workers for {DURATION}s…")
    print("  Watch Grafana → Error Rate spike,  Availability drop to 0")
    print("  Watch Alertmanager → http://localhost:9093")
    print("  Watch Healer log  → http://localhost:9001/log\n")

    counts = await flood()

    total   = counts["ok"] + counts["err"]
    err_pct = counts["err"] / total * 100 if total else 0

    print(f"\n  Done.  {total} requests  —  {counts['err']} errors ({err_pct:.1f}%)")

    # ── Step 3: wait for self-heal ────────────────────────────────
    print(f"\n▶ Step 3 — Waiting for Alertmanager → Healer to auto-recover…")
    print("  (alert fires after ~15s, Alertmanager waits 10s, healer responds)")

    recovered = await check_recovery()

    print()
    print(SEP)
    if recovered:
        print("  ✅  SELF-HEAL SUCCESS — backend is back to normal!")
        print(f"  Open http://localhost:5173 and place an order to verify.")
    else:
        print("  ⚠️   Did not detect automatic recovery within 90s.")
        print("  Check Alertmanager: http://localhost:9093")
        print("  Check Healer log:   http://localhost:9001/log")
        print(f"  Manual recover:     curl -X POST {BASE_URL}/recover")
    print(SEP + "\n")


if __name__ == "__main__":
    asyncio.run(main())
