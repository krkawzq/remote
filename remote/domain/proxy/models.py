"""
Proxy domain models
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
import time


@dataclass
class ProxyConfig:
    """Proxy configuration"""
    local_port: int
    remote_port: int
    mode: str = "http"  # http or socks5
    local_host: str = "localhost"
    tags: Dict[str, str] = field(default_factory=dict)
    
    def validate(self) -> None:
        """Validate configuration"""
        from ...core.exceptions import ProxyError
        
        if not (1 <= self.local_port <= 65535):
            raise ProxyError(f"Invalid local_port: {self.local_port}")
        if not (1 <= self.remote_port <= 65535):
            raise ProxyError(f"Invalid remote_port: {self.remote_port}")
        if self.mode not in ("http", "socks5"):
            raise ProxyError(f"Invalid mode: {self.mode}, must be 'http' or 'socks5'")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "local_port": self.local_port,
            "remote_port": self.remote_port,
            "mode": self.mode,
            "local_host": self.local_host,
            "tags": self.tags,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProxyConfig":
        """Create from dictionary"""
        return cls(
            local_port=data["local_port"],
            remote_port=data["remote_port"],
            mode=data.get("mode", "http"),
            local_host=data.get("local_host", "localhost"),
            tags=data.get("tags", {}),
        )


@dataclass
class TunnelConfig:
    """Tunnel configuration"""
    remote_port: int
    local_host: str = "localhost"
    local_port: int = 7890
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "remote_port": self.remote_port,
            "local_host": self.local_host,
            "local_port": self.local_port,
        }


@dataclass
class ProxyState:
    """Proxy instance state"""
    name: str
    config: ProxyConfig
    ssh_host: str
    pid: Optional[int] = None
    started_at: float = field(default_factory=time.time)
    tunnel_config: Optional[TunnelConfig] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "name": self.name,
            "config": self.config.to_dict(),
            "ssh_host": self.ssh_host,
            "pid": self.pid,
            "started_at": self.started_at,
            "tunnel": self.tunnel_config.to_dict() if self.tunnel_config else None,
        }
    
    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "ProxyState":
        """Create from dictionary"""
        return cls(
            name=name,
            config=ProxyConfig.from_dict(data["config"]),
            ssh_host=data["ssh_host"],
            pid=data.get("pid"),
            started_at=data.get("started_at", time.time()),
            tunnel_config=TunnelConfig(**data["tunnel"]) if data.get("tunnel") else None,
        )

