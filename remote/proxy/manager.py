"""
Proxy manager for managing SSH reverse proxy tunnels
"""
import json
import signal
import os
import time
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict

import typer

from ..client import RemoteClient
from ..config import create_client, resolve_connection_params
from ..exceptions import RemoteError, ProxyError
from .tunnel import ProxyTunnel, TunnelConfig


@dataclass
class ProxyConfig:
    """Proxy configuration"""
    local_port: int
    remote_port: int
    mode: str = "http"  # http or socks5
    local_host: str = "localhost"
    
    def validate(self) -> None:
        """Validate configuration"""
        if not (1 <= self.local_port <= 65535):
            raise ProxyError(f"Invalid local_port: {self.local_port}")
        if not (1 <= self.remote_port <= 65535):
            raise ProxyError(f"Invalid remote_port: {self.remote_port}")
        if self.mode not in ("http", "socks5"):
            raise ProxyError(f"Invalid mode: {self.mode}, must be 'http' or 'socks5'")


class ProxyManager:
    """
    Manages SSH reverse proxy tunnels.
    
    Features:
    - Start/stop proxy tunnels
    - Persistent state management (PID file)
    - Automatic reconnection
    - Status monitoring
    """
    
    def __init__(self, state_dir: Optional[Path] = None):
        """
        Initialize proxy manager.
        
        Args:
            state_dir: Directory for storing state files (default: ~/.remote/proxy)
        """
        if state_dir is None:
            state_dir = Path.home() / ".remote" / "proxy"
        
        self.state_dir = Path(state_dir).expanduser()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        
        self.pidfile = self.state_dir / "proxy.pid"
        self.statefile = self.state_dir / "proxy.json"
    
    def _load_state(self) -> Optional[Dict[str, Any]]:
        """Load proxy state from file"""
        if not self.statefile.exists():
            return None
        
        try:
            return json.loads(self.statefile.read_text())
        except Exception:
            return None
    
    def _save_state(self, state: Dict[str, Any]) -> None:
        """Save proxy state to file"""
        self.statefile.write_text(json.dumps(state, indent=2))
    
    def _clear_state(self) -> None:
        """Clear proxy state"""
        if self.pidfile.exists():
            self.pidfile.unlink()
        if self.statefile.exists():
            self.statefile.unlink()
    
    def is_running(self) -> bool:
        """Check if proxy is running"""
        if not self.pidfile.exists():
            return False
        
        try:
            pid = int(self.pidfile.read_text().strip())
            # Check if process exists
            os.kill(pid, 0)
            return True
        except (OSError, ValueError):
            # Process doesn't exist, clean up
            self._clear_state()
            return False
    
    def get_status(self) -> Optional[Dict[str, Any]]:
        """Get proxy status"""
        if not self.is_running():
            return None
        
        state = self._load_state()
        if not state:
            return None
        
        try:
            pid = int(self.pidfile.read_text().strip())
            state["pid"] = pid
            state["running"] = True
        except (ValueError, OSError):
            state["running"] = False
        
        return state
    
    def start(
        self,
        config: ProxyConfig,
        connection_params: Dict[str, Any],
        ssh_config_name: Optional[str] = None,
        background: bool = False
    ) -> int:
        """
        Start proxy tunnel.
        
        Args:
            config: Proxy configuration
            connection_params: SSH connection parameters
            ssh_config_name: SSH config host name (for status display)
            background: Run in background (not implemented yet, always False)
        
        Returns:
            Process ID
        
        Raises:
            ProxyError: If proxy is already running or fails to start
        """
        config.validate()
        
        if self.is_running():
            raise ProxyError("Proxy is already running. Stop it first with 'rmt proxy stop'")
        
        # Create SSH client and connect
        client, _ = create_client(connection_params)
        
        # Create tunnel using paramiko
        tunnel_config = TunnelConfig(
            remote_port=config.remote_port,
            local_host=config.local_host,
            local_port=config.local_port
        )
        
        tunnel = ProxyTunnel(client, tunnel_config)
        
        # Start tunnel
        tunnel.start()
        
        # Save state
        pid = os.getpid()
        self.pidfile.write_text(str(pid))
        
        state = {
            "config": asdict(config),
            "connection": {
                "host": connection_params["host"],
                "user": connection_params["user"],
                "port": connection_params["port"],
            },
            "ssh_config": ssh_config_name,
            "started_at": time.time(),
            "tunnel": {
                "remote_port": config.remote_port,
                "local_host": config.local_host,
                "local_port": config.local_port,
            }
        }
        self._save_state(state)
        
        # Store tunnel and client references for cleanup
        # These need to stay alive for the tunnel to work
        self._tunnel = tunnel
        self._client = client
        
        typer.echo(f"[proxy] Started reverse tunnel: remote localhost:{config.remote_port} -> local {config.local_host}:{config.local_port}")
        typer.echo(f"[proxy] PID: {pid}")
        typer.echo(f"[proxy] To use on remote: export http_proxy=http://localhost:{config.remote_port}")
        typer.echo(f"[proxy] Press Ctrl+C to stop")
        
        return pid
    
    def stop(self) -> None:
        """
        Stop proxy tunnel.
        
        Raises:
            ProxyError: If proxy is not running
        """
        if not self.is_running():
            raise ProxyError("Proxy is not running")
        
        try:
            pid = int(self.pidfile.read_text().strip())
            
            # Try graceful shutdown first
            try:
                os.kill(pid, signal.SIGTERM)
                # Wait a bit for graceful shutdown
                time.sleep(1)
                
                # Check if still running
                try:
                    os.kill(pid, 0)
                    # Still running, force kill
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    # Process already dead
                    pass
            except OSError:
                # Process doesn't exist
                pass
            
            self._clear_state()
            typer.echo("[proxy] Stopped")
        
        except Exception as e:
            raise ProxyError(f"Failed to stop proxy: {e}") from e
    
    def keep_alive(self) -> None:
        """
        Keep proxy alive (blocking).
        
        This should be called after start() to keep the tunnel running.
        """
        try:
            while self.is_running():
                time.sleep(1)
        except KeyboardInterrupt:
            typer.echo("\n[proxy] Stopping...")
            self.stop()

