"""
Connect domain models
"""
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Any, List

from ....core.client import RemoteClient
from ..models import TransferConfig


@dataclass
class PathSpec:
    """Path specification with remote/local distinction"""
    original: str  # Original input, e.g., ":~/file.txt"
    is_remote: bool  # Whether this is a remote path
    prefix_stripped: str  # Path with : prefix removed, e.g., "~/file.txt"
    resolved: str  # Resolved absolute path
    
    def __str__(self) -> str:
        """String representation"""
        return self.original
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "original": self.original,
            "is_remote": self.is_remote,
            "prefix_stripped": self.prefix_stripped,
            "resolved": self.resolved,
        }


@dataclass
class ConnectConfig:
    """Connect session configuration"""
    # Transfer thresholds
    large_file_threshold: int = 100 * 1024 * 1024  # 100MB default
    
    # Transfer settings (delegated to TransferConfig)
    transfer_config: TransferConfig = field(default_factory=lambda: TransferConfig())
    
    # Session settings
    timeout: int = 30
    keep_alive: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "large_file_threshold": self.large_file_threshold,
            "transfer_config": self.transfer_config.to_dict(),
            "timeout": self.timeout,
            "keep_alive": self.keep_alive,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConnectConfig":
        """Create from dictionary"""
        transfer_config_data = data.get("transfer_config", {})
        return cls(
            large_file_threshold=data.get("large_file_threshold", 100 * 1024 * 1024),
            transfer_config=TransferConfig.from_dict(transfer_config_data),
            timeout=data.get("timeout", 30),
            keep_alive=data.get("keep_alive", True),
        )


@dataclass
class ConnectSession:
    """Connect session state"""
    # Connection info
    host: str
    user: str
    port: int
    client: RemoteClient
    
    # Working directories
    local_cwd: Path
    remote_cwd: str
    
    # Configuration
    config: ConnectConfig
    
    # Statistics
    bytes_transferred: int = 0
    commands_executed: int = 0
    start_time: float = field(default_factory=time.time)
    
    # Context tracking
    last_cd_was_remote: bool = False  # Track if last cd was remote
    
    def update_cwd(self, is_remote: bool, new_cwd: str) -> None:
        """Update current working directory"""
        if is_remote:
            self.remote_cwd = new_cwd
            self.last_cd_was_remote = True
        else:
            self.local_cwd = Path(new_cwd)
            self.last_cd_was_remote = False
    
    def get_cwd(self, is_remote: bool) -> str:
        """Get current working directory"""
        if is_remote:
            return self.remote_cwd
        return str(self.local_cwd)
    
    def get_default_path(self) -> str:
        """Get default path based on last cd context"""
        if self.last_cd_was_remote:
            return ":."
        return "."
    
    def add_transferred_bytes(self, bytes_count: int) -> None:
        """Add to transferred bytes counter"""
        self.bytes_transferred += bytes_count
    
    def increment_command_count(self) -> None:
        """Increment command counter"""
        self.commands_executed += 1
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "host": self.host,
            "user": self.user,
            "port": self.port,
            "local_cwd": str(self.local_cwd),
            "remote_cwd": self.remote_cwd,
            "config": self.config.to_dict(),
            "bytes_transferred": self.bytes_transferred,
            "commands_executed": self.commands_executed,
            "start_time": self.start_time,
        }


@dataclass
class CommandResult:
    """Command execution result"""
    exit_code: int
    stdout: str
    stderr: str
    success: bool = True
    
    def __post_init__(self):
        """Set success based on exit_code"""
        self.success = self.exit_code == 0
    
    def __str__(self) -> str:
        """String representation"""
        if self.success:
            return self.stdout
        return f"Error (exit code {self.exit_code}): {self.stderr}"


@dataclass
class PathInfo:
    """Path information for command parsing"""
    original: str
    has_colon_prefix: bool
    is_remote: bool
    resolved_path: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "original": self.original,
            "has_colon_prefix": self.has_colon_prefix,
            "is_remote": self.is_remote,
            "resolved_path": self.resolved_path,
        }


@dataclass
class ParsedCommand:
    """Parsed command structure"""
    name: str
    options: List[str]
    args: List[str]
    paths: Dict[int, PathInfo]
    is_remote: bool
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "name": self.name,
            "options": self.options,
            "args": self.args,
            "paths": {str(k): v.to_dict() for k, v in self.paths.items()},
            "is_remote": self.is_remote,
        }

