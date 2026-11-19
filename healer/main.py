"""
Self-Healer Service
Receives Alertmanager webhooks and automatically recovers the backend.
"""
import logging
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

BACKEND_URL = "http://backend:8001"

app = FastAPI(title="Self-Healer")
heal_log = []  # in-memory log of healing events


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/log")
def get_log():
    return {"events": heal_log}


@app.post("/webhook")
async def alertmanager_webhook(request: Request):
    """
    Alertmanager calls this endpoint when an alert fires.
    We inspect the alert name and trigger recovery automatically.
    """
    payload = await request.json()
    alerts = payload.get("alerts", [])

    for alert in alerts:
        status     = alert.get("status", "")
        alert_name = alert.get("labels", {}).get("alertname", "unknown")
        severity   = alert.get("labels", {}).get("severity", "unknown")

        if status == "firing":
            logger.warning(f"🚨 ALERT FIRING  [{severity}] {alert_name}")

            if alert_name in ("PaymentGatewayDown", "HighPaymentFailureRate"):
                action = "restore_payments"
                result = await restore_payments()
            elif alert_name == "HighLatency":
                action = "clear_latency"
                result = await clear_latency()
            else:
                action = "recover_service"
                result = await attempt_recovery()

            event = {"alert": alert_name, "severity": severity, "action": action, "result": result}
            heal_log.append(event)
            logger.info(f"📋 Healing result: {result}")

        elif status == "resolved":
            logger.info(f"✅ ALERT RESOLVED [{severity}] {alert_name} — system back to normal")
            heal_log.append({"alert": alert_name, "severity": severity, "action": "none", "result": "resolved"})

    return JSONResponse(status_code=200, content={"status": "ok", "alerts_processed": len(alerts)})


async def restore_payments() -> str:
    logger.info("💳 Calling POST /payments/restore on backend...")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(f"{BACKEND_URL}/payments/restore")
            if r.status_code == 200:
                msg = "✅ Payment gateway restored via /payments/restore"
                logger.info(msg)
                return msg
            msg = f"⚠️  /payments/restore returned {r.status_code}"
            logger.warning(msg)
            return msg
    except Exception as e:
        msg = f"❌ Could not reach backend: {e}"
        logger.error(msg)
        return msg


async def clear_latency() -> str:
    logger.info("⏱️  Calling POST /latency/clear on backend...")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(f"{BACKEND_URL}/latency/clear")
            if r.status_code == 200:
                msg = "✅ Latency injection cleared via /latency/clear"
                logger.info(msg)
                return msg
            msg = f"⚠️  /latency/clear returned {r.status_code}"
            logger.warning(msg)
            return msg
    except Exception as e:
        msg = f"❌ Could not reach backend: {e}"
        logger.error(msg)
        return msg


async def attempt_recovery() -> str:
    logger.info("🔧 Calling POST /recover on backend...")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(f"{BACKEND_URL}/recover")
            if r.status_code == 200:
                msg = "✅ Backend recovered via /recover"
                logger.info(msg)
                return msg
            else:
                msg = f"⚠️  /recover returned {r.status_code}"
                logger.warning(msg)
                return msg
    except httpx.ConnectError:
        msg = "❌ Backend unreachable — recovery skipped"
        logger.error(msg)
        return msg
    except Exception as e:
        msg = f"❌ Unexpected error: {e}"
        logger.error(msg)
        return msg


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9001)
