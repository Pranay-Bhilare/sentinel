"""Docker SDK tools for container introspection and control."""
import logging

import docker

client = docker.from_env()
logger = logging.getLogger(__name__)


def get_logs(container_name: str) -> str:
    """Reads stdout from the container."""
    logger.info("Tool: get_logs(container=%s)", container_name)
    container = client.containers.get(container_name)
    return container.logs(tail=50).decode("utf-8")


def restart_container(container_name: str) -> str:
    """Kills and restarts the container."""
    logger.info("Tool: restart_container(container=%s)", container_name)
    container = client.containers.get(container_name)
    container.restart()
    return f"Container {container_name} restarted successfully."


def stop_container(container_name: str) -> str:
    """Stops the container."""
    logger.info("Tool: stop_container(container=%s)", container_name)
    container = client.containers.get(container_name)
    container.stop()
    return f"Container {container_name} stopped."


def get_stats(container_name: str) -> dict:
    """Gets real-time container stats (CPU, memory, etc.)."""
    logger.info("Tool: get_stats(container=%s)", container_name)
    container = client.containers.get(container_name)
    return container.stats(stream=False)
