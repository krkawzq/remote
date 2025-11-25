"""
Path resolver for connect module

Handles parsing and resolving paths with : prefix for remote paths
"""
import os
from pathlib import Path
from typing import Optional

from .models import PathSpec, ConnectSession
from ....core.client import RemoteClient


def parse_path(path: str, session: ConnectSession) -> PathSpec:
    """
    Parse a path string into PathSpec.
    
    Rules:
    - ":path" or ":~/path" → remote path
    - "path" or "~/path" → local path
    
    Args:
        path: Path string (may start with :)
        session: Connect session for context
    
    Returns:
        PathSpec object
    """
    is_remote = path.startswith(":")
    prefix_stripped = path[1:] if is_remote else path
    
    if is_remote:
        resolved = resolve_remote_path(prefix_stripped, session.client, session.remote_cwd)
    else:
        resolved = resolve_local_path(prefix_stripped, session.local_cwd)
    
    return PathSpec(
        original=path,
        is_remote=is_remote,
        prefix_stripped=prefix_stripped,
        resolved=resolved,
    )


def resolve_local_path(path: str, cwd: Path) -> str:
    """
    Resolve local path to absolute path.
    
    Args:
        path: Path string (may be relative)
        cwd: Current working directory
    
    Returns:
        Absolute path string
    """
    # Expand ~
    expanded = os.path.expanduser(path)
    
    # Resolve relative to cwd if relative
    if os.path.isabs(expanded):
        return expanded
    else:
        return str((cwd / expanded).resolve())


def resolve_remote_path(path: str, client: RemoteClient, cwd: str) -> str:
    """
    Resolve remote path to absolute path.
    
    Uses remote shell to resolve path (handles ~, relative paths, symlinks).
    
    Args:
        path: Path string (may be relative)
        client: RemoteClient instance
        cwd: Remote current working directory
    
    Returns:
        Absolute path string
    """
    # Try to resolve using Python on remote
    # This handles ~ expansion, relative paths, and symlinks
    python_cmd = f'''python3 -c "import os; print(os.path.abspath(os.path.expanduser('{path}')))"'''
    
    try:
        stdout, stderr = client.exec(python_cmd)
        if stdout.strip():
            return stdout.strip()
    except Exception:
        pass
    
    # Fallback: try with cd and pwd
    try:
        # If path is relative, resolve relative to cwd
        if not path.startswith("/") and not path.startswith("~"):
            # Combine cwd and path
            combined = f"{cwd.rstrip('/')}/{path.lstrip('/')}"
            python_cmd = f'''python3 -c "import os; print(os.path.abspath(os.path.expanduser('{combined}')))"'''
            stdout, stderr = client.exec(python_cmd)
            if stdout.strip():
                return stdout.strip()
        else:
            # Absolute path or ~, use as-is after expansion
            python_cmd = f'''python3 -c "import os; print(os.path.abspath(os.path.expanduser('{path}')))"'''
            stdout, stderr = client.exec(python_cmd)
            if stdout.strip():
                return stdout.strip()
    except Exception:
        pass
    
    # Final fallback: return path as-is (may not be absolute)
    return path


def normalize_path(path: str, is_remote: bool, session: ConnectSession) -> str:
    """
    Normalize a path (resolve to absolute).
    
    Args:
        path: Path string
        is_remote: Whether path is remote
        session: Connect session
    
    Returns:
        Normalized absolute path
    """
    if is_remote:
        return resolve_remote_path(path, session.client, session.remote_cwd)
    else:
        return resolve_local_path(path, session.local_cwd)

