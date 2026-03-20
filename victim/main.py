import threading
import time
import math
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource

# Setup tracing
resource = Resource(attributes={"service.name": "victim_service"})
provider = TracerProvider(resource=resource)
otlp_exporter = OTLPSpanExporter(endpoint="http://jaeger:4317", insecure=True)
provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer(__name__)

app = FastAPI()

FastAPIInstrumentor.instrument_app(app)

state = {"health": True, "bad_deploy": False}
memory_holder = []
failures_total = 0


@app.get("/")
def read_root():
    if not state["health"]:
        time.sleep(300)
    return {"status": "running"}


@app.post("/break/cpu")
def kill_cpu():
    """Starts a thread that burns CPU to ~85% (threshold for alerting)."""
    def burn():
        while True:
            [math.sqrt(i) for i in range(10000000)]
            time.sleep(0.02)

    threading.Thread(target=burn, daemon=True).start()
    return {"msg": "CPU is now burning (~85%)"}


@app.post("/break/freeze")
def freeze_service():
    """Makes the health check hang."""
    state["health"] = False
    return {"msg": "Service is now a Zombie"}


@app.post("/break/network")
def flood_network():
    """Starts threads that generate outbound-like activity (many small requests in a loop)."""
    import urllib.request
    def flood():
        while True:
            try:
                urllib.request.urlopen("http://127.0.0.1:8001/", timeout=0.5)
            except Exception:
                pass
            time.sleep(0.01)
    for _ in range(20):
        t = threading.Thread(target=flood, daemon=True)
        t.start()
    return {"msg": "Network flood started (many local requests)"}


@app.post("/break/memory")
def burn_memory():
    """Allocates and holds ~50MB to push container memory up."""
    global memory_holder
    chunk = "x" * (5 * 1024 * 1024)
    memory_holder.append(chunk)
    return {"msg": "Memory burn: holding ~50MB more", "chunks": len(memory_holder)}


@app.post("/break/bad_deploy")
def bad_deploy():
    """Simulates bad deploy: start returning errors and increment failure metric."""
    global state
    state["bad_deploy"] = True

    def trigger_failures():
        import urllib.request
        while state.get("bad_deploy"):
            try:
                urllib.request.urlopen("http://127.0.0.1:8001/broken", timeout=1)
            except Exception:
                pass
            time.sleep(2)

    threading.Thread(target=trigger_failures, daemon=True).start()
    return {"msg": "Bad deploy mode: errors will be reported periodically"}


@app.get("/api/fetch_orders")
def fetch_orders():
    """Simulates an endpoint that does N+1 queries. Takes a long time."""
    with tracer.start_as_current_span("db.query_orders"):
        time.sleep(0.1) # Simulate main query
    
    # N+1 simulation
    for i in range(50):
        with tracer.start_as_current_span(f"db.query_item_{i}"):
            time.sleep(0.05) # Simulate individual item query
            
    return {"status": "success", "orders_fetched": 50}


@app.post("/break/n_plus_one")
def trigger_n_plus_one():
    """Starts a background thread hitting the N+1 endpoint repeatedly."""
    def hit_endpoint():
        import urllib.request
        while True:
            try:
                urllib.request.urlopen("http://127.0.0.1:8001/api/fetch_orders", timeout=10)
            except Exception:
                pass
            time.sleep(1)

    threading.Thread(target=hit_endpoint, daemon=True).start()
    return {"msg": "Triggered N+1 query loop! Check Jaeger for massive latency traces."}


@app.get("/broken")
def broken_endpoint():
    """Returns 500 when bad_deploy is on; used to drive app_failures_total."""
    global failures_total
    if state.get("bad_deploy"):
        failures_total += 1
        return PlainTextResponse("error", status_code=500)
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    """Prometheus-format metrics for HighErrorRate alert."""
    return PlainTextResponse(
        f"# HELP app_failures_total Total application failures (e.g. 500s).\n"
        f"# TYPE app_failures_total counter\n"
        f"app_failures_total {failures_total}\n"
    )
