import time
import random
import logging
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

# ── OpenTelemetry setup ──────────────────────────────────────────────────────
resource = Resource(attributes={"service.name": "product-service"})
provider = TracerProvider(resource=resource)
exporter = OTLPSpanExporter(endpoint="http://jaeger:4317", insecure=True)
provider.add_span_processor(BatchSpanProcessor(exporter))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer(__name__)

# ── Prometheus metrics ───────────────────────────────────────────────────────
REQUEST_COUNT   = Counter("product_requests_total",    "Total requests",        ["method","endpoint","status"])
REQUEST_LATENCY = Histogram("product_request_latency", "Request latency (s)",   ["endpoint"])
ERROR_COUNT     = Counter("product_errors_total",      "Total errors",          ["endpoint"])
SERVICE_UP      = Gauge("product_service_up",          "1 = healthy, 0 = down")

# ── State ────────────────────────────────────────────────────────────────────
SERVICE_FAILING = False
next_product_id = 6

PRODUCTS = [
    {"id": 1, "name": "Wireless Headphones", "price": 79.99,  "stock": 50, "category": "Electronics"},
    {"id": 2, "name": "Running Shoes",        "price": 120.00, "stock": 30, "category": "Footwear"},
    {"id": 3, "name": "Coffee Maker",         "price": 45.50,  "stock": 15, "category": "Kitchen"},
    {"id": 4, "name": "Yoga Mat",             "price": 25.00,  "stock": 100,"category": "Fitness"},
    {"id": 5, "name": "Desk Lamp",            "price": 35.99,  "stock": 40, "category": "Home"},
]

class ProductRequest(BaseModel):
    name: str
    price: float
    stock: int = 0
    category: str = "General"

# ── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(title="Product Service")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
FastAPIInstrumentor.instrument_app(app)
SERVICE_UP.set(1)


@app.get("/health")
def health():
    if SERVICE_FAILING:
        SERVICE_UP.set(0)
        REQUEST_COUNT.labels("GET", "/health", "503").inc()
        raise HTTPException(status_code=503, detail="Service is in failure mode")
    SERVICE_UP.set(1)
    REQUEST_COUNT.labels("GET", "/health", "200").inc()
    return {"status": "healthy", "service": "product-service"}


@app.get("/products")
def list_products():
    start = time.time()
    with tracer.start_as_current_span("list-products"):
        if SERVICE_FAILING:
            ERROR_COUNT.labels("/products").inc()
            REQUEST_COUNT.labels("GET", "/products", "503").inc()
            raise HTTPException(status_code=503, detail="Product service unavailable")

        # Simulate occasional slow response
        if random.random() < 0.1:
            time.sleep(0.5)

        REQUEST_COUNT.labels("GET", "/products", "200").inc()
        REQUEST_LATENCY.labels("/products").observe(time.time() - start)
        return {"products": PRODUCTS, "total": len(PRODUCTS)}


@app.get("/products/{product_id}")
def get_product(product_id: int):
    start = time.time()
    with tracer.start_as_current_span("get-product") as span:
        span.set_attribute("product.id", product_id)

        if SERVICE_FAILING:
            ERROR_COUNT.labels("/products/{id}").inc()
            REQUEST_COUNT.labels("GET", "/products/{id}", "503").inc()
            raise HTTPException(status_code=503, detail="Product service unavailable")

        product = next((p for p in PRODUCTS if p["id"] == product_id), None)
        if not product:
            REQUEST_COUNT.labels("GET", "/products/{id}", "404").inc()
            raise HTTPException(status_code=404, detail="Product not found")

        REQUEST_COUNT.labels("GET", "/products/{id}", "200").inc()
        REQUEST_LATENCY.labels("/products/{id}").observe(time.time() - start)
        return product


@app.post("/products", status_code=201)
def create_product(body: ProductRequest):
    global next_product_id
    product = {"id": next_product_id, "name": body.name, "price": body.price, "stock": body.stock, "category": body.category}
    PRODUCTS.append(product)
    next_product_id += 1
    REQUEST_COUNT.labels("POST", "/products", "201").inc()
    return product


@app.put("/products/{product_id}")
def update_product(product_id: int, body: ProductRequest):
    idx = next((i for i, p in enumerate(PRODUCTS) if p["id"] == product_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Product not found")
    PRODUCTS[idx] = {"id": product_id, "name": body.name, "price": body.price, "stock": body.stock, "category": body.category}
    REQUEST_COUNT.labels("PUT", "/products/{id}", "200").inc()
    return PRODUCTS[idx]


@app.delete("/products/{product_id}", status_code=204)
def delete_product(product_id: int):
    idx = next((i for i, p in enumerate(PRODUCTS) if p["id"] == product_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Product not found")
    PRODUCTS.pop(idx)
    REQUEST_COUNT.labels("DELETE", "/products/{id}", "204").inc()


@app.post("/fail")
def trigger_failure():
    """Simulate service failure for demo purposes."""
    global SERVICE_FAILING
    SERVICE_FAILING = True
    SERVICE_UP.set(0)
    logger.warning("⚠️  Product service entering FAILURE mode")
    return {"status": "failing", "message": "Product service is now simulating failure"}


@app.post("/recover")
def recover():
    """Recover service from failure mode."""
    global SERVICE_FAILING
    SERVICE_FAILING = False
    SERVICE_UP.set(1)
    logger.info("✅  Product service RECOVERED")
    return {"status": "healthy", "message": "Product service has recovered"}


@app.get("/status")
def status():
    return {"failing": SERVICE_FAILING, "service": "product-service"}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
