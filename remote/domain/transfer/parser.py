"""
SCP-style path parser
"""
import re
from typing import Optional
from pathlib import Path

from ...core.utils import load_ssh_config
from ...core.exceptions import ConfigError, TransferError
from .models import Endpoint


def parse_scp_path(path: str, default_port: int = 22) -> Endpoint:
    """
    Parse SCP-style path into Endpoint.
    
    Supports formats:
    - local-path (no colon)
    - user@host:path
    - host:path
    - host:/abs/path
    - host:~/file
    
    Args:
        path: Path string to parse
        default_port: Default SSH port if not specified
    
    Returns:
        Endpoint object
    
    Raises:
        TransferError: If path format is invalid
    """
    # Check if it's a local path (no colon)
    if ":" not in path:
        return Endpoint(
            path=str(Path(path).expanduser()),
            is_local=True,
        )
    
    # Remote path - parse user@host:path format
    # Pattern: [user@]host[:port]:path
    # Note: port is not standard scp format, but we support it for flexibility
    
    # Try to match user@host:path or host:path
    # Split by first colon
    parts = path.split(":", 1)
    if len(parts) != 2:
        raise TransferError(f"Invalid remote path format: {path}")
    
    host_part = parts[0]
    remote_path = parts[1]
    
    # Parse host part (may contain user@host or just host)
    if "@" in host_part:
        user, host = host_part.rsplit("@", 1)
    else:
        user = None
        host = host_part
    
    # Try to load SSH config for this host
    ssh_config = None
    try:
        ssh_config = load_ssh_config(host)
    except ConfigError:
        # SSH config not found, use defaults
        pass
    
    # Use SSH config values if available
    if ssh_config:
        resolved_host = ssh_config.get("host", host)
        resolved_user = ssh_config.get("user") or user
        resolved_port = int(ssh_config.get("port", default_port))
        key_file = ssh_config.get("key_file")
    else:
        resolved_host = host
        resolved_user = user
        resolved_port = default_port
        key_file = None
    
    # Resolve remote path (expand ~ if needed)
    if remote_path.startswith("~"):
        # Will be resolved later when we have SSH connection
        resolved_path = remote_path
    elif remote_path.startswith("/"):
        resolved_path = remote_path
    else:
        # Relative path
        resolved_path = remote_path
    
    return Endpoint(
        host=resolved_host,
        user=resolved_user,
        port=resolved_port,
        path=resolved_path,
        is_local=False,
        key_file=key_file,
    )


def resolve_remote_path(client, endpoint: Endpoint) -> str:
    """
    Resolve remote path, expanding ~ to actual home directory.
    
    Args:
        client: RemoteClient instance
        endpoint: Endpoint with remote path
    
    Returns:
        Resolved absolute path
    """
    if endpoint.is_local:
        return endpoint.path
    
    path = endpoint.path
    
    # Expand ~ to home directory
    if path.startswith("~"):
        stdout, _ = client.exec("printf $HOME")
        home = stdout.strip() or "/root"
        if path == "~":
            return home
        return home + path[1:]  # Remove ~
    
    # If relative path, resolve relative to home
    if not path.startswith("/"):
        stdout, _ = client.exec("pwd")
        cwd = stdout.strip() or "/"
        if path == "":
            return cwd
        return f"{cwd}/{path}" if cwd != "/" else f"/{path}"
    
    return path


def generate_manifest_key(src: Endpoint, dst: Endpoint) -> str:
    """
    Generate manifest key from src and dst endpoints.
    
    Uses SHA256 hash of normalized endpoint strings.
    
    Args:
        src: Source endpoint
        dst: Destination endpoint
    
    Returns:
        SHA256 hash string (hex)
    """
    import hashlib
    
    # Normalize endpoints for consistent hashing
    src_str = f"{src.host}:{src.user}:{src.port}:{src.path}"
    dst_str = f"{dst.host}:{dst.user}:{dst.port}:{dst.path}"
    combined = f"{src_str}|{dst_str}"
    
    return hashlib.sha256(combined.encode()).hexdigest()

