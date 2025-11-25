"""
Core utility functions
"""
import paramiko
from pathlib import Path
from typing import Dict, Any, Tuple, TYPE_CHECKING

from .constants import SSH_CONFIG_PATH
from .exceptions import ConfigError

if TYPE_CHECKING:
    from .client import RemoteClient


# ============================================================
# SSH Config Management
# ============================================================

def load_ssh_config(hostname: str) -> Dict[str, Any]:
    """
    Load configuration for specified Host from ~/.ssh/config.
    
    Args:
        hostname: Host name in SSH configuration
    
    Returns:
        Dictionary containing host, user, port, key_file
    
    Raises:
        ConfigError: If ~/.ssh/config doesn't exist
    """
    config_path = Path(SSH_CONFIG_PATH).expanduser()
    if not config_path.exists():
        raise ConfigError(f"{SSH_CONFIG_PATH} does not exist")

    ssh_config = paramiko.SSHConfig.from_path(str(config_path))
    entry = ssh_config.lookup(hostname)

    return {
        "host": entry.get("hostname", hostname),
        "user": entry.get("user", None),
        "port": int(entry.get("port", 22)),
        "key_file": entry.get("identityfile", [None])[0],
    }


# ============================================================
# Path Resolution Utilities
# ============================================================

def is_remote_path(path: str) -> bool:
    """Check if path is a remote path (starts with :)"""
    return path.startswith(":")


def resolve_local_path(path: str) -> Path:
    """Resolve local path, expand ~ and other symbols"""
    return Path(path).expanduser()


def resolve_remote_path(client: "RemoteClient", path: str) -> str:
    """
    Resolve remote path, expand ~ to remote $HOME
    
    Args:
        client: RemoteClient instance
        path: Remote path, must start with :
    
    Returns:
        Resolved absolute path
    
    Raises:
        AssertionError: If path doesn't start with :
    """
    assert path.startswith(":"), f"Remote path must start with ':', got: {path}"
    
    raw_path = path[1:]  # Remove prefix :
    
    if raw_path.startswith("~"):
        out, _ = client.exec("printf $HOME")
        home = out.strip() or "/root"
        return home + raw_path[1:]  # Remove ~
    
    return raw_path


# ============================================================
# SSH Key Management
# ============================================================

def generate_ssh_key_pair(key_path: Path) -> Tuple[str, str]:
    """
    Generate Ed25519 SSH key pair.
    
    Args:
        key_path: Path to private key file (public key will be key_path + '.pub')
    
    Returns:
        (private_key_path, public_key_path) as strings
    """
    key_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Generate Ed25519 key
    key = paramiko.Ed25519Key.generate()
    
    # Save private key
    key.write_private_key_file(str(key_path))
    key_path.chmod(0o600)
    
    # Save public key
    pub_key_path = Path(str(key_path) + '.pub')
    pub_key_path.write_text(f"{key.get_name()} {key.get_base64()} remote@remote\n")
    pub_key_path.chmod(0o644)
    
    return str(key_path), str(pub_key_path)


def add_authorized_key(client: "RemoteClient", public_key_path: str) -> None:
    """
    Add public key to remote ~/.ssh/authorized_keys.
    
    Args:
        client: RemoteClient instance (must be connected)
        public_key_path: Local path to public key file
    """
    pub_key_path = Path(public_key_path).expanduser()
    if not pub_key_path.exists():
        raise FileNotFoundError(f"Public key not found: {pub_key_path}")
    
    # Read public key content
    pub_key_content = pub_key_path.read_text().strip()
    
    # Get remote authorized_keys path
    out, _ = client.exec("printf $HOME")
    home = out.strip() or "/root"
    remote_auth_keys = f"{home}/.ssh/authorized_keys"
    
    # Ensure .ssh directory exists
    client.exec(f"mkdir -p {home}/.ssh")
    client.exec(f"chmod 700 {home}/.ssh")
    
    # Check if key already exists
    out, _ = client.exec(f"grep -Fx '{pub_key_content}' {remote_auth_keys} 2>/dev/null || echo ''")
    if out.strip():
        # Key already exists
        return
    
    # Append public key
    client.exec(f"echo '{pub_key_content}' >> {remote_auth_keys}")
    client.exec(f"chmod 600 {remote_auth_keys}")
