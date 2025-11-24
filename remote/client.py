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


class RemoteClient:
    """
    专业封装 Paramiko SSHClient：
    - 显式保存 host / user / port（paramiko 4.x 不再保存）
    - 支持 password 和 key 登录
    - 自动加载 RSA / Ed25519 私钥
    - 提供 exec / sftp 辅助方法
    - 支持 with 上下文管理
    """
    def __init__(
        self,
        host: str,
        user: str,
        port: int = 22,
        auth_method: Literal["password", "key"] = "password",
        password: Optional[str] = None,
        key_path: Optional[str] = None,
    ) -> None:
        """
        直接接受参数初始化，而不是 ClientConfig 对象
        """
        self.config = ClientConfig(
            host=host,
            user=user,
            port=port,
            auth_method=auth_method,
            password=password,
            key_path=key_path,
        )

        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        # SFTP 连接缓存
        self._sftp: Optional[paramiko.SFTPClient] = None

    # --------------------
    # Connection management
    # --------------------
    def connect(self) -> None:
        """公开的连接方法"""
        self._connect()

    def _connect(self) -> None:
        """内部连接实现"""
        cfg = self.config

        if cfg.auth_method == "password":
            self.client.connect(
                hostname=cfg.host,
                port=cfg.port,
                username=cfg.user,
                password=cfg.password,
            )

        elif cfg.auth_method == "key":
            key = self._load_private_key(cfg.key_path)
            self.client.connect(
                hostname=cfg.host,
                port=cfg.port,
                username=cfg.user,
                pkey=key,
            )

        else:
            raise ValueError(f"Unsupported auth method: {cfg.auth_method}")

    # --------------------
    # Load private key
    # --------------------
    def _load_private_key(self, path: str) -> paramiko.PKey:
        """自动探测 RSA 和 Ed25519"""
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
        """执行命令并返回 (stdout, stderr)"""
        stdin, stdout, stderr = self.client.exec_command(cmd)
        out = stdout.read().decode()
        err = stderr.read().decode()
        return out, err

    def exec_with_code(self, cmd: str) -> Tuple[str, str, int]:
        """执行命令并返回 (stdout, stderr, exit_code)"""
        stdin, stdout, stderr = self.client.exec_command(cmd)
        out = stdout.read().decode()
        err = stderr.read().decode()
        exit_code = stdout.channel.recv_exit_status()
        return out, err, exit_code

    def exec_with_code_streaming(
        self, cmd: str, stdout_callback=None, stderr_callback=None
    ) -> Tuple[str, str, int]:
        """
        执行命令并实时输出，返回 (stdout, stderr, exit_code)
        
        Args:
            cmd: 要执行的命令
            stdout_callback: stdout 输出回调函数，接收 (data: str) -> None
            stderr_callback: stderr 输出回调函数，接收 (data: str) -> None
        
        Returns:
            (stdout, stderr, exit_code)
        """
        import sys
        import time
        
        stdin, stdout, stderr = self.client.exec_command(cmd)
        
        out_buf = []
        err_buf = []
        
        # 轮询方式读取输出，实时显示
        while not stdout.channel.exit_status_ready():
            has_output = False
            
            # 读取 stdout
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
            
            # 读取 stderr
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
            
            # 如果没有输出，短暂休眠避免 CPU 空转
            if not has_output:
                time.sleep(0.01)
        
        # 读取剩余数据
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
        """返回 SFTP 客户端，复用已有连接"""
        if self._sftp is None or self._sftp.get_channel() is None:
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
