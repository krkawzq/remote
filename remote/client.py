from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Literal, Tuple
import paramiko
from pathlib import Path


@dataclass
class ClientConfig:
    host: str
    user: str
    port: int = 22
    auth_method: Literal["password", "key"] = "password"
    password: Optional[str] = None
    key_path: Optional[str] = None
    timeout: int = 10  # SSH connection timeout (seconds)


class RemoteClient:
    """
    Professional wrapper for Paramiko SSHClient:
    - Explicitly save host / user / port (paramiko 4.x no longer saves them)
    - Support password and key authentication
    - Auto-load RSA / Ed25519 private keys
    - Provide exec / sftp helper methods
    - Support with context management
    """
    def __init__(
        self,
        host: str,
        user: str,
        port: int = 22,
        auth_method: Literal["password", "key"] = "password",
        password: Optional[str] = None,
        key_path: Optional[str] = None,
        timeout: int = 10,
    ) -> None:
        """
        Accept parameters directly for initialization, not a ClientConfig object
        """
        self.config = ClientConfig(
            host=host,
            user=user,
            port=port,
            auth_method=auth_method,
            password=password,
            key_path=key_path,
            timeout=timeout,
        )

        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        # SFTP connection cache
        self._sftp: Optional[paramiko.SFTPClient] = None

    # --------------------
    # Connection management
    # --------------------
    def connect(self) -> None:
        """Public connection method"""
        self._connect()

    def _connect(self) -> None:
        """Internal connection implementation"""
        cfg = self.config

        if cfg.auth_method == "password":
            self.client.connect(
                hostname=cfg.host,
                port=cfg.port,
                username=cfg.user,
                password=cfg.password,
                timeout=cfg.timeout,
            )

        elif cfg.auth_method == "key":
            key = self._load_private_key(cfg.key_path)
            self.client.connect(
                hostname=cfg.host,
                port=cfg.port,
                username=cfg.user,
                pkey=key,
                timeout=cfg.timeout,
            )

        else:
            raise ValueError(f"Unsupported auth method: {cfg.auth_method}")

    # --------------------
    # Load private key
    # --------------------
    def _load_private_key(self, path: str) -> paramiko.PKey:
        """Auto-detect RSA and Ed25519"""
        p = Path(path).expanduser()

        try:
            return paramiko.Ed25519Key.from_private_key_file(str(p))
        except Exception:
            try:
                return paramiko.RSAKey.from_private_key_file(str(p))
            except Exception as e:
                raise RuntimeError(f"Failed to load private key at {p}") from e

    # --------------------
    # Helpers
    # --------------------
    def exec(self, cmd: str) -> Tuple[str, str]:
        """Execute command and return (stdout, stderr)"""
        stdin, stdout, stderr = self.client.exec_command(cmd)
        out = stdout.read().decode()
        err = stderr.read().decode()
        return out, err

    def exec_with_code(self, cmd: str) -> Tuple[str, str, int]:
        """Execute command and return (stdout, stderr, exit_code)"""
        stdin, stdout, stderr = self.client.exec_command(cmd)
        out = stdout.read().decode()
        err = stderr.read().decode()
        exit_code = stdout.channel.recv_exit_status()
        return out, err, exit_code

    def exec_with_code_streaming(
        self, cmd: str, stdout_callback=None, stderr_callback=None
    ) -> Tuple[str, str, int]:
        """
        Execute command with real-time output, return (stdout, stderr, exit_code)
        
        Args:
            cmd: Command to execute
            stdout_callback: stdout output callback function, receives (data: str) -> None
            stderr_callback: stderr output callback function, receives (data: str) -> None
        
        Returns:
            (stdout, stderr, exit_code)
        """
        import sys
        import time
        
        stdin, stdout, stderr = self.client.exec_command(cmd)
        
        out_buf = []
        err_buf = []
        
        # Polling method to read output in real-time
        while not stdout.channel.exit_status_ready():
            has_output = False
            
            # Read stdout
            if stdout.channel.recv_ready():
                data = stdout.channel.recv(4096).decode('utf-8', errors='replace')
                if data:
                    has_output = True
                    out_buf.append(data)
                    if stdout_callback:
                        stdout_callback(data)
                    else:
                        sys.stdout.write(data)
                        sys.stdout.flush()
            
            # Read stderr
            if stderr.channel.recv_stderr_ready():
                data = stderr.channel.recv_stderr(4096).decode('utf-8', errors='replace')
                if data:
                    has_output = True
                    err_buf.append(data)
                    if stderr_callback:
                        stderr_callback(data)
                    else:
                        sys.stderr.write(data)
                        sys.stderr.flush()
            
            # If no output, sleep briefly to avoid CPU spinning
            if not has_output:
                time.sleep(0.01)
        
        # Read remaining data
        while stdout.channel.recv_ready():
            data = stdout.channel.recv(4096).decode('utf-8', errors='replace')
            if data:
                out_buf.append(data)
                if stdout_callback:
                    stdout_callback(data)
                else:
                    sys.stdout.write(data)
                    sys.stdout.flush()
        
        while stderr.channel.recv_stderr_ready():
            data = stderr.channel.recv_stderr(4096).decode('utf-8', errors='replace')
            if data:
                err_buf.append(data)
                if stderr_callback:
                    stderr_callback(data)
                else:
                    sys.stderr.write(data)
                    sys.stderr.flush()
        
        exit_code = stdout.channel.recv_exit_status()
        return ''.join(out_buf), ''.join(err_buf), exit_code

    def open_sftp(self) -> paramiko.SFTPClient:
        """Return SFTP client, reuse existing connection"""
        # Check if connection is valid
        if self._sftp is None:
            self._sftp = self.client.open_sftp()
        else:
            try:
                # Check if channel is still valid
                channel = self._sftp.get_channel()
                if channel is None or channel.closed:
                    self._sftp = self.client.open_sftp()
            except Exception:
                # If check fails, recreate connection
                self._sftp = self.client.open_sftp()
        return self._sftp

    # --------------------
    # Context manager
    # --------------------
    def __enter__(self) -> RemoteClient:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self._sftp:
            try:
                self._sftp.close()
            except Exception:
                pass
        self.client.close()
