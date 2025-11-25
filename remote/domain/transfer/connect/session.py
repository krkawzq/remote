"""
Connect session management
"""
import os
from pathlib import Path
from typing import Optional

from .models import ConnectSession, ConnectConfig
from ....core.client import RemoteClient
from ....core.exceptions import ConnectionError
from ..parser import load_ssh_config


class ConnectSessionManager:
    """Manager for connect sessions"""
    
    @staticmethod
    def create_session(
        host: str,
        user: Optional[str] = None,
        port: Optional[int] = None,
        password: Optional[str] = None,
        key_file: Optional[str] = None,
        config: Optional[ConnectConfig] = None,
        prompt_password: bool = False,
    ) -> ConnectSession:
        """
        Create a new connect session.
        
        Args:
            host: Hostname or SSH config alias
            user: Username (optional, from SSH config if not provided)
            port: SSH port (optional, from SSH config if not provided)
            password: Password for authentication (optional)
            key_file: Path to SSH key file (optional)
            config: Connect configuration (optional, creates default if None)
        
        Returns:
            ConnectSession instance
        
        Raises:
            ConnectionError: If connection fails
        """
        # Load SSH config if host is an alias
        ssh_config = None
        try:
            ssh_config = load_ssh_config(host)
        except Exception:
            pass
        
        # Resolve connection parameters
        resolved_host = ssh_config.get("host", host) if ssh_config else host
        resolved_user = user or (ssh_config.get("user") if ssh_config else None) or os.getenv("USER", "root")
        resolved_port = port or (int(ssh_config.get("port", 22)) if ssh_config else 22)
        resolved_key_file = key_file or (ssh_config.get("key_file") if ssh_config else None)
        
        # Create client and connect with fallback to password
        client = None
        last_error = None
        
        # Strategy 1: Use provided password
        if password:
            try:
                client = RemoteClient(
                    host=resolved_host,
                    user=resolved_user,
                    port=resolved_port,
                    auth_method="password",
                    password=password,
                    timeout=config.timeout if config else 30,
                )
                client.connect()
            except Exception as e:
                last_error = e
                client = None
        
        # Strategy 2: Try provided key file
        if client is None and resolved_key_file:
            try:
                client = RemoteClient(
                    host=resolved_host,
                    user=resolved_user,
                    port=resolved_port,
                    auth_method="key",
                    key_path=resolved_key_file,
                    timeout=config.timeout if config else 30,
                )
                client.connect()
            except Exception as e:
                last_error = e
                client = None
                # If key failed and password not provided, fallback to password prompt
                if prompt_password:
                    import getpass
                    try:
                        password_str = getpass.getpass(f"Key authentication failed. Password for {resolved_user}@{resolved_host}: ")
                        client = RemoteClient(
                            host=resolved_host,
                            user=resolved_user,
                            port=resolved_port,
                            auth_method="password",
                            password=password_str,
                            timeout=config.timeout if config else 30,
                        )
                        client.connect()
                    except Exception as e2:
                        last_error = e2
                        client = None
        
        # Strategy 3: Try default SSH keys (only if no key was explicitly provided)
        if client is None and not resolved_key_file:
            ssh_dir = Path.home() / ".ssh"
            default_keys = [
                ssh_dir / "id_ed25519",  # Ed25519 (preferred)
                ssh_dir / "id_rsa",      # RSA
                ssh_dir / "id_ecdsa",    # ECDSA
            ]
            
            found_key = None
            for key_path in default_keys:
                if key_path.exists():
                    found_key = key_path
                    break
            
            if found_key:
                try:
                    client = RemoteClient(
                        host=resolved_host,
                        user=resolved_user,
                        port=resolved_port,
                        auth_method="key",
                        key_path=str(found_key),
                        timeout=config.timeout if config else 30,
                    )
                    client.connect()
                except Exception as e:
                    last_error = e
                    client = None
                    # If default key failed silently, fallback to password prompt
                    # Don't show "key failed" message since user didn't specify a key
                    if prompt_password:
                        import getpass
                        try:
                            password_str = getpass.getpass(f"Password for {resolved_user}@{resolved_host}: ")
                            client = RemoteClient(
                                host=resolved_host,
                                user=resolved_user,
                                port=resolved_port,
                                auth_method="password",
                                password=password_str,
                                timeout=config.timeout if config else 30,
                            )
                            client.connect()
                        except Exception as e2:
                            last_error = e2
                            client = None
        
        # Strategy 4: Prompt for password if no authentication method worked
        if client is None and prompt_password:
            import getpass
            try:
                password_str = getpass.getpass(f"Password for {resolved_user}@{resolved_host}: ")
                client = RemoteClient(
                    host=resolved_host,
                    user=resolved_user,
                    port=resolved_port,
                    auth_method="password",
                    password=password_str,
                    timeout=config.timeout if config else 30,
                )
                client.connect()
            except Exception as e:
                last_error = e
                client = None
        
        # If all strategies failed, raise error
        if client is None:
            if last_error:
                raise ConnectionError(f"Failed to connect to {resolved_host}: {last_error}")
            else:
                raise ConnectionError(
                    "No authentication method provided. Use --password or ensure SSH key is configured."
                )
        
        # Get initial working directories
        local_cwd = Path.cwd()
        
        # Get remote working directory
        try:
            stdout, _ = client.exec("pwd")
            remote_cwd = stdout.strip()
        except Exception:
            remote_cwd = "~"
        
        # Create config if not provided
        if config is None:
            config = ConnectConfig()
        
        # Create session
        session = ConnectSession(
            host=resolved_host,
            user=resolved_user,
            port=resolved_port,
            client=client,
            local_cwd=local_cwd,
            remote_cwd=remote_cwd,
            config=config,
            last_cd_was_remote=True,  # Default to remote context after connection
        )
        
        return session
    
    @staticmethod
    def close_session(session: ConnectSession) -> None:
        """
        Close a connect session.
        
        Args:
            session: Session to close
        """
        if session.client:
            try:
                session.client.close()
            except Exception:
                pass

