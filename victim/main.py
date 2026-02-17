# Victim service - "bad" service for self-healing demo.
# Designed to fail: burn CPU, memory, network, or simulate bad deploy.
import threading
import time
import math
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

app = FastAPI()

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
