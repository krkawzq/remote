"""
Transfer data models v2.0

重新设计的数据模型，更清晰、更完整
"""
import time
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ChunkStatus(str, Enum):
    """Chunk status"""
    PENDING = "pending"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    COMPLETED = "completed"
    VERIFIED = "verified"
    FAILED = "failed"


class TransferDirection(str, Enum):
    """传输方向"""
    DOWNLOAD = "download"  # remote → local
    UPLOAD = "upload"      # local → remote


@dataclass
class TransferConfig:
    """Transfer configuration"""
    # 传输控制
    resume: bool = True
    force: bool = False
    parallel: int = 4
    aria2: bool = False
    split: int = 32  # Number of chunks in aria2 mode
    chunk: int = 4 * 1024 * 1024  # 4MB default
    
    # 高级选项
    preserve_permissions: bool = False
    compress: bool = False
    limit_rate: Optional[int] = None  # bytes per second
    
    # 连接设置
    ssh_port: int = 22
    timeout: int = 30
    
    # 重试策略
    max_retries: int = 3
    retry_delay: float = 1.0
    
    # 日志和显示
    verbose: bool = False
    quiet: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "resume": self.resume,
            "force": self.force,
            "parallel": self.parallel,
            "aria2": self.aria2,
            "split": self.split,
            "chunk": self.chunk,
            "preserve_permissions": self.preserve_permissions,
            "verbose": self.verbose,
            "quiet": self.quiet,
            "compress": self.compress,
            "limit_rate": self.limit_rate,
            "ssh_port": self.ssh_port,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "retry_delay": self.retry_delay,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TransferConfig":
        """Create from dictionary"""
        # 只使用存在于类定义中的字段
        valid_fields = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid_fields)


@dataclass
class Endpoint:
    """Path endpoint (local or remote)"""
    path: str = ""
    is_local: bool = True
    host: Optional[str] = None
    user: Optional[str] = None
    port: int = 22
    key_file: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "path": self.path,
            "is_local": self.is_local,
            "host": self.host,
            "user": self.user,
            "port": self.port,
            "key_file": self.key_file,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Endpoint":
        """Create from dictionary"""
        return cls(**data)
    
    def __str__(self) -> str:
        """String representation"""
        if self.is_local:
            return self.path
        if self.user:
            return f"{self.user}@{self.host}:{self.path}"
        return f"{self.host}:{self.path}"
    
    def get_display_name(self) -> str:
        """Get display name"""
        if self.is_local:
            return f"local:{self.path}"
        return f"{self.host}:{self.path}"


@dataclass
class Chunk:
    """File chunk information"""
    index: int
    offset: int
    size: int
    status: ChunkStatus = ChunkStatus.PENDING
    sha1: Optional[str] = None
    sha256: Optional[str] = None
    attempts: int = 0
    error: Optional[str] = None
    downloaded_bytes: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "index": self.index,
            "offset": self.offset,
            "size": self.size,
            "status": self.status.value,
            "sha1": self.sha1,
            "sha256": self.sha256,
            "attempts": self.attempts,
            "error": self.error,
            "downloaded_bytes": self.downloaded_bytes,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Chunk":
        """Create from dictionary"""
        # 兼容旧格式
        status_str = data.get("status", "pending")
        if status_str == "downloaded":
            status_str = "completed"
        
        return cls(
            index=data["index"],
            offset=data["offset"],
            size=data["size"],
            status=ChunkStatus(status_str),
            sha1=data.get("sha1"),
            sha256=data.get("sha256"),
            attempts=data.get("attempts", 0),
            error=data.get("error"),
            downloaded_bytes=data.get("downloaded_bytes", data["size"] if status_str in ("completed", "verified") else 0),
        )
    
    def is_complete(self) -> bool:
        """Check if chunk is complete"""
        return self.status in (ChunkStatus.COMPLETED, ChunkStatus.VERIFIED)
    
    def should_retry(self, max_retries: int) -> bool:
        """Check if should retry"""
        return self.status == ChunkStatus.FAILED and self.attempts < max_retries


@dataclass
class Manifest:
    """Transfer manifest for resume support"""
    version: str = "2.0"
    src: Optional[Endpoint] = None
    dst: Optional[Endpoint] = None
    size: int = 0
    mtime: float = 0.0
    chunks: List[Chunk] = field(default_factory=list)
    config: Optional[TransferConfig] = None
    
    # v2 新增字段
    file_hash: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "version": self.version,
            "src": self.src.to_dict() if self.src else None,
            "dst": self.dst.to_dict() if self.dst else None,
            "size": self.size,
            "mtime": self.mtime,
            "chunks": [chunk.to_dict() for chunk in self.chunks],
            "config": self.config.to_dict() if self.config else None,
            "file_hash": self.file_hash,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Manifest":
        """Create from dictionary"""
        version = data.get("version", "1.0")
        return cls(
            version=version,
            src=Endpoint.from_dict(data["src"]) if data.get("src") else None,
            dst=Endpoint.from_dict(data["dst"]) if data.get("dst") else None,
            size=data.get("size", 0),
            mtime=data.get("mtime", 0.0),
            chunks=[Chunk.from_dict(c) for c in data.get("chunks", [])],
            config=TransferConfig.from_dict(data["config"]) if data.get("config") else None,
            file_hash=data.get("file_hash"),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )
    
    def get_pending_chunks(self) -> List[Chunk]:
        """Get pending chunks"""
        return [c for c in self.chunks if not c.is_complete()]
    
    def get_completed_chunks(self) -> List[Chunk]:
        """Get completed chunks"""
        return [c for c in self.chunks if c.is_complete()]
    
    def get_failed_chunks(self) -> List[Chunk]:
        """Get failed chunks"""
        return [c for c in self.chunks if c.status == ChunkStatus.FAILED]
    
    def calculate_progress(self) -> tuple[int, int]:
        """Calculate progress (completed_bytes, total_bytes)"""
        completed = sum(c.size for c in self.chunks if c.is_complete())
        total = sum(c.size for c in self.chunks)
        return (completed, total)
    
    def is_complete(self) -> bool:
        """Check if all chunks are complete"""
        return len(self.chunks) > 0 and all(c.is_complete() for c in self.chunks)


@dataclass
class TransferResult:
    """Transfer result"""
    success: bool
    bytes_transferred: int
    total_bytes: int
    duration: float
    average_speed: float  # bytes/s
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "success": self.success,
            "bytes_transferred": self.bytes_transferred,
            "total_bytes": self.total_bytes,
            "duration": self.duration,
            "average_speed": self.average_speed,
            "error": self.error,
        }

