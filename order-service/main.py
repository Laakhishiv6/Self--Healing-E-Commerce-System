import time
import asyncio
import logging
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
import uvicorn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── OpenTelemetry ─────────────────────────────────────────────────────────────
resource = Resource(attributes={"service.name": "order-service"})
provider = TracerProvider(resource=resource)
exporter = OTLPSpanExporter(endpoint="http://jaeger:4317", insecure=True)
provider.add_span_processor(BatchSpanProcessor(exporter))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer(__name__)

# ── Prometheus ────────────────────────────────────────────────────────────────
ORDER_COUNT      = Counter("order_requests_total",       "Total orders placed",         ["status"])
ORDER_LATENCY    = Histogram("order_request_latency",    "Order latency (s)")
RETRY_COUNT      = Counter("order_retries_total",        "Product fetch retries")
FALLBACK_COUNT   = Counter("order_fallbacks_total",      "Times fallback was used")
SERVICE_UP       = Gauge("order_service_up",             "1 = healthy")

PRODUCT_SERVICE_URL = "http://product-service:8001"

# ── Retry helper ──────────────────────────────────────────────────────────────
async def fetch_product_with_retry(product_id: int, max_retries: int = 3):
    """Exponential backoff retry. Falls back to cached stub on total failure."""
    last_error = None
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"{PRODUCT_SERVICE_URL}/products/{product_id}")
                r.raise_for_status()
                logger.info(f"✅ Product fetched on attempt {attempt + 1}")
                return r.json(), False  # (data, used_fallback)
        except Exception as e:
            last_error = e
            wait = (2 ** attempt) * 0.5   # 0.5s, 1s, 2s
            logger.warning(f"⚠️  Attempt {attempt+1} failed: {e}. Retrying in {wait}s…")
            RETRY_COUNT.inc()
            if attempt < max_retries - 1:
                await asyncio.sleep(wait)

    # All retries exhausted → graceful fallback
    logger.error(f"❌ All retries failed. Serving fallback for product {product_id}")
    FALLBACK_COUNT.inc()
    fallback = {
        "id": product_id,
        "name": "Product (cached)",
        "price": 0.0,
        "stock": 0,
        "category": "Unknown",
        "_fallback": True,
    }
    return fallback, True  # (data, used_fallback)


# ── State / storage ────────────────────────────────────────────────────────────
orders = []
order_id_counter = 1

class OrderRequest(BaseModel):
    product_id: int
    quantity: int = 1
    customer_name: str = "Guest"

# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(title="Order Service")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
FastAPIInstrumentor.instrument_app(app)
SERVICE_UP.set(1)


@app.get("/health")
def health():
    return {"status": "healthy", "service": "order-service"}


@app.post("/orders")
async def place_order(order_req: OrderRequest):
    global order_id_counter
    start = time.time()

    with tracer.start_as_current_span("place-order") as span:
        span.set_attribute("product.id", order_req.product_id)
        span.set_attribute("customer", order_req.customer_name)

        product, used_fallback = await fetch_product_with_retry(order_req.product_id)

        order = {
            "order_id": order_id_counter,
            "customer_name": order_req.customer_name,
            "product_id": order_req.product_id,
            "product_name": product.get("name", "Unknown"),
            "quantity": order_req.quantity,
            "unit_price": product.get("price", 0.0),
            "total_price": round(product.get("price", 0.0) * order_req.quantity, 2),
            "status": "PLACED_WITH_FALLBACK" if used_fallback else "CONFIRMED",
            "fallback_used": used_fallback,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        orders.append(order)
        order_id_counter += 1

        status_label = "fallback" if used_fallback else "success"
        ORDER_COUNT.labels(status_label).inc()
        ORDER_LATENCY.observe(time.time() - start)

        span.set_attribute("order.fallback", used_fallback)
        span.set_attribute("order.id", order["order_id"])

        return order


@app.get("/orders")
def list_orders():
    return {"orders": orders, "total": len(orders)}


@app.delete("/orders/{order_id}", status_code=204)
def cancel_order(order_id: int):
    idx = next((i for i, o in enumerate(orders) if o["order_id"] == order_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Order not found")
    orders.pop(idx)


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8002)
