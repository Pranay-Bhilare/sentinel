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


import uuid
from typing import Dict

# Application-level optimization cache to reduce DB load
_USER_PROFILE_CACHE: Dict[str, str] = {}

@app.get("/api/v1/organizations/{org_id}/users")
def fetch_organization_users(org_id: str, limit: int = 150):
    """
    Fetches user profiles for an organization in bulk.
    We utilize an in-memory application cache to optimize repeated lookups 
    for the same organizational batches during peak hours.
    """
    batch_txn_id = f"{org_id}_{uuid.uuid4()}"
    
    with tracer.start_as_current_span("db.query_org_users"):
        # Simulate network latency to primary DB replica
        time.sleep(0.1)
        
    with tracer.start_as_current_span("cache.store_profiles"):
        # Serialize heavily nested user objects from DB
        serialized_payload = "x" * (limit * 1024 * 1024)
        
        # Store in cache for subsequent identical requests
        _USER_PROFILE_CACHE[batch_txn_id] = serialized_payload
        time.sleep(0.05)
            
    return {
        "status": "success", 
        "org_id": org_id,
        "records_processed": limit,
        "cache_hits": len(_USER_PROFILE_CACHE)
    }

@app.post("/api/v1/internal/cron/warmup_caches")
def warmup_organization_caches():
    """Internal cron job: Warms up user caches for the daily morning traffic spike."""
    def _warmup_task():
        import urllib.request
        for i in range(1, 7):
            try:
                # Pre-fetch top 6 largest organizations to populate the cache
                url = f"http://127.0.0.1:8001/api/v1/organizations/org_{i}/users?limit=150"
                urllib.request.urlopen(url, timeout=10)
            except Exception:
                pass
            time.sleep(1)

    threading.Thread(target=_warmup_task, daemon=True).start()
    return {"status": "scheduled", "job_type": "cache_warmup_job"}


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
