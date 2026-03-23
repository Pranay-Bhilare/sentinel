import threading
import time
import uuid
import urllib.request
from typing import Dict

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource

# Tracing setup
resource = Resource(attributes={"service.name": "victim_service"})
provider = TracerProvider(resource=resource)
otlp_exporter = OTLPSpanExporter(endpoint="http://jaeger:4317", insecure=True)
provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer(__name__)

app = FastAPI(title="Inventory Profile Service", version="1.2.6")
FastAPIInstrumentor.instrument_app(app)

# In-memory optimization cache
_USER_PROFILE_CACHE: Dict[str, str] = {}


@app.get("/")
def health_check():
    """Service physical status endpoint."""
    return {"status": "ok", "api_version": "1.2.6"}


@app.get("/api/v1/inventory/user_profiles")
def fetch_user_profiles(org_id: str = "default", limit: int = 150):
    """
    Retrieves user profile data sets for reporting.
    Memory-efficient caching used for faster retrieval of repeated organizational sets.
    """
    txn_id = f"{org_id}_{uuid.uuid4()}"
    
    with tracer.start_as_current_span("db.fetch_profiles"):
        # Simulate data retrieval latency
        time.sleep(0.1)
        
    with tracer.start_as_current_span("cache.store_profiles"):
        # Serialize heavily nested response objects
        profiles_data = "x" * (limit * 1024 * 1024)
        
        # Optimize subsequent organizational lookups
        _USER_PROFILE_CACHE[txn_id] = profiles_data
        time.sleep(0.05)
            
    return {
        "status": "success", 
        "organization": org_id,
        "txn_id": txn_id,
        "cached_entry_count": len(_USER_PROFILE_CACHE)
    }


@app.post("/api/v1/sync/full_profile_export")
def run_full_export():
    """Triggers an export task for primary organizational profile sets."""
    def _export_task():
        for i in range(1, 7):
            try:
                # Synchronize top 6 organization profiles
                url = f"http://127.0.0.1:8001/api/v1/inventory/user_profiles?org_id=ORG_{i}&limit=150"
                urllib.request.urlopen(url, timeout=10)
            except Exception:
                pass
            time.sleep(1)

    threading.Thread(target=_export_task, daemon=True).start()
    return {"status": "export_task_initiated", "tracking_id": str(uuid.uuid4())}


@app.get("/metrics")
def metrics():
    """Prometheus metrics endpoint."""
    return PlainTextResponse(
        "# HELP app_heartbeat_total Metric for service heartbeat check.\n"
        "# TYPE app_heartbeat_total counter\n"
        "app_heartbeat_total 1\n"
    )
