import asyncio
import time
import logging
import threading
import psutil
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response
import uvicorn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Prometheus metrics ────────────────────────────────────────────────────────
REQUEST_COUNT   = Counter(
    "app_requests_total", "Total HTTP requests",
    ["method", "path", "status"]
)
REQUEST_LATENCY = Histogram(
    "app_request_latency_seconds", "Request latency in seconds",
    ["path"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)
APP_UP              = Gauge("app_up",                  "1 = healthy, 0 = down")
PAYMENT_COUNTER     = Counter("payment_total",         "Total payment attempts", ["status"])
PAYMENT_GATEWAY_UP  = Gauge("payment_gateway_up",      "1 = gateway healthy, 0 = gateway down")
SYSTEM_CPU_PERCENT  = Gauge("system_cpu_percent",      "System CPU usage %")
SYSTEM_MEM_PERCENT  = Gauge("system_memory_percent",   "System memory usage %")
PROCESS_CPU_PERCENT = Gauge("process_cpu_percent",     "Backend process CPU usage %")
LATENCY_INJECTED    = Gauge("latency_injected_seconds","Artificially injected response delay in seconds")

_proc = psutil.Process()

def _update_system_metrics():
    _proc.cpu_percent()  # first call initialises the baseline
    while True:
        SYSTEM_CPU_PERCENT.set(psutil.cpu_percent())
        SYSTEM_MEM_PERCENT.set(psutil.virtual_memory().percent)
        PROCESS_CPU_PERCENT.set(_proc.cpu_percent())
        time.sleep(2)

threading.Thread(target=_update_system_metrics, daemon=True).start()

# ── In-memory state ───────────────────────────────────────────────────────────
OVERLOADED           = False
PAYMENT_GATEWAY_DOWN = False
INJECTED_DELAY       = 0.0   # seconds added to every non-bypass response
next_product_id = 6

PRODUCTS = [
    {"id": 1, "name": "Wireless Headphones", "price": 79.99,  "stock": 50,  "category": "Electronics"},
    {"id": 2, "name": "Running Shoes",        "price": 120.00, "stock": 30,  "category": "Footwear"},
    {"id": 3, "name": "Coffee Maker",         "price": 45.50,  "stock": 15,  "category": "Kitchen"},
    {"id": 4, "name": "Yoga Mat",             "price": 25.00,  "stock": 100, "category": "Fitness"},
    {"id": 5, "name": "Desk Lamp",            "price": 35.99,  "stock": 40,  "category": "Home"},
]

ORDERS = []
next_order_id = 1

# Paths that always work even under overload / latency injection
BYPASS_PATHS = {"/metrics", "/health", "/overload", "/recover", "/status",
                "/payments/fail", "/payments/restore",
                "/latency/inject", "/latency/clear"}

# ── Schemas ───────────────────────────────────────────────────────────────────
class ProductBody(BaseModel):
    name: str
    price: float
    stock: int = 0
    category: str = "General"

class OrderBody(BaseModel):
    product_id: int
    quantity: int = 1
    customer_name: str = "Guest"

class PaymentBody(BaseModel):
    order_id: int
    amount: float
    card_last4: str = "4242"

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="ShopCore API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)
APP_UP.set(1)
PAYMENT_GATEWAY_UP.set(1)


@app.middleware("http")
async def track_metrics(request: Request, call_next):
    if OVERLOADED and request.url.path not in BYPASS_PATHS:
        REQUEST_COUNT.labels(request.method, request.url.path, 503).inc()
        return JSONResponse(
            status_code=503,
            content={"detail": "Service overloaded — self-healing in progress"}
        )

    if INJECTED_DELAY > 0 and request.url.path not in BYPASS_PATHS:
        await asyncio.sleep(INJECTED_DELAY)

    start = time.time()
    response = await call_next(request)
    if request.url.path != "/metrics":
        REQUEST_COUNT.labels(request.method, request.url.path, response.status_code).inc()
        REQUEST_LATENCY.labels(request.url.path).observe(time.time() - start)
    return response


# ── Health & Metrics ──────────────────────────────────────────────────────────
@app.get("/health")
def health():
    if OVERLOADED:
        return JSONResponse(status_code=503, content={"status": "overloaded"})
    return {"status": "healthy"}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/status")
def status():
    return {"overloaded": OVERLOADED}


# ── Chaos controls ────────────────────────────────────────────────────────────
@app.post("/overload")
def trigger_overload():
    global OVERLOADED
    OVERLOADED = True
    APP_UP.set(0)
    logger.warning("⚠️  OVERLOAD triggered — service entering failure mode")
    return {"message": "Service is now overloaded. All requests will return 503."}


@app.post("/recover")
def recover():
    global OVERLOADED
    OVERLOADED = False
    APP_UP.set(1)
    logger.info("✅ RECOVERED — service resuming normal operations")
    return {"message": "Service recovered. Back to normal operations."}


@app.post("/latency/inject")
def inject_latency(delay: float = 2.0):
    global INJECTED_DELAY
    INJECTED_DELAY = delay
    LATENCY_INJECTED.set(delay)
    logger.warning(f"⏱️  LATENCY INJECTED — {delay}s added to every response")
    return {"message": f"Injecting {delay}s delay into all responses.", "delay_seconds": delay}


@app.post("/latency/clear")
def clear_latency():
    global INJECTED_DELAY
    INJECTED_DELAY = 0.0
    LATENCY_INJECTED.set(0)
    logger.info("✅ LATENCY CLEARED — responses back to normal speed")
    return {"message": "Latency injection cleared. Responses are back to normal."}


# ── Products ──────────────────────────────────────────────────────────────────
@app.get("/products")
def list_products():
    return {"products": PRODUCTS, "total": len(PRODUCTS)}


@app.get("/products/{product_id}")
def get_product(product_id: int):
    p = next((p for p in PRODUCTS if p["id"] == product_id), None)
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    return p


@app.post("/products", status_code=201)
def create_product(body: ProductBody):
    global next_product_id
    product = {
        "id": next_product_id,
        "name": body.name, "price": body.price,
        "stock": body.stock, "category": body.category,
    }
    PRODUCTS.append(product)
    next_product_id += 1
    return product


@app.put("/products/{product_id}")
def update_product(product_id: int, body: ProductBody):
    idx = next((i for i, p in enumerate(PRODUCTS) if p["id"] == product_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Product not found")
    PRODUCTS[idx] = {
        "id": product_id, "name": body.name,
        "price": body.price, "stock": body.stock, "category": body.category,
    }
    return PRODUCTS[idx]


@app.delete("/products/{product_id}", status_code=204)
def delete_product(product_id: int):
    idx = next((i for i, p in enumerate(PRODUCTS) if p["id"] == product_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Product not found")
    PRODUCTS.pop(idx)


# ── Orders ────────────────────────────────────────────────────────────────────
@app.get("/orders")
def list_orders():
    return {"orders": ORDERS, "total": len(ORDERS)}


@app.post("/orders", status_code=201)
def place_order(body: OrderBody):
    global next_order_id
    product = next((p for p in PRODUCTS if p["id"] == body.product_id), None)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    order = {
        "order_id": next_order_id,
        "customer_name": body.customer_name,
        "product_id": body.product_id,
        "product_name": product["name"],
        "quantity": body.quantity,
        "unit_price": product["price"],
        "total_price": round(product["price"] * body.quantity, 2),
        "status": "CONFIRMED",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    ORDERS.append(order)
    next_order_id += 1
    logger.info(f"Order #{order['order_id']} placed — {body.customer_name}")
    return order


@app.delete("/orders/{order_id}", status_code=204)
def cancel_order(order_id: int):
    idx = next((i for i, o in enumerate(ORDERS) if o["order_id"] == order_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Order not found")
    ORDERS.pop(idx)


# ── Payments ──────────────────────────────────────────────────────────────────
next_payment_id = 1

@app.post("/payments")
def process_payment(body: PaymentBody):
    global next_payment_id
    if PAYMENT_GATEWAY_DOWN:
        PAYMENT_COUNTER.labels(status="failed").inc()
        logger.warning(f"💳 Payment FAILED for order #{body.order_id} — gateway down")
        raise HTTPException(status_code=402, detail="Payment declined — gateway unavailable")

    payment = {
        "payment_id": next_payment_id,
        "order_id":   body.order_id,
        "amount":     body.amount,
        "card_last4": body.card_last4,
        "status":     "SUCCESS",
        "timestamp":  time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    next_payment_id += 1
    PAYMENT_COUNTER.labels(status="success").inc()
    logger.info(f"💳 Payment #{payment['payment_id']} SUCCESS — ${body.amount}")
    return payment


@app.post("/payments/fail")
def break_payment_gateway():
    global PAYMENT_GATEWAY_DOWN
    PAYMENT_GATEWAY_DOWN = True
    PAYMENT_GATEWAY_UP.set(0)
    logger.warning("⚠️  Payment gateway BROKEN — all payments will fail")
    return {"message": "Payment gateway is now down. All payments will return 402."}


@app.post("/payments/restore")
def restore_payment_gateway():
    global PAYMENT_GATEWAY_DOWN
    PAYMENT_GATEWAY_DOWN = False
    PAYMENT_GATEWAY_UP.set(1)
    logger.info("✅ Payment gateway RESTORED")
    return {"message": "Payment gateway restored. Payments will succeed again."}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
