# Victim service - "bad" service for self-healing demo (Phase 2)
# Designed to fail: burn CPU or hang health check.
from fastapi import FastAPI
import threading
import time
import math

app = FastAPI()

# Global flags
state = {"health": True}


@app.get("/")
def read_root():
    if not state["health"]:
        # Simulate a Zombie/Hang process
        time.sleep(300)
    return {"status": "running"}


@app.post("/break/cpu")
def kill_cpu():
    """Starts a thread that burns CPU to ~85% (threshold for alerting)."""
    def burn():
        while True:
            [math.sqrt(i) for i in range(10000000)]
            time.sleep(0.02)  # Keeps CPU ~85%

    threading.Thread(target=burn, daemon=True).start()
    return {"msg": "CPU is now burning (~85%)"}


@app.post("/break/freeze")
def freeze_service():
    """Makes the health check hang."""
    state["health"] = False
    return {"msg": "Service is now a Zombie"}
