# Victim service - "bad" service for self-healing demo (Phase 2)
# Placeholder for Step 1: project structure
from fastapi import FastAPI

app = FastAPI()


@app.get("/")
def read_root():
    return {"status": "running", "service": "orders-service"}
