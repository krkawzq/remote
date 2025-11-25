"""
Manifest management for transfer resume
"""
from typing import Optional
from pathlib import Path

from ...core.client import RemoteClient
from ...core.exceptions import TransferError
from .models import Manifest, Endpoint, TransferConfig
from .parser import resolve_remote_path


def get_local_file_info(path: Path) -> tuple[int, float]:
    """
    Get local file size and mtime.
    
    Args:
        path: Local file path
    
    Returns:
        (size, mtime) tuple
    """
    if not path.exists():
        return (0, 0.0)
    stat = path.stat()
    return (stat.st_size, stat.st_mtime)


def get_remote_file_info(client: RemoteClient, path: str) -> tuple[int, float]:
    """
    Get remote file size and mtime.
    
    Args:
        client: RemoteClient instance
        path: Remote file path
    
    Returns:
        (size, mtime) tuple
    
    Raises:
        TransferError: If file doesn't exist
    """
    try:
        sftp = client.open_sftp()
        stat = sftp.stat(path)
        return (stat.st_size, stat.st_mtime)
    except IOError as e:
        raise TransferError(f"Remote file not found: {path}") from e


def validate_manifest(
    manifest: Manifest,
    src_endpoint: Endpoint,
    dst_endpoint: Endpoint,
    src_client: Optional[RemoteClient] = None,
    dst_client: Optional[RemoteClient] = None,
) -> bool:
    """
    Validate manifest against actual source file.
    
    Checks if source file size and mtime match manifest.
    If mismatch, manifest is considered invalid.
    
    Args:
        manifest: Manifest to validate
        src_endpoint: Source endpoint
        dst_endpoint: Destination endpoint
        src_client: Source client (if remote)
        dst_client: Destination client (if remote)
    
    Returns:
        True if manifest is valid, False otherwise
    """
    # Check endpoints match
    if manifest.src and manifest.dst:
        if manifest.src.path != src_endpoint.path or manifest.dst.path != dst_endpoint.path:
            return False
    
    # Get source file info
    if src_endpoint.is_local:
        size, mtime = get_local_file_info(Path(src_endpoint.path))
    else:
        if not src_client:
            return False
        try:
            size, mtime = get_remote_file_info(src_client, src_endpoint.path)
        except TransferError:
            return False
    
    # Compare with manifest
    if manifest.size != size:
        return False
    
    # Allow small mtime difference (1 second) for filesystem precision
    if abs(manifest.mtime - mtime) > 1.0:
        return False
    
    return True


def create_manifest(
    src_endpoint: Endpoint,
    dst_endpoint: Endpoint,
    size: int,
    mtime: float,
    config: TransferConfig,
    chunks: Optional[list] = None,
) -> Manifest:
    """
    Create a new manifest.
    
    Args:
        src_endpoint: Source endpoint
        dst_endpoint: Destination endpoint
        size: File size
        mtime: File modification time
        config: Transfer configuration
        chunks: Optional list of chunks (will be created if None)
    
    Returns:
        Manifest object
    """
    return Manifest(
        version="1.0",
        src=src_endpoint,
        dst=dst_endpoint,
        size=size,
        mtime=mtime,
        chunks=chunks or [],
        config=config,
    )

