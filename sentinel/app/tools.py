"""Docker SDK tools for container introspection and control."""
import docker

client = docker.from_env()


def get_logs(container_name: str) -> str:
    """Reads stdout from the container."""
    container = client.containers.get(container_name)
    return container.logs(tail=50).decode("utf-8")


def restart_container(container_name: str) -> str:
    """Kills and restarts the container."""
    container = client.containers.get(container_name)
    container.restart()
    return f"Container {container_name} restarted successfully."


def get_stats(container_name: str) -> dict:
    """Gets real-time container stats (CPU, memory, etc.)."""
    container = client.containers.get(container_name)
    return container.stats(stream=False)
