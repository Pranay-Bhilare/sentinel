"""
LangChain tools for the Operator agent. Wraps Docker SDK helpers so the LLM
can choose which remediation to run via bind_tools / tool_calls.
"""
import json
import logging

from langchain_core.tools import tool

from app.tools import (
    get_logs as _get_logs,
    get_stats as _get_stats,
    inspect_container as _inspect_container,
    network_connect as _network_connect,
    network_disconnect as _network_disconnect,
    restart_container as _restart_container,
    rollback_container as _rollback_container,
    stop_container as _stop_container,
    update_container_resources as _update_container_resources,
)

logger = logging.getLogger(__name__)


@tool
def get_logs(container_name: str) -> str:
    """Read the last 50 lines of stdout/stderr from a container. Use to inspect application logs when diagnosing an alert."""
    return _get_logs(container_name)


@tool
def get_stats(container_name: str) -> str:
    """Get real-time container stats (CPU, memory, network). Returns a text summary. Use to confirm resource usage before or after remediation."""
    raw = _get_stats(container_name)
    if not raw:
        return "No stats available."
    cpu = raw.get("cpu_stats", {}) or {}
    mem = raw.get("memory_stats", {}) or {}
    usage = mem.get("usage", 0) or 0
    return f"CPU stats: {json.dumps(cpu)[:500]}; Memory usage bytes: {usage}"


@tool
def inspect_container(container_name: str) -> str:
    """Get full container config (image, env, mounts, ports, networks). Use before rollback or recreate to know current setup."""
    attrs = _inspect_container(container_name)
    image = attrs.get("Config", {}).get("Image", "?")
    networks = list((attrs.get("NetworkSettings") or {}).get("Networks") or [])
    return f"Image: {image}; Networks: {networks}; (full attrs available in backend)"


@tool
def restart_container(container_name: str) -> str:
    """Restart a Docker container. Use when the container is stuck, in a CPU/memory loop, or needs a clean state. Clears in-process state."""
    return _restart_container(container_name)


@tool
def stop_container(container_name: str) -> str:
    """Stop a Docker container. Use when the service must be taken down (e.g. containment, or after rollback to avoid duplicate)."""
    return _stop_container(container_name)


@tool
def network_disconnect(container_name: str, network_name: str = "") -> str:
    """Disconnect a container from a Docker network. Use for containment when the service is flooding the network or misbehaving. If network_name is empty, disconnects from the first attached network."""
    return _network_disconnect(container_name, network_name or None)


@tool
def network_connect(container_name: str, network_name: str) -> str:
    """Reconnect a container to a Docker network. Use after containment or to restore connectivity (e.g. after network_disconnect)."""
    return _network_connect(container_name, network_name)


@tool
def update_container_resources(
    container_name: str,
    memory_limit_mb: int = None,
    cpu_limit: float = None,
) -> str:
    """Update CPU and/or memory limits on a running container without restart. Use when the container is hitting OOM or needs more CPU headroom. Pass at least one of memory_limit_mb or cpu_limit."""
    return _update_container_resources(
        container_name,
        memory_limit_mb=memory_limit_mb,
        cpu_limit=cpu_limit,
    )


@tool
def rollback_container(container_name: str) -> str:
    """Revert the container to the previous image tag (e.g. last known good version). Use after a bad deploy or when the current image is failing. Requires a previous tag to exist (e.g. victim:prev or versioned tags)."""
    return _rollback_container(container_name)


OPERATOR_TOOLS = [
    get_logs,
    get_stats,
    inspect_container,
    restart_container,
    stop_container,
    network_disconnect,
    network_connect,
    update_container_resources,
    rollback_container,
]
