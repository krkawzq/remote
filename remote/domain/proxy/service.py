"""
Proxy domain service - business logic
"""
import os
import signal
import time
from typing import Optional, Dict, Any, Callable
from pathlib import Path

from ...core.interfaces import StateStore, ConnectionFactory
from ...core.exceptions import ProxyError, ConnectionError
from ...core.logging import get_logger
from ...core.telemetry import get_telemetry
from .models import ProxyConfig, ProxyState, TunnelConfig
from .tunnel import ProxyTunnel

logger = get_logger(__name__)
telemetry = get_telemetry()


class ProxyService:
    """
    Proxy service - pure business logic.
    
    Handles proxy lifecycle: start, stop, status, restart.
    No direct dependency on CLI, Typer, or file system.
    """
    
    def __init__(
        self,
        name: str,
        state_store: StateStore,
        connection_factory: ConnectionFactory,
    ):
        """
        Initialize proxy service.
        
        Args:
            name: Instance name
            state_store: State storage implementation
            connection_factory: SSH connection factory
        """
        self.name = name
        self.state_store = state_store
        self.connection_factory = connection_factory
        self._tunnel: Optional[ProxyTunnel] = None
        self._client = None
    
    def is_running(self) -> bool:
        """Check if proxy is running"""
        return self.state_store.exists(self.name)
    
    def get_status(self) -> Optional[Dict[str, Any]]:
        """
        Get proxy status.
        
        Returns:
            Status dictionary or None if not running
        """
        if not self.is_running():
            return None
        
        state_data = self.state_store.load(self.name)
        if not state_data:
            return None
        
        pid = self.state_store.load_pid(self.name)
        if pid is None:
            return None
        
        return {
            "name": self.name,
            "pid": pid,
            "running": True,
            **state_data,
        }
    
    def start(
        self,
        config: ProxyConfig,
        connection_params: Dict[str, Any],
        ssh_host: str,
        background: bool = True,
        on_started: Optional[Callable[[int], None]] = None,
    ) -> int:
        """
        Start proxy tunnel.
        
        Args:
            config: Proxy configuration
            connection_params: SSH connection parameters
            ssh_host: SSH host name (for display)
            background: Run in background
            on_started: Callback when started (receives PID)
        
        Returns:
            Process ID
        
        Raises:
            ProxyError: If proxy is already running or fails to start
        """
        config.validate()
        
        if self.is_running():
            raise ProxyError(
                f"Proxy '{self.name}' is already running. "
                f"Stop it first with 'remote proxy stop {self.name}'"
            )
        
        if background:
            return self._start_background(config, connection_params, ssh_host, on_started)
        else:
            return self._start_foreground(config, connection_params, ssh_host, on_started)
    
    def _start_background(
        self,
        config: ProxyConfig,
        connection_params: Dict[str, Any],
        ssh_host: str,
        on_started: Optional[Callable[[int], None]] = None,
    ) -> int:
        """Start proxy in background"""
        pid = os.fork()
        
        if pid > 0:
            # Parent process
            self.state_store.save_pid(self.name, pid)
            
            state = ProxyState(
                name=self.name,
                config=config,
                ssh_host=ssh_host,
                pid=pid,
                tunnel_config=TunnelConfig(
                    remote_port=config.remote_port,
                    local_host=config.local_host,
                    local_port=config.local_port,
                ),
            )
            self.state_store.save(self.name, state.to_dict())
            
            if on_started:
                on_started(pid)
            
            telemetry.record_event("proxy.started", {
                "name": self.name,
                "background": True,
                "pid": pid,
            })
            
            return pid
        else:
            # Child process - run proxy
            self._run_proxy(config, connection_params, ssh_host, background=True)
            os._exit(0)
    
    def _start_foreground(
        self,
        config: ProxyConfig,
        connection_params: Dict[str, Any],
        ssh_host: str,
        on_started: Optional[Callable[[int], None]] = None,
    ) -> int:
        """Start proxy in foreground"""
        pid = os.getpid()
        self.state_store.save_pid(self.name, pid)
        
        state = ProxyState(
            name=self.name,
            config=config,
            ssh_host=ssh_host,
            pid=pid,
            tunnel_config=TunnelConfig(
                remote_port=config.remote_port,
                local_host=config.local_host,
                local_port=config.local_port,
            ),
        )
        self.state_store.save(self.name, state.to_dict())
        
        if on_started:
            on_started(pid)
        
        telemetry.record_event("proxy.started", {
            "name": self.name,
            "background": False,
            "pid": pid,
        })
        
        try:
            self._run_proxy(config, connection_params, ssh_host, background=False)
        finally:
            self.stop()
        
        return pid
    
    def _run_proxy(
        self,
        config: ProxyConfig,
        connection_params: Dict[str, Any],
        ssh_host: str,
        background: bool,
    ) -> None:
        """Run proxy tunnel"""
        from ...infrastructure.state.file_store import FileStateStore
        
        # Redirect logs if background
        if background and isinstance(self.state_store, FileStateStore):
            log_dir = self.state_store.state_dir
            stdout_file = log_dir / f"{self.name}.out"
            stderr_file = log_dir / f"{self.name}.err"
            
            with open(stdout_file, 'a') as fout, open(stderr_file, 'a') as ferr:
                os.dup2(fout.fileno(), 1)
                os.dup2(ferr.fileno(), 2)
            
            # Create new session to detach from terminal
            os.setsid()
            
            # Update PID file with child PID
            child_pid = os.getpid()
            self.state_store.save_pid(self.name, child_pid)
        
        try:
            # Create SSH client
            self._client = self.connection_factory.create(connection_params)
            
            # Create tunnel configuration
            tunnel_config = TunnelConfig(
                remote_port=config.remote_port,
                local_host=config.local_host,
                local_port=config.local_port,
            )
            
            # Create and start tunnel
            self._tunnel = ProxyTunnel(self._client, tunnel_config)
            self._tunnel.start()
            
            logger.info(f"Proxy tunnel started: {ssh_host}")
            
            # Keep alive loop
            while True:
                # Check if PID file still exists
                if not self.state_store.exists(self.name):
                    break
                
                # Check if tunnel is still running
                if not self._tunnel.is_running():
                    logger.warning("Tunnel connection lost")
                    break
                
                time.sleep(1)
        
        except KeyboardInterrupt:
            logger.info("Received interrupt signal")
        except Exception as e:
            logger.error(f"Proxy error: {e}", exc_info=True)
            telemetry.record_event("proxy.error", {
                "name": self.name,
                "error": str(e),
            })
            raise
        finally:
            if self._tunnel:
                self._tunnel.stop()
            if self._client:
                self._client.close()
            self.state_store.delete(self.name)
    
    def stop(self) -> None:
        """
        Stop proxy tunnel.
        
        Raises:
            ProxyError: If proxy is not running
        """
        if not self.is_running():
            raise ProxyError(f"Proxy '{self.name}' is not running")
        
        pid = self.state_store.load_pid(self.name)
        if pid is None:
            self.state_store.delete(self.name)
            raise ProxyError(f"Proxy '{self.name}' PID not found")
        
        try:
            # Try graceful shutdown first
            os.kill(pid, signal.SIGTERM)
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
        
        self.state_store.delete(self.name)
        
        telemetry.record_event("proxy.stopped", {
            "name": self.name,
            "pid": pid,
        })
        
        logger.info(f"Proxy '{self.name}' stopped")
    
    @classmethod
    def list_all(cls, state_store: StateStore) -> list[str]:
        """List all proxy instance names"""
        return state_store.list()
    
    @classmethod
    def get_all_status(cls, state_store: StateStore) -> Dict[str, Dict[str, Any]]:
        """Get status of all proxy instances"""
        instances = cls.list_all(state_store)
        result = {}
        
        for name in instances:
            # Load state directly from store
            state_data = state_store.load(name)
            if not state_data:
                continue
            
            pid = state_store.load_pid(name)
            if pid is None:
                continue
            
            result[name] = {
                "name": name,
                "pid": pid,
                "running": True,
                **state_data,
            }
        
        return result

