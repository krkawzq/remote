"""
SSH reverse tunnel implementation using paramiko

设计说明：
==========
真正的反向端口转发（Remote Port Forwarding）：
- 远程机器访问 localhost:remote_port
- 通过 SSH 通道转发到本地 localhost:local_port

Paramiko 实现方式：
- 使用 Transport.request_port_forward() 在远程建立监听
- 使用 Transport.accept() 接收来自远程的连接
- 为每个连接创建到本地代理的 socket 连接并转发数据
"""
import socket
import threading
import time
from typing import Optional, Callable
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
    SSH reverse tunnel using paramiko Transport.request_port_forward.
    
    实现真正的反向端口转发：
    - 远程 localhost:remote_port -> 本地 localhost:local_port
    
    工作原理：
    1. 调用 Transport.request_port_forward() 在远程建立监听端口
    2. 使用 Transport.accept() 接收来自远程的连接
    3. 为每个连接创建到本地代理的 socket 并双向转发数据
    """
    
    def __init__(
        self,
        client: RemoteClient,
        config: TunnelConfig,
        on_error: Optional[Callable[[Exception], None]] = None
    ):
        """
        Initialize tunnel.
        
        Args:
            client: Connected RemoteClient instance
            config: Tunnel configuration
            on_error: Error callback function
        """
        self.client = client
        self.config = config
        self.on_error = on_error
        self._transport: Optional[paramiko.Transport] = None
        self._acceptor_thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()
        self._channels: list = []
    
    def start(self) -> None:
        """
        Start the reverse tunnel.
        
        Implementation note:
        Paramiko doesn't directly support reverse port forwarding (-R option).
        We implement it by:
        1. Using Transport.request_port_forward() to request the SSH server
           to forward connections from remote_port to our local handler
        2. The handler receives connections and forwards them to local proxy
        
        Note: This requires SSH server to support reverse port forwarding
        (GatewayPorts may need to be enabled on server).
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
            # This tells SSH server: "listen on remote_port and forward to our handler"
            # The handler will then connect to local proxy and forward data
            try:
                # request_port_forward with handler function
                # When remote connects to remote_port, handler is called with the channel
                self._transport.request_port_forward(
                    address='',  # Empty string means bind to localhost on remote
                    port=self.config.remote_port,
                    handler=self._handle_remote_connection
                )
            except Exception as e:
                raise ConnectionError(
                    f"Failed to request reverse port forward: {e}. "
                    "Make sure SSH server supports reverse port forwarding."
                ) from e
            
            # Start acceptor thread to handle incoming connections
            self._running = True
            self._acceptor_thread = threading.Thread(
                target=self._run_acceptor,
                daemon=True
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
            
            # Close all active channels
            for chan in self._channels[:]:
                try:
                    chan.close()
                except Exception:
                    pass
            self._channels.clear()
            
            if self._acceptor_thread and self._acceptor_thread.is_alive():
                self._acceptor_thread.join(timeout=2.0)
    
    def is_running(self) -> bool:
        """Check if tunnel is running"""
        with self._lock:
            return self._running
    
    def _run_acceptor(self) -> None:
        """
        Main acceptor loop.
        
        When using request_port_forward with a handler, the handler is called
        automatically when connections arrive. However, we also need to keep
        the transport alive and handle connection errors.
        """
        try:
            while self._running:
                if not self._transport or not self._transport.is_alive():
                    raise ConnectionError("SSH connection lost")
                
                # Keep connection alive
                # The handler function will be called automatically by paramiko
                # when connections arrive from remote
                time.sleep(1.0)
        
        except Exception as e:
            if self.on_error:
                self.on_error(e)
            else:
                raise
    
    def _handle_remote_connection(
        self,
        chan: paramiko.Channel,
        origin: tuple = None,
        destination: tuple = None
    ) -> None:
        """
        Handle a connection from remote.
        
        Creates a connection to local proxy server and forwards data bidirectionally.
        
        Args:
            chan: SSH channel representing connection from remote
        """
        local_sock = None
        try:
            with self._lock:
                self._channels.append(chan)
            
            # Connect to local proxy server
            local_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            local_sock.settimeout(10)
            local_sock.connect((self.config.local_host, self.config.local_port))
            
            # Forward data bidirectionally
            self._forward_data(chan, local_sock)
        
        except Exception as e:
            if self.on_error:
                self.on_error(e)
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
            with self._lock:
                if chan in self._channels:
                    self._channels.remove(chan)
    
    def _forward_data(self, chan: paramiko.Channel, sock: socket.socket) -> None:
        """
        Forward data bidirectionally between SSH channel and socket.
        
        Uses non-blocking I/O with select for efficient data transfer.
        
        Args:
            chan: SSH channel (from remote)
            sock: Local socket (to local proxy)
        """
        import select
        
        try:
            while self._running:
                if chan.closed or sock.fileno() == -1:
                    break
                
                # Forward data from remote (channel) to local (socket)
                if chan.recv_ready():
                    data = chan.recv(4096)
                    if not data:
                        break
                    try:
                        sock.sendall(data)
                    except (socket.error, OSError):
                        break
                
                # Forward data from local (socket) to remote (channel)
                if select.select([sock], [], [], 0.1)[0]:
                    data = sock.recv(4096)
                    if not data:
                        break
                    try:
                        chan.sendall(data)
                    except paramiko.SSHException:
                        break
                
                # Small sleep to avoid CPU spinning
                time.sleep(0.01)
        
        except Exception as e:
            if self.on_error:
                self.on_error(e)

