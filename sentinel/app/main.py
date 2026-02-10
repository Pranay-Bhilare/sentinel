# Sentinel API - FastAPI ingestion for Alertmanager webhooks ()
# GROQ-only for LLM calls
from fastapi import FastAPI

app = FastAPI(title="Sentinel API")


@app.get("/health")
def health():
    return {"status": "ok"}
