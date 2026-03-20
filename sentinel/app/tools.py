"""Docker SDK tools for container introspection and control."""
import logging
import re
import json
import urllib.request
import urllib.parse

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


def inspect_container(container_name: str) -> dict:
    """Gets full container configuration (env, mounts, ports, network, image, etc.)."""
    logger.info("Tool: inspect_container(container=%s)", container_name)
    container = client.containers.get(container_name)
    return container.attrs


def network_disconnect(container_name: str, network_name: str = None) -> str:
    """Disconnect container from a network. Network isolation for containment."""
    logger.info("Tool: network_disconnect(container=%s, network=%s)", container_name, network_name)
    container = client.containers.get(container_name)
    if not network_name:
        networks = container.attrs.get("NetworkSettings", {}).get("Networks", {})
        if not networks:
            return f"Container {container_name} has no networks to disconnect."
        network_name = list(networks.keys())[0]
    try:
        container.disconnect(network=network_name)
        return f"Container {container_name} disconnected from network {network_name}."
    except docker.errors.APIError as e:
        return f"Failed to disconnect: {e}"


def network_connect(container_name: str, network_name: str) -> str:
    """Reconnect container to a network."""
    logger.info("Tool: network_connect(container=%s, network=%s)", container_name, network_name)
    container = client.containers.get(container_name)
    try:
        container.connect(network=network_name)
        return f"Container {container_name} connected to network {network_name}."
    except docker.errors.APIError as e:
        return f"Failed to connect: {e}"


def update_container_resources(container_name: str, memory_limit_mb: int = None, cpu_limit: float = None) -> str:
    """Update CPU and/or memory limits on a running container. Dynamic resource scaling."""
    logger.info("Tool: update_container_resources(container=%s, memory=%s, cpu=%s)", container_name, memory_limit_mb, cpu_limit)
    container = client.containers.get(container_name)
    update_kwargs = {}
    if memory_limit_mb:
        update_kwargs["mem_limit"] = f"{memory_limit_mb}m"
    if cpu_limit:
        update_kwargs["nano_cpus"] = int(cpu_limit * 1_000_000_000)
    if not update_kwargs:
        return "No resource limits specified."
    try:
        container.update(**update_kwargs)
        parts = []
        if memory_limit_mb:
            parts.append(f"memory={memory_limit_mb}MB")
        if cpu_limit:
            parts.append(f"CPU={cpu_limit}")
        return f"Container {container_name} resources updated: {', '.join(parts)}."
    except docker.errors.APIError as e:
        return f"Failed to update resources: {e}"


def rollback_container(container_name: str) -> str:
    """Revert container to previous image tag. Rollback to last known good version."""
    logger.info("Tool: rollback_container(container=%s)", container_name)
    container = client.containers.get(container_name)
    current_image = container.image.tags[0] if container.image.tags else container.image.id
    logger.info("Current image: %s", current_image)
    attrs = container.attrs
    config = container.attrs.get("Config", {})
    host_config = container.attrs.get("HostConfig", {})
    network_settings = container.attrs.get("NetworkSettings", {})
    networks = network_settings.get("Networks", {})
    env = config.get("Env", [])
    ports = config.get("ExposedPorts", {})
    volumes = host_config.get("Binds", [])
    restart_policy = host_config.get("RestartPolicy", {})
    mem_limit = host_config.get("Memory", 0)
    cpu_quota = host_config.get("CpuQuota", 0)
    cpu_period = host_config.get("CpuPeriod", 0)
    cpu_limit = cpu_quota / cpu_period if cpu_period else None
    try:
        if ":" in current_image:
            repo, tag = current_image.rsplit(":", 1)
            if tag.isdigit():
                prev_tag = str(int(tag) - 1)
            elif tag == "latest":
                prev_tag = "prev"
            else:
                prev_tag = "prev"
            prev_image = f"{repo}:{prev_tag}"
        else:
            prev_image = f"{current_image}:prev"
        logger.info("Attempting rollback to: %s", prev_image)
        try:
            client.images.get(prev_image)
        except docker.errors.ImageNotFound:
            return f"Previous image {prev_image} not found. Cannot rollback."
        container.stop()
        container.remove()
        port_bindings = {}
        if ports:
            for port in ports.keys():
                port_num = int(port.split("/")[0])
                port_bindings[port] = (None, port_num)
        create_kwargs = {
            "image": prev_image,
            "environment": env,
            "detach": True,
            "name": container_name,
            "ports": port_bindings,
            "restart_policy": restart_policy,
            "mem_limit": mem_limit if mem_limit else None,
        }
        if cpu_limit:
            create_kwargs["nano_cpus"] = int(cpu_limit * 1_000_000_000)
        if volumes:
            create_kwargs["volumes"] = volumes
        new_container = client.containers.run(**create_kwargs)
        for net_name in networks.keys():
            try:
                new_container.connect(network=net_name)
            except Exception as e:
                logger.warning("Failed to reconnect to network %s: %s", net_name, e)
        return f"Container {container_name} rolled back to {prev_image}."
    except Exception as e:
        logger.exception("Rollback failed")
        return f"Rollback failed: {e}"


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
            
            # Format span data to show hierarchy and duration
            for span in spans:
                duration_ms = span.get("duration", 0) / 1000.0
                op_name = span.get("operationName", "unknown")
                tags = {tg["key"]: tg["value"] for tg in span.get("tags", [])}
                
                # We only log spans that are somewhat significant or have errors to save context length
                if duration_ms > 10 or tags.get("error"):
                    err_str = " [ERROR]" if tags.get("error") else ""
                    traces_info.append(f"  - Span: {op_name}{err_str} | Duration: {duration_ms}ms | Tags: {tags}")
            
        return "\n".join(traces_info)[:4000] # Limit to avoid context bloat
    except Exception as e:
        return f"Failed to fetch traces: {e}"


def read_docker_source_code(container_name: str, file_path: str, start_line: int, end_line: int) -> str:
    """Reads specific lines from a file inside a running docker container. Use this to read the problematic application code."""
    logger.info("Tool: read_docker_source_code(container=%s, file=%s)", container_name, file_path)
    try:
        container = client.containers.get(container_name)
        # Using sed to extract specific line ranges: sed -n '1,100p' filename
        cmd = ["sed", "-n", f"{start_line},{end_line}p", file_path]
        exit_code, output = container.exec_run(cmd)
        if exit_code != 0:
            return f"Failed to read file: exit code {exit_code}. Output: {output.decode('utf-8')}"
        
        # Add line numbers out of courtesy for the AI
        lines = output.decode("utf-8").splitlines()
        numbered_lines = [f"{start_line + i}: {line}" for i, line in enumerate(lines)]
        return "\n".join(numbered_lines)
    except Exception as e:
        return f"Failed to read source code: {e}"

