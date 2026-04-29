
import logging
from api.services.sandbox import docker

logger = logging.getLogger(__name__)

async def create_sandbox() -> str:
    """Initialize a fresh Docker container for the repair session."""
    container = await docker.create_container()
    return container.id

async def destroy_sandbox(container_id: str) -> None:
    """Stop and remove the specified container."""
    try:
        client = docker._get_client()
        container = client.containers.get(container_id)
        await docker.destroy(container)
    except Exception as e:
        logger.warning(f"Failed to destroy container {container_id}: {e}")

def get_container(container_id: str):
    """Resolve a container ID to a Docker SDK object."""
    client = docker._get_client()
    return client.containers.get(container_id)
