"""
SSH reverse tunnel implementation using paramiko

Design Notes:
=============
Implements reverse port forwarding (Remote Port Forwarding) using paramiko:
- Remote server accesses localhost:remote_port
- Traffic is forwarded through SSH tunnel to local localhost:local_port

Paramiko Implementation:
- Use Transport.request_port_forward() to establish listener on remote
- Use Transport.accept() to receive connections from remote
- Create threads for each connection to handle bidirectional data forwarding

Advantages:
- Pure Python implementation, cross-platform compatible
- Supports password and key authentication
- Better error handling and state management
- No dependency on system SSH commands
"""
import socket
import threading
import select
import time
from typing import Optional
from dataclasses import dataclass

import paramiko

from ..client import RemoteClient
from ..exceptions import ConnectionError


@dataclass
class TunnelConfig:
    """Tunnel configuration"""
    remote_port: int
    local_host: str = "localhost"
    local_port: int = 7890


class ProxyTunnel:
    """
    SSH reverse tunnel using paramiko.
    
    Implements reverse port forwarding:
    - Remote localhost:remote_port -> Local localhost:local_port
    
    How it works:
    1. Call Transport.request_port_forward() to establish listener port on remote
    2. Use Transport.accept() to receive connections from remote
    3. Create threads for each connection to handle bidirectional data forwarding
    """
    
    def __init__(
        self,
        client: RemoteClient,
        config: TunnelConfig
    ):
        """
        Initialize tunnel.
        
        Args:
            client: Connected RemoteClient instance
            config: Tunnel configuration
        """
        self.client = client
        self.config = config
        self._transport: Optional[paramiko.Transport] = None
        self._running = False
        self._acceptor_thread: Optional[threading.Thread] = None
        self._handler_threads: list[threading.Thread] = []
        self._lock = threading.Lock()
    
    def start(self) -> None:
        """
        Start the reverse tunnel.
        
        Raises:
            RuntimeError: If tunnel is already running
            ConnectionError: If SSH connection is not available
        """
        with self._lock:
            if self._running:
                raise RuntimeError("Tunnel is already running")
            
            self._transport = self.client.client.get_transport()
            if not self._transport:
                raise ConnectionError("SSH transport not available")
            
            if not self._transport.is_alive():
                raise ConnectionError("SSH connection is not alive")
            
            # Request reverse port forward on remote server
            try:
                self._transport.request_port_forward(
                    address='',  # Empty string = bind to localhost on remote
                    port=self.config.remote_port
                )
            except Exception as e:
                raise ConnectionError(
                    f"Failed to request reverse port forward: {e}. "
                    "Make sure SSH server supports reverse port forwarding."
                ) from e
            
            # Start acceptor thread
            self._running = True
            self._acceptor_thread = threading.Thread(
                target=self._run_acceptor,
                daemon=True,
                name=f"ProxyTunnel-Acceptor-{self.config.remote_port}"
            )
            self._acceptor_thread.start()
    
    def stop(self) -> None:
        """Stop the tunnel"""
        with self._lock:
            if not self._running:
                return
            
            self._running = False
            
            # Cancel port forward
            if self._transport:
                try:
                    self._transport.cancel_port_forward('', self.config.remote_port)
                except Exception:
                    pass
            
            # Wait for acceptor thread
            if self._acceptor_thread and self._acceptor_thread.is_alive():
                self._acceptor_thread.join(timeout=2.0)
            
            # Clean up handler threads
            for thread in self._handler_threads[:]:
                if thread.is_alive():
                    thread.join(timeout=0.5)
            self._handler_threads.clear()
    
    def is_running(self) -> bool:
        """Check if tunnel is running"""
        with self._lock:
            return self._running and self._transport and self._transport.is_alive()
    
    def _run_acceptor(self) -> None:
        """
        Main acceptor loop.
        
        Continuously accepts incoming connections from remote
        and spawns handler threads for each connection.
        """
        try:
            while self._running:
                if not self._transport or not self._transport.is_alive():
                    raise ConnectionError("SSH connection lost")
                
                # Accept incoming connection (with timeout)
                chan = self._transport.accept(timeout=1.0)
                if chan is None:
                    continue
                
                # Spawn handler thread for this connection
                handler_thread = threading.Thread(
                    target=self._handle_connection,
                    args=(chan,),
                    daemon=True,
                    name=f"ProxyTunnel-Handler-{id(chan)}"
                )
                handler_thread.start()
                
                # Track handler thread
                with self._lock:
                    self._handler_threads.append(handler_thread)
                    # Clean up finished threads
                    self._handler_threads = [t for t in self._handler_threads if t.is_alive()]
        
        except Exception as e:
            if self._running:  # Only log if not intentionally stopped
                print(f"[proxy] Acceptor error: {e}")
    
    def _handle_connection(self, chan: paramiko.Channel) -> None:
        """
        Handle a single connection from remote.
        
        Creates a connection to local proxy and forwards data bidirectionally.
        
        Args:
            chan: SSH channel from remote
        """
        local_sock = None
        try:
            # Connect to local proxy
            local_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            local_sock.settimeout(10)
            local_sock.connect((self.config.local_host, self.config.local_port))
            local_sock.settimeout(None)  # Set to blocking mode
            
            # Forward data bidirectionally
            self._forward_data(chan, local_sock)
        
        except Exception as e:
            # Connection errors are expected when connections close
            pass
        finally:
            if local_sock:
                try:
                    local_sock.close()
                except Exception:
                    pass
            try:
                chan.close()
            except Exception:
                pass
    
    def _forward_data(self, chan: paramiko.Channel, sock: socket.socket) -> None:
        """
        Forward data bidirectionally between SSH channel and socket.
        
        Uses select() for efficient multiplexing of both directions.
        
        Args:
            chan: SSH channel (from remote)
            sock: Local socket (to local proxy)
        """
        try:
            while self._running:
                # Check if either side is closed
                if chan.closed:
                    break
                
                # Use select to wait for data on either side
                # We only select on socket for reading; channel is checked via recv_ready()
                read_ready = []
                if chan.recv_ready():
                    read_ready.append('chan')
                
                # Check socket with select (non-blocking check)
                r, w, x = select.select([sock], [], [], 0.01)
                if r:
                    read_ready.append('sock')
                
                # No data available, continue
                if not read_ready:
                    continue
                
                # Forward data from channel to socket
                if 'chan' in read_ready:
                    try:
                        data = chan.recv(8192)
                        if len(data) == 0:
                            break
                        sock.sendall(data)
                    except (socket.error, OSError):
                        break
                    except paramiko.SSHException:
                        break
                
                # Forward data from socket to channel
                if 'sock' in read_ready:
                    try:
                        data = sock.recv(8192)
                        if len(data) == 0:
                            break
                        chan.sendall(data)
                    except (socket.error, OSError):
                        break
                    except paramiko.SSHException:
                        break
        
        except Exception:
            pass
