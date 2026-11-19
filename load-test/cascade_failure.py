#!/usr/bin/env python3
"""
ShopCore Cascade Failure Demo — Service + Payments Down Simultaneously
----------------------------------------------------------------------
Simulates a catastrophic outage where two independent systems fail at once
(e.g. a bad deployment that breaks both the app server and the payment provider):

  1. Breaks payment gateway  →  all payments return 402
  2. Triggers service overload →  all requests return 503
  3. Floods with both payment and product requests
  4. Alertmanager receives FOUR firing alerts simultaneously:
       • PaymentGatewayDown
       • HighPaymentFailureRate
       • ServiceDown
       • HighErrorRate
  5. Healer processes each alert:
       • PaymentGatewayDown/HighPaymentFailureRate → POST /payments/restore
       • ServiceDown/HighErrorRate                → POST /recover
  6. Both systems come back online independently

Watch in Grafana:
  • Availability   → drops to 0%
  • Error Rate     → spikes to 100%
  • Payment Rate   → fails 100%
  • All recover after Healer acts

Run:
    pip install httpx
    python load-test/cascade_failure.py
"""
import asyncio
import sys
import time
import httpx

BASE_URL   = "http://localhost:8001"
CONCURRENT = 30
DURATION   = 60
SEP        = "─" * 60


async def hit_product(client, sem, counts):
    async with sem:
        try:
            r = await client.get(f"{BASE_URL}/products", timeout=3.0)
            counts["product_ok" if r.status_code == 200 else "product_fail"] += 1
        except Exception:
            counts["product_fail"] += 1


async def hit_payment(client, sem, counts):
    async with sem:
        try:
            r = await client.post(
                f"{BASE_URL}/payments",
                json={"order_id": 9000, "amount": 49.99, "card_last4": "1234"},
                timeout=3.0,
            )
            counts["payment_ok" if r.status_code == 200 else "payment_fail"] += 1
        except Exception:
            counts["payment_fail"] += 1


async def flood_both():
    sem    = asyncio.Semaphore(CONCURRENT)
    counts = {"product_ok": 0, "product_fail": 0, "payment_ok": 0, "payment_fail": 0}
    start  = time.time()
    last   = start

    async with httpx.AsyncClient() as client:
        while time.time() - start < DURATION:
            batch = []
            for i in range(CONCURRENT // 2):
                batch.append(asyncio.create_task(hit_product(client, sem, counts)))
                batch.append(asyncio.create_task(hit_payment(client, sem, counts)))
            await asyncio.gather(*batch)

            if time.time() - last >= 5:
                elapsed = time.time() - start
                bar     = "█" * int(elapsed / DURATION * 28)
                print(f"  [{elapsed:5.1f}s] {bar:<28} "
                      f"products ✓{counts['product_ok']} ✗{counts['product_fail']}  "
                      f"payments ✓{counts['payment_ok']} ✗{counts['payment_fail']}")
                last = time.time()

    return counts


async def check_both_recovered():
    print("\n  Polling for full recovery (up to 120s)…")
    async with httpx.AsyncClient() as client:
        for i in range(24):
            await asyncio.sleep(5)
            try:
                # Check service
                status_r  = await client.get(f"{BASE_URL}/status", timeout=3.0)
                service_ok = (status_r.status_code == 200 and
                              not status_r.json().get("overloaded"))

                # Check payment gateway
                pay_r     = await client.post(
                    f"{BASE_URL}/payments",
                    json={"order_id": 99999, "amount": 1.00, "card_last4": "0000"},
                    timeout=3.0,
                )
                payment_ok = pay_r.status_code == 200

                status_str = f"service={'✓' if service_ok else '✗'}  payment={'✓' if payment_ok else '✗'}"
                print(f"  [{(i+1)*5}s] {status_str}")

                if service_ok and payment_ok:
                    return True
            except Exception as e:
                print(f"  [{(i+1)*5}s] Check failed: {e}")
    return False


async def main():
    print(f"\n{SEP}")
    print("  💥  Cascade Failure Demo — Service + Payments Simultaneously")
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

    # ── Step 1: break payment gateway ─────────────────────────────
    print("\n▶ Step 1 — Breaking payment gateway…")
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{BASE_URL}/payments/fail", timeout=3.0)
    print(f"  {r.json()['message']}")

    await asyncio.sleep(1)

    # ── Step 2: trigger service overload ──────────────────────────
    print("\n▶ Step 2 — Triggering service overload…")
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{BASE_URL}/overload", timeout=3.0)
    print(f"  {r.json()['message']}")
    print()
    print("  Both systems are now down:")
    print("    payment_gateway_up  →  0  (402 on payments)")
    print("    app_up              →  0  (503 on everything else)")

    # ── Step 3: flood ──────────────────────────────────────────────
    print(f"\n▶ Step 3 — Flooding with {CONCURRENT} concurrent requests for {DURATION}s…")
    print("  Watch Alertmanager → 4 alerts fire simultaneously:")
    print("    • PaymentGatewayDown     • HighPaymentFailureRate")
    print("    • ServiceDown            • HighErrorRate")
    print("  Watch Healer log → http://localhost:9001/log\n")

    counts = await flood_both()

    p_total  = counts["product_ok"]  + counts["product_fail"]
    py_total = counts["payment_ok"]  + counts["payment_fail"]
    print(f"\n  Done.")
    print(f"  Products: {p_total} requests  — {counts['product_fail']} failures")
    print(f"  Payments: {py_total} requests  — {counts['payment_fail']} failures")

    # ── Step 4: wait for full recovery ────────────────────────────
    print(f"\n▶ Step 4 — Waiting for Alertmanager → Healer to restore both systems…")
    print("  Healer will:")
    print("    PaymentGatewayDown/HighPaymentFailureRate → POST /payments/restore")
    print("    ServiceDown/HighErrorRate                → POST /recover")

    fully_recovered = await check_both_recovered()

    # ── Result ────────────────────────────────────────────────────
    print()
    print(SEP)
    if fully_recovered:
        print("  ✅  FULL CASCADE RECOVERY — both systems are back online!")
        print()
        print("  What just happened:")
        print("    1. Payment gateway + service failed simultaneously")
        print("    2. Prometheus fired 4 alerts at once")
        print("    3. Alertmanager grouped & routed them to Healer")
        print("    4. Healer independently restored each system")
        print("    5. Both came back online without human intervention")
        print()
        print("  Full audit trail: http://localhost:9001/log")
    else:
        print("  ⚠️   Not fully recovered within 120s.")
        print("  Check Alertmanager : http://localhost:9093")
        print("  Check Healer log   : http://localhost:9001/log")
        print(f"  Manual fix:")
        print(f"    curl -X POST {BASE_URL}/recover")
        print(f"    curl -X POST {BASE_URL}/payments/restore")
    print(SEP + "\n")


if __name__ == "__main__":
    asyncio.run(main())
