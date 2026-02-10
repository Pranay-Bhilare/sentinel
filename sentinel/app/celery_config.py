"""Celery app config. No task imports - prevents graph/checkpointer load in API."""
from celery import Celery

celery_app = Celery("sentinel", broker="redis://redis:6379/0")
