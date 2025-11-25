"""
Block sync implementation
"""
import re
import time
import hashlib
from typing import List, Dict, Optional, Tuple

from ...core.client import RemoteClient
from ...core.utils import resolve_remote_path
from ...core.logging import get_logger
from ...core.constants import GLOBAL_START_MARKER, GLOBAL_END_MARKER
from .models import BlockGroup, TextBlock
from .file_sync import ensure_remote_dir

logger = get_logger(__name__)

# Regular expression pattern for block markers
BLOCK_PATTERN = re.compile(
    r"(?ms)^# >>> remote-block:(?P<name>[^\n]+?) "
    r"src=(?P<src>.+?) "
    r"mtime=(?P<mtime>\d+) "
    r"hash=(?P<hash>[0-9a-f]+) <<<$"
    r"\n(?P<body>.*?)"
    r"^# <<< remote-block:(?P=name) <<<\s*$"
)


# ============================================================
# Helper Functions
# ============================================================

def _calc_hash(text: str) -> str:
    """Calculate SHA256 hash of text (first 16 characters)"""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _read_local_block(blk: TextBlock) -> Tuple[str, float]:
    """
    Read all src files of block, merge content, return merged content and maximum mtime.
    
    Returns:
        (merged_content, latest_mtime)
    """
    from pathlib import Path
    
    bodies = []
    latest_mtime = 0.0

    for src_path in blk.src:
        path = Path(src_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"Block source file not found: {src_path}")
        
        body = path.read_text()
        bodies.append(body.rstrip() + "\n")
        latest_mtime = max(latest_mtime, path.stat().st_mtime)

    merged = "".join(bodies)
    return merged, latest_mtime


def _parse_remote_blocks(remote_text: str) -> Dict[str, re.Match]:
    """
    Parse existing blocks in remote file.
    
    Returns:
        Dictionary: {block_name: match_object}
    """
    return {m.group("name"): m for m in BLOCK_PATTERN.finditer(remote_text)}


def _read_remote_file(client: RemoteClient, remote_path: str) -> str:
    """
    Read remote file content, return empty string if file doesn't exist.
    
    Returns:
        File content (ensured to end with newline)
    """
    sftp = client.open_sftp()
    try:
        with sftp.open(remote_path, "r") as f:
            content = f.read().decode()
    except IOError:
        content = ""
    
    if not content.endswith("\n"):
        content += "\n"
    
    return content


def _has_global_wrapper(text: str) -> bool:
    """Check if text contains global wrapper"""
    return GLOBAL_START_MARKER in text


def _strip_global_region(text: str) -> str:
    """Remove global wrapper region, preserve other content"""
    if not _has_global_wrapper(text):
        return text
    
    wrapper_pattern = re.compile(
        rf"(?ms){re.escape(GLOBAL_START_MARKER)}.*?{re.escape(GLOBAL_END_MARKER)}"
    )
    return wrapper_pattern.sub("", text).rstrip() + "\n"


# ============================================================
# Block Sync Logic
# ============================================================

class BlockSyncResult:
    """Block sync result"""
    def __init__(self):
        self.blocks_to_write: List[Tuple[str, List[str], float, str, str]] = []
        self.warnings: List[str] = []
    
    def add_block(self, name: str, src_list: List[str], mtime: float, 
                  hash_val: str, body: str):
        """Add block to write"""
        self.blocks_to_write.append((name, src_list, mtime, hash_val, body))
    
    def add_warning(self, warning: str):
        """Add warning message"""
        self.warnings.append(warning)
    
    def has_warnings(self) -> bool:
        """Check if there are warnings"""
        return len(self.warnings) > 0


def _should_update_block(
    blk: TextBlock,
    block_name: str,
    existed: bool,
    old_hash: Optional[str],
    old_mtime: Optional[float],
    new_hash: str,
    new_mtime: float,
    has_global: bool,
    force_init: bool = False
) -> Tuple[bool, Optional[str]]:
    """
    Determine if block should be updated.
    
    Returns:
        (should_update, warning_message)
    """
    # init mode: write only on first initialization (unless force_init)
    if blk.mode == "init":
        if force_init:
            # Force init mode: always update
            return True, None
        if has_global:
            return False, None
        return True, None
    
    # update mode: intelligent update
    if blk.mode == "update":
        if existed:
            # mtime not newer → no update needed
            if new_mtime <= old_mtime:
                return False, None
            
            # hash conflict → reject update
            if new_hash != old_hash:
                warning = f"""
[WARN] Block '{block_name}' was manually modified on the remote. Update is rejected!
Local hash:  {new_hash}
Remote hash: {old_hash}
Local mtime:  {time.ctime(new_mtime)}
Remote mtime: {time.ctime(old_mtime)}

If you want to overwrite, please set block.mode to 'cover' and try again.
"""
                return False, warning
        # Need to add or update
        return True, None
    
    # cover mode: force overwrite
    if blk.mode == "cover":
        return True, None
    
    raise ValueError(f"Unknown block mode: {blk.mode}")


def _process_blocks(
    group: BlockGroup,
    existing_blocks: Dict[str, re.Match],
    has_global: bool,
    force_init: bool = False
) -> BlockSyncResult:
    """
    Process all blocks, determine which need to be updated.
    
    Returns:
        BlockSyncResult object
    """
    result = BlockSyncResult()
    
    for blk in group.blocks:
        # Read local block content
        new_body, new_mtime = _read_local_block(blk)
        new_hash = _calc_hash(new_body)
        block_name = blk.get_name()
        
        # Check if exists
        existed = block_name in existing_blocks
        old_hash = None
        old_mtime = None
        
        if existed:
            m = existing_blocks[block_name]
            old_hash = m.group("hash")
            old_mtime = float(m.group("mtime"))
        
        # Determine if should update
        should_update, warning = _should_update_block(
            blk, block_name, existed, old_hash, old_mtime,
            new_hash, new_mtime, has_global, force_init=force_init
        )
        
        if warning:
            result.add_warning(warning)
        
        if should_update:
            result.add_block(block_name, blk.src, new_mtime, new_hash, new_body)
    
    return result


def _build_block_marker(name: str, src_list: List[str], mtime: float, 
                        hash_val: str) -> str:
    """Build block marker line"""
    src_str = ",".join(src_list)
    return f"# >>> remote-block:{name} src={src_str} mtime={int(mtime)} hash={hash_val} <<<"


def _build_global_region(
    group: BlockGroup,
    existing_blocks: Dict[str, re.Match],
    new_blocks: List[Tuple[str, List[str], float, str, str]],
    has_global: bool
) -> List[str]:
    """
    Build content of global wrapper region.
    
    Returns:
        List of lines
    """
    lines = [GLOBAL_START_MARKER]
    
    # Preserve existing blocks not in current configuration (incremental mode)
    if group.mode == "incremental" and has_global:
        current_block_names = {blk.get_name() for blk in group.blocks}
        for name, m in existing_blocks.items():
            if name not in current_block_names:
                src = m.group("src")
                mtime = m.group("mtime")
                hsh = m.group("hash")
                body = m.group("body")
                lines.append(_build_block_marker(name, [src], float(mtime), hsh))
                lines.append(body)
                lines.append(f"# <<< remote-block:{name} <<<")
    
    # Add new or updated blocks
    for name, src_list, mtime, hsh, body in new_blocks:
        lines.append(_build_block_marker(name, src_list, mtime, hsh))
        lines.append(body)
        lines.append(f"# <<< remote-block:{name} <<<")
    
    lines.append(GLOBAL_END_MARKER)
    return lines


def _write_remote_file(client: RemoteClient, remote_path: str, content: str):
    """Write content to remote file"""
    # Ensure remote directory exists
    ensure_remote_dir(client, remote_path)
    
    sftp = client.open_sftp()
    with sftp.open(remote_path, "w") as f:
        f.write(content)


def sync_block_groups(groups: List[BlockGroup], client: RemoteClient, force_init: bool = False) -> None:
    """
    Sync multiple BlockGroups to remote server.
    
    Args:
        groups: List of BlockGroup
        client: RemoteClient instance
        force_init: Force init mode (treat as first connection)
    
    Raises:
        RuntimeError: If sync fails due to remote modifications
    """
    from ...core.exceptions import BlockSyncError
    
    for group in groups:
        remote_path = resolve_remote_path(client, group.dist)
        
        # Step 1: Read remote file
        remote_text = _read_remote_file(client, remote_path)
        has_global = _has_global_wrapper(remote_text)
        
        # Step 2: Parse existing blocks
        existing_blocks = _parse_remote_blocks(remote_text)
        
        # Step 3: Process blocks
        result = _process_blocks(group, existing_blocks, has_global, force_init=force_init)
        
        # If there are warnings, raise exception
        if result.has_warnings():
            for warning in result.warnings:
                logger.warning(warning)
            raise BlockSyncError("Sync aborted due to remote modifications.")
        
        # Step 4: Build new content
        untouched = _strip_global_region(remote_text)
        global_lines = _build_global_region(
            group, existing_blocks, result.blocks_to_write, has_global
        )
        final_text = untouched + "\n".join(global_lines) + "\n"
        
        # Step 5: Write back to remote file
        _write_remote_file(client, remote_path, final_text)
        logger.debug(f"[block] Updated {remote_path}")

