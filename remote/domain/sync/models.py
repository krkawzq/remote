"""
Sync domain models
"""
from dataclasses import dataclass
from typing import Literal, Optional, List


@dataclass
class FileSync:
    """File sync configuration"""
    src: str
    dist: str
    mode: Literal["cover", "sync", "update", "init"]


@dataclass
class TextBlock:
    """
    Single block, corresponding to multiple src files (modules).
    Each block has its own update mode:
    - init: Write only on first initialization
    - update: Intelligently update based on mtime and hash
    - cover: Force overwrite
    """
    src: List[str]
    mode: Literal["init", "update", "cover"]
    
    def get_name(self) -> str:
        """Generate block identifier from src file path"""
        if not self.src:
            raise ValueError("TextBlock must have at least one src file")
        from pathlib import Path
        return str(Path(self.src[0]).expanduser().resolve())


@dataclass
class BlockGroup:
    """
    A dist file contains multiple blocks, belonging to the same group.
    mode:
    - incremental: Preserve unknown blocks (blocks not in configuration)
    - overwrite: Completely rebuild remote region (delete unknown blocks)
    """
    dist: str
    mode: Literal["incremental", "overwrite"]
    blocks: List[TextBlock]


@dataclass
class GlobalEnv:
    """Global interpreter environment configuration"""
    interpreter: str = "/bin/bash"
    flags: Optional[List[str]] = None


@dataclass
class ScriptExec:
    """
    Single script execution unit
    
    Attributes:
        src: Local script path or remote script path (":path" format)
        mode: Execution timing - "init" (first connection only) or "always" (every time)
        exec_mode: Execution method - "exec" (direct execution) or "source" (source mode)
        interpreter: Interpreter path (optional, ignored in source mode)
        flags: Interpreter flags (optional)
        args: Script arguments (optional)
        interactive: Whether interactive mode is required
        allow_fail: Whether non-zero exit codes are allowed
    """
    src: str
    mode: Literal["init", "always"] = "always"
    exec_mode: Literal["exec", "source"] = "exec"
    
    interpreter: Optional[str] = None
    flags: Optional[List[str]] = None
    args: Optional[List[str]] = None
    
    interactive: bool = False
    allow_fail: bool = False

