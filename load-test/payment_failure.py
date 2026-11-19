#!/usr/bin/env python3
"""
ShopCore Payment Failure Demo — Self-Healing with Alertmanager
--------------------------------------------------------------
Simulates a real-world scenario where the payment gateway goes down:
  1. Places a few successful orders + payments (baseline)
  2. Breaks the payment gateway  →  all payments return 402
  3. Floods with payment requests so Prometheus metrics spike
  4. Prometheus fires PaymentGatewayDown + HighPaymentFailureRate alerts
  5. Alertmanager routes them to the Healer webhook
  6. Healer calls POST /payments/restore  →  gateway comes back up
  7. Script confirms recovery

Run:
    pip install httpx
    python load-test/payment_failure.py
"""
import asyncio
import sys
import time
import httpx

BASE_URL   = "http://localhost:8001"
HEALER_URL = "http://localhost:9001"
CONCURRENT = 30
DURATION   = 60
SEP        = "─" * 60


async def pay(client: httpx.AsyncClient, sem: asyncio.Semaphore,
              order_id: int, amount: float, counts: dict):
    async with sem:
        try:
            r = await client.post(
                f"{BASE_URL}/payments",
                json={"order_id": order_id, "amount": amount, "card_last4": "4242"},
                timeout=3.0,
            )
            key = "ok" if r.status_code == 200 else "failed"
        except Exception:
            key = "failed"
        counts[key] += 1


async def flood_payments():
    sem    = asyncio.Semaphore(CONCURRENT)
    counts = {"ok": 0, "failed": 0}
    start  = time.time()
    last   = start
    oid    = 1000  # fake order ids

    async with httpx.AsyncClient() as client:
        while time.time() - start < DURATION:
            batch = [
                asyncio.create_task(pay(client, sem, oid + i, round(10 + i * 0.5, 2), counts))
                for i in range(CONCURRENT)
            ]
            await asyncio.gather(*batch)
            oid += CONCURRENT

            if time.time() - last >= 5:
                elapsed = time.time() - start
                total   = counts["ok"] + counts["failed"]
                pct     = counts["failed"] / total * 100 if total else 0
                bar     = "█" * int(elapsed / DURATION * 30)
                print(f"  [{elapsed:5.1f}s] {bar:<30} "
                      f"total={total:5d}  ✓{counts['ok']}  ✗{counts['failed']}  "
                      f"fail={pct:.0f}%")
                last = time.time()

    return counts


async def check_recovery():
    print("\n  Polling for payment gateway recovery (up to 90s)…")
    async with httpx.AsyncClient() as client:
        for i in range(18):
            await asyncio.sleep(5)
            try:
                # Try a real payment — if it succeeds the gateway is back
                r = await client.post(
                    f"{BASE_URL}/payments",
                    json={"order_id": 9999, "amount": 1.00, "card_last4": "0000"},
                    timeout=3.0,
                )
                if r.status_code == 200:
                    return True
                print(f"  [{(i+1)*5}s] Still failing (HTTP {r.status_code})…")
            except Exception as e:
                print(f"  [{(i+1)*5}s] Backend unreachable: {e}")
    return False


async def main():
    print(f"\n{SEP}")
    print("  💳  Payment Failure Demo — Self-Healing with Alertmanager")
    print(SEP)

    # ── Preflight ─────────────────────────────────────────────────
    print("\n▶ Checking backend…")
    try:
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{BASE_URL}/health", timeout=3.0)
        print(f"  Backend: {r.json()}")
    except Exception as e:
        print(f"  ✕ Cannot reach {BASE_URL}: {e}")
        print("    Make sure docker compose is running.\n")
        sys.exit(1)

    # ── Step 1: baseline successful payments ───────────────────────
    print("\n▶ Step 1 — Making 5 successful payments (baseline)…")
    async with httpx.AsyncClient() as c:
        for i in range(1, 6):
            r = await c.post(
                f"{BASE_URL}/payments",
                json={"order_id": i, "amount": round(i * 19.99, 2), "card_last4": "4242"},
                timeout=3.0,
            )
            d = r.json()
            if r.status_code == 200:
                print(f"  ✓ Payment #{d['payment_id']}  order={d['order_id']}  "
                      f"${d['amount']}  status={d['status']}")
            else:
                print(f"  ✗ {d}")

    # ── Step 2: break the payment gateway ─────────────────────────
    print("\n▶ Step 2 — Breaking the payment gateway…")
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{BASE_URL}/payments/fail", timeout=3.0)
    print(f"  {r.json()['message']}")
    print("  payment_gateway_up  →  0")
    print("  All payments will now return HTTP 402 Payment Required")

    # ── Step 3: flood ──────────────────────────────────────────────
    print(f"\n▶ Step 3 — Flooding with {CONCURRENT} concurrent payment requests for {DURATION}s…")
    print("  Watch Grafana  → payment_total{status='failed'} spike")
    print("  Watch Alertmanager → http://localhost:9093")
    print("       alerts: PaymentGatewayDown + HighPaymentFailureRate")
    print("  Watch Healer log   → http://localhost:9001/log\n")

    counts = await flood_payments()

    total = counts["ok"] + counts["failed"]
    pct   = counts["failed"] / total * 100 if total else 0
    print(f"\n  Done.  {total} payments  —  {counts['failed']} failures ({pct:.1f}%)")

    # ── Step 4: wait for Alertmanager → Healer ────────────────────
    print(f"\n▶ Step 4 — Waiting for Alertmanager → Healer to restore gateway…")
    print("  Timeline:")
    print("    ~10s  PaymentGatewayDown enters PENDING in Prometheus")
    print("    ~20s  Alert becomes FIRING → sent to Alertmanager")
    print("    ~30s  Alertmanager group_wait expires → webhook to Healer")
    print("    ~31s  Healer calls POST /payments/restore")
    print("    ~32s  Gateway back up  ✓")

    recovered = await check_recovery()

    # ── Result ────────────────────────────────────────────────────
    print()
    print(SEP)
    if recovered:
        print("  ✅  SELF-HEAL SUCCESS — payment gateway is back online!")
        print()
        print("  What just happened:")
        print("    1. Payment gateway failed  →  402 on every request")
        print("    2. Prometheus saw payment_gateway_up=0 for 10s")
        print("    3. PaymentGatewayDown alert fired")
        print("    4. Alertmanager routed it to the Healer webhook")
        print("    5. Healer called POST /payments/restore")
        print("    6. Gateway came back  →  payments succeeding again")
        print()
        print("  Check the healer log for the full audit trail:")
        print("    http://localhost:9001/log")
    else:
        print("  ⚠️   Gateway did not recover automatically within 90s.")
        print("  Check Alertmanager : http://localhost:9093")
        print("  Check Healer log   : http://localhost:9001/log")
        print(f"  Manual fix         : curl -X POST {BASE_URL}/payments/restore")
    print(SEP + "\n")


if __name__ == "__main__":
    asyncio.run(main())
