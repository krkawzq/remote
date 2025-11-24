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

from ..config import create_client
from ..exceptions import ProxyError
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
    - Support multiple instances by name
    """
    
    def __init__(self, name: str = "default", state_dir: Optional[Path] = None):
        """
        Initialize proxy manager.
        
        Args:
            name: Instance name (default: "default")
            state_dir: Directory for storing state files (default: ~/.remote/proxy)
        """
        if state_dir is None:
            state_dir = Path.home() / ".remote" / "proxy"
        
        self.name = name
        self.state_dir = Path(state_dir).expanduser()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        
        # Use name-specific files
        self.pidfile = self.state_dir / f"{name}.pid"
        self.statefile = self.state_dir / f"{name}.json"
    
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
            state["name"] = self.name
        except (ValueError, OSError):
            state["running"] = False
        
        return state
    
    @classmethod
    def get_all_status(cls, state_dir: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
        """
        Get status of all proxy instances.
        
        Args:
            state_dir: Directory for storing state files (default: ~/.remote/proxy)
        
        Returns:
            Dictionary mapping instance names to their status
        """
        instances = cls.list_all_instances(state_dir)
        result = {}
        for name in instances:
            manager = cls(name, state_dir)
            status = manager.get_status()
            if status:
                result[name] = status
        return result
    
    def start(
        self,
        config: ProxyConfig,
        connection_params: Dict[str, Any],
        ssh_host: str,
        background: bool = True
    ) -> int:
        """
        Start proxy tunnel.
        
        Args:
            config: Proxy configuration
            connection_params: SSH connection parameters
            ssh_host: SSH host name (for display)
            background: Run in background (default: True)
        
        Returns:
            Process ID
        
        Raises:
            ProxyError: If proxy is already running or fails to start
        """
        config.validate()
        
        if self.is_running():
            raise ProxyError(f"Proxy '{self.name}' is already running. Stop it first with 'remote proxy stop {self.name}'")
        
        if background:
            # Fork process for background execution
            pid = os.fork()
            if pid > 0:
                # Parent process - save state and return
                self.pidfile.write_text(str(pid))
                state = {
                    "config": asdict(config),
                    "ssh_host": ssh_host,
                    "started_at": time.time(),
                    "tunnel": {
                        "remote_port": config.remote_port,
                        "local_host": config.local_host,
                        "local_port": config.local_port,
                    },
                    "name": self.name,
                }
                self._save_state(state)
                typer.echo(f"[proxy] Started '{self.name}' in background")
                typer.echo(f"[proxy] SSH host: {ssh_host}")
                typer.echo(f"[proxy] PID: {pid}")
                typer.echo(f"[proxy] Remote port: {config.remote_port} -> Local: {config.local_host}:{config.local_port}")
                typer.echo(f"[proxy] Use 'remote proxy status {self.name}' to check status")
                return pid
            else:
                # Child process - run proxy
                # Redirect stdout/stderr to log files
                log_dir = self.state_dir
                stdout_file = log_dir / f"{self.name}.out"
                stderr_file = log_dir / f"{self.name}.err"
                
                with open(stdout_file, 'a') as fout, open(stderr_file, 'a') as ferr:
                    os.dup2(fout.fileno(), 1)
                    os.dup2(ferr.fileno(), 2)
                
                # Create new session to detach from terminal
                os.setsid()
                
                # Save child PID
                child_pid = os.getpid()
                self.pidfile.write_text(str(child_pid))
                
                try:
                    # Create SSH client and connect
                    client, _ = create_client(connection_params)
                    
                    # Create tunnel configuration
                    tunnel_config = TunnelConfig(
                        remote_port=config.remote_port,
                        local_host=config.local_host,
                        local_port=config.local_port
                    )
                    
                    # Create and start tunnel
                    tunnel = ProxyTunnel(client, tunnel_config)
                    tunnel.start()
                    
                    # Store references
                    self._tunnel = tunnel
                    self._client = client
                    
                    # Keep alive
                    while True:
                        # Check if PID file still exists
                        if not self.pidfile.exists():
                            break
                        try:
                            saved_pid = int(self.pidfile.read_text().strip())
                            if saved_pid != os.getpid():
                                break
                        except (ValueError, OSError):
                            break
                        
                        # Check if tunnel is still running
                        if not tunnel.is_running():
                            break
                        
                        time.sleep(1)
                
                except KeyboardInterrupt:
                    pass
                except Exception as e:
                    print(f"[proxy] Error: {e}", flush=True)
                finally:
                    if hasattr(self, '_tunnel'):
                        self._tunnel.stop()
                    if hasattr(self, '_client'):
                        self._client.close()
                    self._clear_state()
                
                os._exit(0)
        else:
            # Foreground execution
            try:
                # Create SSH client and connect
                client, _ = create_client(connection_params)
                
                # Create tunnel configuration
                tunnel_config = TunnelConfig(
                    remote_port=config.remote_port,
                    local_host=config.local_host,
                    local_port=config.local_port
                )
                
                # Create and start tunnel
                tunnel = ProxyTunnel(client, tunnel_config)
                tunnel.start()
                
                # Save state
                pid = os.getpid()
                self.pidfile.write_text(str(pid))
                
                state = {
                    "config": asdict(config),
                    "ssh_host": ssh_host,
                    "started_at": time.time(),
                    "tunnel": {
                        "remote_port": config.remote_port,
                        "local_host": config.local_host,
                        "local_port": config.local_port,
                    },
                    "name": self.name,
                }
                self._save_state(state)
                
                # Store references
                self._tunnel = tunnel
                self._client = client
                
                typer.echo(f"[proxy] Started reverse tunnel")
                typer.echo(f"[proxy] Remote localhost:{config.remote_port} -> Local {config.local_host}:{config.local_port}")
                typer.echo(f"[proxy] PID: {pid}")
                typer.echo(f"[proxy] Press Ctrl+C to stop")
                
                # Keep alive
                try:
                    while tunnel.is_running():
                        time.sleep(1)
                except KeyboardInterrupt:
                    typer.echo("\n[proxy] Stopping...")
                
                return pid
            
            except Exception as e:
                self._clear_state()
                raise ProxyError(f"Failed to start proxy: {e}") from e
            finally:
                if hasattr(self, '_tunnel'):
                    self._tunnel.stop()
                if hasattr(self, '_client'):
                    self._client.close()
                self._clear_state()
    
    def stop(self) -> None:
        """
        Stop proxy tunnel.
        
        Raises:
            ProxyError: If proxy is not running
        """
        if not self.is_running():
            raise ProxyError(f"Proxy '{self.name}' is not running")
        
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
            typer.echo(f"[proxy] Stopped '{self.name}'")
        
        except Exception as e:
            raise ProxyError(f"Failed to stop proxy '{self.name}': {e}") from e
    
    @classmethod
    def list_all_instances(cls, state_dir: Optional[Path] = None) -> list[str]:
        """
        List all proxy instance names.
        
        Args:
            state_dir: Directory for storing state files (default: ~/.remote/proxy)
        
        Returns:
            List of instance names
        """
        if state_dir is None:
            state_dir = Path.home() / ".remote" / "proxy"
        
        state_dir = Path(state_dir).expanduser()
        if not state_dir.exists():
            return []
        
        instances = set()
        for pidfile in state_dir.glob("*.pid"):
            name = pidfile.stem
            # Check if process is still running
            try:
                pid = int(pidfile.read_text().strip())
                os.kill(pid, 0)
                instances.add(name)
            except (OSError, ValueError):
                # Process doesn't exist, clean up
                pidfile.unlink()
                json_file = state_dir / f"{name}.json"
                if json_file.exists():
                    json_file.unlink()
        
        return sorted(instances)
    

