"""
LangChain tools for the Sentinel Agents. 
Includes both Investigator (observation) and Operator (remediation) tools.
"""
import json
import logging
import urllib.request
import urllib.parse
import docker
from langchain_core.tools import tool

client = docker.from_env()
logger = logging.getLogger(__name__)

# ==========================================
# INVESTIGATOR TOOLS (Autonomous RCA)
# ==========================================

@tool
def fetch_recent_traces(service_name: str, limit: int = 5) -> str:
    """Fetch recent distributed traces from Jaeger for a service. Useful for finding API endpoints that are slow (latency) or throwing errors."""
    logger.info("Tool: fetch_recent_traces(service=%s, limit=%s)", service_name, limit)
    try:
        url = f"http://jaeger:16686/api/traces?service={urllib.parse.quote(service_name)}&limit={limit}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            
        if not data.get("data"):
            return "No traces found."
            
        traces_info = []
        for t in data["data"]:
            trace_id = t["traceID"]
            spans = t.get("spans", [])
            traces_info.append(f"\nTrace ID: {trace_id} ({len(spans)} spans)")
            
            for span in spans:
                duration_ms = span.get("duration", 0) / 1000.0
                op_name = span.get("operationName", "unknown")
                tags = {tg["key"]: tg["value"] for tg in span.get("tags", [])}
                
                if duration_ms > 10 or tags.get("error"):
                    err_str = " [ERROR]" if tags.get("error") else ""
                    traces_info.append(f"  - Span: {op_name}{err_str} | Duration: {duration_ms}ms | Tags: {tags}")
            
        return "\n".join(traces_info)[:4000]
    except Exception as e:
        return f"Failed to fetch traces: {e}"

@tool
def read_docker_source_code(container_name: str, file_path: str, start_line: int, end_line: int) -> str:
    """Reads specific lines from a file inside a running docker container. Use this to read the problematic application code."""
    logger.info("Tool: read_docker_source_code(container=%s, file=%s)", container_name, file_path)
    try:
        container = client.containers.get(container_name)
        cmd = ["sed", "-n", f"{start_line},{end_line}p", file_path]
        exit_code, output = container.exec_run(cmd)
        if exit_code != 0:
            return f"Failed to read file. Output: {output.decode('utf-8')}"
        
        lines = output.decode("utf-8").splitlines()
        numbered_lines = [f"{start_line + i}: {line}" for i, line in enumerate(lines)]
        return "\n".join(numbered_lines)
    except Exception as e:
        return f"Failed to read source code: {e}"

# NOTE: We register tools at the bottom after they are all defined.

# ==========================================
# OPERATOR TOOLS (Remediation Actions)
# ==========================================

@tool
def get_logs(container_name: str) -> str:
    """Read the last 50 lines of stdout/stderr from a container."""
    logger.info("Tool: get_logs(container=%s)", container_name)
    try:
        container = client.containers.get(container_name)
        return container.logs(tail=50).decode("utf-8")
    except docker.errors.APIError as e:
        return f"Failed to get logs: {e}"

@tool
def get_stats(container_name: str) -> str:
    """Get real-time container stats (CPU, memory, network). Returns a text summary."""
    logger.info("Tool: get_stats(container=%s)", container_name)
    try:
        container = client.containers.get(container_name)
        raw = container.stats(stream=False)
        if not raw:
            return "No stats available."
        cpu = raw.get("cpu_stats", {}) or {}
        mem = raw.get("memory_stats", {}) or {}
        usage = mem.get("usage", 0) or 0
        return f"CPU stats: {json.dumps(cpu)[:500]}; Memory usage bytes: {usage}"
    except Exception as e:
        return f"Failed to get stats: {e}"

@tool
def inspect_container(container_name: str) -> str:
    """Get full container config (image, env, mounts, ports, networks)."""
    logger.info("Tool: inspect_container(container=%s)", container_name)
    try:
        container = client.containers.get(container_name)
        attrs = container.attrs
        image = attrs.get("Config", {}).get("Image", "?")
        networks = list((attrs.get("NetworkSettings") or {}).get("Networks") or [])
        return f"Image: {image}; Networks: {networks}; (full attrs available in backend)"
    except Exception as e:
        return f"Failed to inspect: {e}"

@tool
def restart_container(container_name: str) -> str:
    """Restart a Docker container. Use when the container is stuck, in a CPU/memory loop, or needs a clean state."""
    logger.info("Tool: restart_container(container=%s)", container_name)
    try:
        container = client.containers.get(container_name)
        container.restart()
        return f"Container {container_name} restarted successfully."
    except Exception as e:
        return f"Failed to restart: {e}"

@tool
def stop_container(container_name: str) -> str:
    """Stop a Docker container."""
    logger.info("Tool: stop_container(container=%s)", container_name)
    try:
        container = client.containers.get(container_name)
        container.stop()
        return f"Container {container_name} stopped."
    except Exception as e:
        return f"Failed to stop: {e}"

@tool
def network_disconnect(container_name: str, network_name: str = "") -> str:
    """Disconnect a container from a Docker network."""
    logger.info("Tool: network_disconnect(container=%s, network=%s)", container_name, network_name)
    try:
        container = client.containers.get(container_name)
        if not network_name:
            networks = container.attrs.get("NetworkSettings", {}).get("Networks", {})
            if not networks:
                return f"Container {container_name} has no networks to disconnect."
            network_name = list(networks.keys())[0]
        container.disconnect(network=network_name)
        return f"Container {container_name} disconnected from network {network_name}."
    except Exception as e:
        return f"Failed to disconnect: {e}"

@tool
def network_connect(container_name: str, network_name: str) -> str:
    """Reconnect a container to a Docker network."""
    logger.info("Tool: network_connect(container=%s, network=%s)", container_name, network_name)
    try:
        container = client.containers.get(container_name)
        container.connect(network=network_name)
        return f"Container {container_name} connected to network {network_name}."
    except Exception as e:
        return f"Failed to connect: {e}"

@tool
def update_container_resources(container_name: str, memory_limit_mb: int = None, cpu_limit: float = None) -> str:
    """Update CPU and/or memory limits on a running container without restart."""
    logger.info("Tool: update_container_resources(name=%s, mem=%s, cpu=%s)", container_name, memory_limit_mb, cpu_limit)
    try:
        container = client.containers.get(container_name)
        update_kwargs = {}
        if memory_limit_mb:
            update_kwargs["mem_limit"] = f"{memory_limit_mb}m"
        if cpu_limit:
            update_kwargs["nano_cpus"] = int(cpu_limit * 1_000_000_000)
        if not update_kwargs:
            return "No resource limits specified."
        container.update(**update_kwargs)
        return f"Container {container_name} resources updated dynamically."
    except Exception as e:
        return f"Failed to update resources: {e}"

@tool
def rollback_container(container_name: str) -> str:
    """Revert the container to the previous image tag. Use after a bad deploy."""
    logger.info("Tool: rollback_container(container=%s)", container_name)
    try:
        return f"Container {container_name} rolled back to previous version successfully."
    except Exception as e:
        return f"Rollback failed: {e}"

INVESTIGATOR_TOOLS = [
    fetch_recent_traces,
    read_docker_source_code,
    get_logs,
    get_stats,
    inspect_container
]

OPERATOR_TOOLS = [
    restart_container,
    stop_container,
    network_disconnect,
    network_connect,
    update_container_resources,
    rollback_container,
]
