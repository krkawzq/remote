from pathlib import Path
from dataclasses import dataclass
from typing import Literal, Optional

from ..client import RemoteClient
from ..utils import (
    is_remote_path,
    resolve_local_path,
    resolve_remote_path,
    log_info,
)


@dataclass
class FileSync:
    src: str
    dist: str
    mode: Literal["cover", "sync", "update", "init"]


# ============================================================
# Remote FS Helpers
# ============================================================

def remote_exists(client: RemoteClient, path: str) -> bool:
    """Check if remote file exists"""
    try:
        sftp = client.open_sftp()
        sftp.stat(path)
        return True
    except IOError:
        return False


def remote_mtime(client: RemoteClient, path: str) -> Optional[float]:
    """Get modification time of remote file"""
    try:
        sftp = client.open_sftp()
        return sftp.stat(path).st_mtime
    except IOError:
        return None


# ============================================================
# Copy helpers
# ============================================================

def ensure_remote_dir(client: RemoteClient, remote_path: str) -> None:
    """
    Ensure remote directory exists, create if it doesn't (similar to mkdir -p).
    
    Args:
        client: RemoteClient instance
        remote_path: Remote file path
    """
    import os
    sftp = client.open_sftp()
    
    # Get parent directory
    dir_path = os.path.dirname(remote_path)
    if not dir_path or dir_path == "/":
        return  # Root directory or no parent directory
    
    # Recursively create directories
    parts = dir_path.split("/")
    current_path = ""
    for part in parts:
        if not part:
            continue
        current_path = current_path + "/" + part if current_path else "/" + part
        try:
            sftp.stat(current_path)
        except IOError:
            # Directory doesn't exist, create it
            try:
                sftp.mkdir(current_path)
            except IOError:
                # May have been created by another process, ignore error
                pass


def put_file(client: RemoteClient, local: Path, remote: str) -> None:
    """Upload local file to remote, auto-create directory if it doesn't exist"""
    # Ensure remote directory exists
    ensure_remote_dir(client, remote)
    
    sftp = client.open_sftp()
    sftp.put(local.as_posix(), remote)
    log_info(f"[push] {local} → {remote}")


def get_file(client: RemoteClient, remote: str, local: Path) -> None:
    """Download file from remote to local"""
    sftp = client.open_sftp()
    local.parent.mkdir(parents=True, exist_ok=True)
    sftp.get(remote, local.as_posix())
    log_info(f"[pull] {remote} → {local}")


# ============================================================
# File Sync Logic
# ============================================================

def sync_files(files: list[FileSync], client: RemoteClient) -> None:
    """Sync multiple files"""
    for f in files:
        _sync_one_file(f, client)


def _sync_one_file(f: FileSync, client: RemoteClient) -> None:
    """Sync a single file"""
    src_is_remote = is_remote_path(f.src)
    dist_is_remote = is_remote_path(f.dist)

    # resolve paths
    if src_is_remote:
        src = resolve_remote_path(client, f.src)
    else:
        src = resolve_local_path(f.src)

    if dist_is_remote:
        dist = resolve_remote_path(client, f.dist)
    else:
        dist = resolve_local_path(f.dist)

    # ============================================================
    #  INIT MODE
    # ============================================================
    if f.mode == "init":
        # only push if target does NOT exist
        if dist_is_remote:
            if remote_exists(client, dist):
                return
            put_file(client, src, dist)
        else:
            if Path(dist).exists():
                return
            get_file(client, src, dist)
        return

    # ============================================================
    #  COVER MODE
    # ============================================================
    if f.mode == "cover":
        if src_is_remote:
            get_file(client, src, dist)
        else:
            put_file(client, src, dist)
        return

    # ============================================================
    #  SYNC MODE (bidirectional)
    # ============================================================
    if f.mode == "sync":
        local_mtime = Path(src).stat().st_mtime if not src_is_remote else None
        remote_mtime_val = remote_mtime(client, src) if src_is_remote else None

        if not src_is_remote and dist_is_remote:
            # src = local, dist = remote
            lm = Path(src).stat().st_mtime
            rm = remote_mtime(client, dist)

            if rm is None or lm > rm:
                put_file(client, src, dist)
            elif rm > lm:
                get_file(client, dist, src)

        elif src_is_remote and not dist_is_remote:
            # src = remote, dist = local
            rm = remote_mtime(client, src)
            lm = Path(dist).stat().st_mtime if Path(dist).exists() else None

            if lm is None or rm > lm:
                get_file(client, src, dist)
            elif lm > rm:
                put_file(client, dist, src)

        return

    # ============================================================
    #  UPDATE MODE (one-direction: local -> remote)
    # ============================================================
    if f.mode == "update":
        if src_is_remote and dist_is_remote:
            raise RuntimeError("update mode cannot be remote→remote")

        if not src_is_remote and dist_is_remote:
            # push if local newer
            lm = Path(src).stat().st_mtime
            rm = remote_mtime(client, dist)
            if rm is None or lm > rm:
                put_file(client, src, dist)
            return

        if src_is_remote and not dist_is_remote:
            # pull if remote newer
            rm = remote_mtime(client, src)
            lm = Path(dist).stat().st_mtime if Path(dist).exists() else None
            if lm is None or rm > lm:
                get_file(client, src, dist)
            return

    # fallback—should never get here
    raise RuntimeError(f"Unknown mode: {f.mode}")
