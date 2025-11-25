"""
SSH tunnel implementations and built-in proxy server
"""
import socket
import threading
import select
import struct
from typing import Optional, Callable
from enum import IntEnum

import paramiko

from ...core.client import RemoteClient
from ...core.exceptions import ConnectionError
from ...core.logging import get_logger
from .models import TunnelConfig

logger = get_logger(__name__)


# ============================================================================
# SOCKS5 Protocol Constants
# ============================================================================

class SOCKS5Method(IntEnum):
    """SOCKS5 authentication methods"""
    NO_AUTH = 0x00
    GSSAPI = 0x01
    USERNAME_PASSWORD = 0x02
    NO_ACCEPTABLE = 0xFF


class SOCKS5Command(IntEnum):
    """SOCKS5 commands"""
    CONNECT = 0x01
    BIND = 0x02
    UDP_ASSOCIATE = 0x03


class SOCKS5AddressType(IntEnum):
    """SOCKS5 address types"""
    IPV4 = 0x01
    DOMAIN = 0x03
    IPV6 = 0x04


class SOCKS5Reply(IntEnum):
    """SOCKS5 reply codes"""
    SUCCESS = 0x00
    GENERAL_FAILURE = 0x01
    CONNECTION_NOT_ALLOWED = 0x02
    NETWORK_UNREACHABLE = 0x03
    HOST_UNREACHABLE = 0x04
    CONNECTION_REFUSED = 0x05
    TTL_EXPIRED = 0x06
    COMMAND_NOT_SUPPORTED = 0x07
    ADDRESS_TYPE_NOT_SUPPORTED = 0x08


# ============================================================================
# Reverse Tunnel (Remote -> Local)
# ============================================================================

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
                logger.error(f"Acceptor error: {e}", exc_info=True)
    
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
        
        except Exception:
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


# ============================================================================
# Forward Tunnel (Local -> Remote)
# ============================================================================

class ForwardTunnel:
    """
    SSH forward tunnel for built-in proxy server.
    
    Creates a tunnel from local -> remote proxy through SSH.
    """
    
    def __init__(
        self,
        client: RemoteClient,
        remote_host: str,
        remote_port: int,
    ):
        """
        Initialize forward tunnel.
        
        Args:
            client: Connected RemoteClient instance
            remote_host: Remote proxy host (usually localhost on remote)
            remote_port: Remote proxy port
        """
        self.client = client
        self.remote_host = remote_host
        self.remote_port = remote_port
        self._transport: Optional[paramiko.Transport] = None
        self._running = False
    
    def connect(self, target_host: str, target_port: int) -> socket.socket:
        """
        Create a tunnel connection to target through remote proxy.
        
        Args:
            target_host: Target host to connect to
            target_port: Target port to connect to
        
        Returns:
            Socket connected to target through tunnel
        """
        if not self._transport:
            self._transport = self.client.client.get_transport()
            if not self._transport:
                raise ConnectionError("SSH transport not available")
            
            if not self._transport.is_alive():
                raise ConnectionError("SSH connection is not alive")
        
        # Create a channel for port forwarding
        # We'll use direct-tcpip channel type
        try:
            chan = self._transport.open_channel(
                'direct-tcpip',
                (target_host, target_port),
                (self.remote_host, self.remote_port)
            )
            
            if chan is None:
                raise ConnectionError(f"Failed to open channel to {target_host}:{target_port}")
            
            # Convert channel to socket-like object
            return ChannelSocket(chan)
        
        except Exception as e:
            raise ConnectionError(f"Failed to create tunnel connection: {e}") from e
    
    def is_alive(self) -> bool:
        """Check if tunnel is alive"""
        return (
            self._transport is not None
            and self._transport.is_alive()
        )


class ChannelSocket:
    """
    Socket-like wrapper for paramiko Channel.
    
    Allows using paramiko Channel as a socket in proxy server.
    """
    
    def __init__(self, channel: paramiko.Channel):
        self.channel = channel
        self._closed = False
    
    def recv(self, bufsize: int) -> bytes:
        """Receive data from channel"""
        if self._closed or self.channel.closed:
            return b""
        try:
            return self.channel.recv(bufsize)
        except Exception:
            return b""
    
    def sendall(self, data: bytes) -> None:
        """Send data to channel"""
        if self._closed or self.channel.closed:
            raise socket.error("Channel is closed")
        try:
            self.channel.sendall(data)
        except Exception as e:
            raise socket.error(f"Send failed: {e}") from e
    
    def close(self) -> None:
        """Close channel"""
        if not self._closed:
            self._closed = True
            try:
                self.channel.close()
            except Exception:
                pass
    
    def getsockname(self) -> tuple:
        """Get socket name (for SOCKS5 reply)"""
        # Return a dummy address
        return ("127.0.0.1", 0)
    
    def fileno(self) -> int:
        """Get file descriptor"""
        # Channel doesn't have a real file descriptor
        # Return -1 to indicate this
        return -1
    
    def settimeout(self, timeout: Optional[float]) -> None:
        """Set timeout (not supported for channels)"""
        pass


# ============================================================================
# Built-in Proxy Server
# ============================================================================

class ProxyServer:
    """
    Built-in SOCKS5/HTTP proxy server.
    
    Listens on local port and forwards connections through SSH tunnel.
    """
    
    def __init__(
        self,
        local_host: str = "127.0.0.1",
        local_port: int = 7890,
        mode: str = "socks5",
        tunnel_handler: Optional[Callable[[str, int], socket.socket]] = None,
    ):
        """
        Initialize proxy server.
        
        Args:
            local_host: Local bind address
            local_port: Local bind port
            mode: Proxy mode ("socks5" or "http")
            tunnel_handler: Function to create tunnel connection (host, port) -> socket
        """
        self.local_host = local_host
        self.local_port = local_port
        self.mode = mode.lower()
        self.tunnel_handler = tunnel_handler
        self._socket: Optional[socket.socket] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._client_threads: list[threading.Thread] = []
        
        if self.mode not in ("socks5", "http"):
            raise ValueError(f"Unsupported mode: {mode}, must be 'socks5' or 'http'")
    
    def start(self) -> None:
        """Start the proxy server"""
        if self._running:
            raise RuntimeError("Proxy server is already running")
        
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((self.local_host, self.local_port))
        self._socket.listen(128)
        self._socket.settimeout(1.0)  # Allow periodic checks
        
        self._running = True
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name=f"ProxyServer-{self.mode}-{self.local_port}"
        )
        self._thread.start()
        
        logger.info(f"Started {self.mode.upper()} proxy server on {self.local_host}:{self.local_port}")
    
    def stop(self) -> None:
        """Stop the proxy server"""
        if not self._running:
            return
        
        self._running = False
        
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
        
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        
        # Wait for client threads
        for thread in self._client_threads[:]:
            if thread.is_alive():
                thread.join(timeout=0.5)
        self._client_threads.clear()
        
        logger.info(f"Stopped {self.mode.upper()} proxy server")
    
    def is_running(self) -> bool:
        """Check if proxy server is running"""
        return self._running
    
    def _run(self) -> None:
        """Main server loop"""
        try:
            while self._running:
                try:
                    client_sock, addr = self._socket.accept()
                    
                    # Spawn handler thread
                    handler_thread = threading.Thread(
                        target=self._handle_client,
                        args=(client_sock, addr),
                        daemon=True,
                        name=f"ProxyHandler-{addr}"
                    )
                    handler_thread.start()
                    self._client_threads.append(handler_thread)
                    
                    # Clean up finished threads
                    self._client_threads = [t for t in self._client_threads if t.is_alive()]
                    
                except socket.timeout:
                    continue
                except OSError:
                    if self._running:
                        raise
        
        except Exception as e:
            if self._running:
                logger.error(f"Proxy server error: {e}", exc_info=True)
    
    def _handle_client(self, client_sock: socket.socket, addr: tuple) -> None:
        """Handle a client connection"""
        try:
            if self.mode == "socks5":
                self._handle_socks5(client_sock)
            else:
                self._handle_http(client_sock)
        except Exception as e:
            logger.debug(f"Client handler error: {e}")
        finally:
            try:
                client_sock.close()
            except Exception:
                pass
    
    def _handle_socks5(self, client_sock: socket.socket) -> None:
        """Handle SOCKS5 protocol"""
        # SOCKS5 greeting
        greeting = client_sock.recv(2)
        if len(greeting) < 2:
            return
        
        version, nmethods = greeting
        if version != 5:
            return
        
        methods = client_sock.recv(nmethods)
        if len(methods) < nmethods:
            return
        
        # Select NO_AUTH
        client_sock.sendall(bytes([5, SOCKS5Method.NO_AUTH]))
        
        # SOCKS5 request
        request = client_sock.recv(4)
        if len(request) < 4:
            return
        
        version, cmd, rsv, atype = request
        if version != 5:
            return
        
        if cmd != SOCKS5Command.CONNECT:
            client_sock.sendall(bytes([5, SOCKS5Reply.COMMAND_NOT_SUPPORTED, 0, 1, 0, 0, 0, 0, 0, 0]))
            return
        
        # Parse address
        if atype == SOCKS5AddressType.IPV4:
            addr_data = client_sock.recv(4)
            if len(addr_data) < 4:
                return
            host = socket.inet_ntoa(addr_data)
        elif atype == SOCKS5AddressType.DOMAIN:
            len_data = client_sock.recv(1)
            if len(len_data) < 1:
                return
            domain_len = len_data[0]
            domain_data = client_sock.recv(domain_len)
            if len(domain_data) < domain_len:
                return
            host = domain_data.decode('utf-8', errors='ignore')
        elif atype == SOCKS5AddressType.IPV6:
            addr_data = client_sock.recv(16)
            if len(addr_data) < 16:
                return
            host = socket.inet_ntop(socket.AF_INET6, addr_data)
        else:
            client_sock.sendall(bytes([5, SOCKS5Reply.ADDRESS_TYPE_NOT_SUPPORTED, 0, 1, 0, 0, 0, 0, 0, 0]))
            return
        
        # Parse port
        port_data = client_sock.recv(2)
        if len(port_data) < 2:
            return
        port = struct.unpack('>H', port_data)[0]
        
        # Connect through tunnel
        remote_sock = None
        try:
            if self.tunnel_handler:
                remote_sock = self.tunnel_handler(host, port)
            else:
                # Direct connection (fallback)
                remote_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                remote_sock.settimeout(10)
                remote_sock.connect((host, port))
                remote_sock.settimeout(None)
            
            # Send success reply
            bind_addr = remote_sock.getsockname()
            if len(bind_addr) == 2:  # IPv4
                reply = bytes([5, SOCKS5Reply.SUCCESS, 0, SOCKS5AddressType.IPV4])
                reply += socket.inet_aton(bind_addr[0])
                reply += struct.pack('>H', bind_addr[1])
            else:  # IPv6
                reply = bytes([5, SOCKS5Reply.SUCCESS, 0, SOCKS5AddressType.IPV6])
                reply += socket.inet_pton(socket.AF_INET6, bind_addr[0])
                reply += struct.pack('>H', bind_addr[1])
            client_sock.sendall(reply)
            
            # Forward data
            self._forward_data(client_sock, remote_sock)
            
        except Exception as e:
            logger.debug(f"Connection failed: {e}")
            # Send failure reply
            client_sock.sendall(bytes([5, SOCKS5Reply.CONNECTION_REFUSED, 0, 1, 0, 0, 0, 0, 0, 0]))
        finally:
            if remote_sock:
                try:
                    remote_sock.close()
                except Exception:
                    pass
    
    def _handle_http(self, client_sock: socket.socket) -> None:
        """Handle HTTP CONNECT method"""
        # Read HTTP request
        request_line = b""
        while True:
            chunk = client_sock.recv(1)
            if not chunk:
                return
            request_line += chunk
            if request_line.endswith(b"\r\n"):
                break
        
        # Parse CONNECT request
        try:
            line = request_line.decode('utf-8', errors='ignore').strip()
            if not line.startswith("CONNECT "):
                # Not a CONNECT request, send error
                response = b"HTTP/1.1 405 Method Not Allowed\r\n\r\n"
                client_sock.sendall(response)
                return
            
            parts = line.split()
            if len(parts) < 2:
                return
            
            target = parts[1]
            if ":" not in target:
                return
            
            host, port_str = target.rsplit(":", 1)
            port = int(port_str)
            
            # Connect through tunnel
            remote_sock = None
            try:
                if self.tunnel_handler:
                    remote_sock = self.tunnel_handler(host, port)
                else:
                    # Direct connection (fallback)
                    remote_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    remote_sock.settimeout(10)
                    remote_sock.connect((host, port))
                    remote_sock.settimeout(None)
                
                # Send success response
                response = b"HTTP/1.1 200 Connection Established\r\n\r\n"
                client_sock.sendall(response)
                
                # Forward data
                self._forward_data(client_sock, remote_sock)
                
            except Exception as e:
                logger.debug(f"Connection failed: {e}")
                response = b"HTTP/1.1 502 Bad Gateway\r\n\r\n"
                client_sock.sendall(response)
            finally:
                if remote_sock:
                    try:
                        remote_sock.close()
                    except Exception:
                        pass
        
        except Exception as e:
            logger.debug(f"HTTP parsing error: {e}")
    
    def _forward_data(self, client_sock: socket.socket, remote_sock: socket.socket) -> None:
        """Forward data bidirectionally"""
        try:
            while self._running:
                # Check if either side is closed
                if client_sock.fileno() == -1 or remote_sock.fileno() == -1:
                    break
                
                # Use select to wait for data
                r, w, x = select.select([client_sock, remote_sock], [], [], 0.1)
                
                if not r:
                    continue
                
                # Forward from client to remote
                if client_sock in r:
                    try:
                        data = client_sock.recv(8192)
                        if len(data) == 0:
                            break
                        remote_sock.sendall(data)
                    except (socket.error, OSError):
                        break
                
                # Forward from remote to client
                if remote_sock in r:
                    try:
                        data = remote_sock.recv(8192)
                        if len(data) == 0:
                            break
                        client_sock.sendall(data)
                    except (socket.error, OSError):
                        break
        
        except Exception:
            pass
