"""
Shared utility functions
"""
import typer
import paramiko
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Any, Tuple

if TYPE_CHECKING:
    from .client import RemoteClient


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
# Logging Utilities
# ============================================================

def log_info(message: str) -> None:
    """Output info log"""
    print(message)


def log_success(message: str) -> None:
    """Output success log"""
    print(f"[✓] {message}")


def log_error(message: str) -> None:
    """Output error log"""
    print(f"[✗] {message}")


def log_warn(message: str) -> None:
    """Output warning log"""
    print(f"[!] {message}")


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
    from .constants import SSH_CONFIG_PATH
    from .exceptions import ConfigError
    
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
        raise FileNotFoundError(f"Public key not found: {public_key_path}")
    
    # Read public key content
    pub_key_content = pub_key_path.read_text().strip()
    
    # Get remote authorized_keys path
    out, _ = client.exec("printf $HOME")
    home = out.strip() or "/root"
    remote_auth_keys = f"{home}/.ssh/authorized_keys"
    
    # Ensure .ssh directory exists
    client.exec(f"mkdir -p {home}/.ssh")
    client.exec(f"chmod 700 {home}/.ssh")
    
    # Check if key already exists (check by the key content itself, not just the base64 part)
    out, _ = client.exec(f"grep -Fx '{pub_key_content}' {remote_auth_keys} 2>/dev/null || echo ''")
    if out.strip():
        typer.echo(f"[info] Public key already exists in {remote_auth_keys}")
        return
    
    # Append public key
    client.exec(f"echo '{pub_key_content}' >> {remote_auth_keys}")
    client.exec(f"chmod 600 {remote_auth_keys}")
    typer.echo(f"[✓] Public key added to {remote_auth_keys}")


def save_ssh_config(name: str, params: Dict[str, Any], used_key_fallback: bool = False) -> None:
    """
    Save SSH configuration to ~/.ssh/config.
    
    If a Host with the same name already exists, the old configuration
    will be deleted before adding the new one.
    
    Args:
        name: Host name in SSH config
        params: Connection parameters dictionary containing host, user, port, key
        used_key_fallback: Whether key authentication was attempted but fell back to password
    """
    from .constants import SSH_CONFIG_PATH, SSH_CONFIG_MODE
    
    ssh_config_path = Path(SSH_CONFIG_PATH).expanduser()
    ssh_config_path.parent.mkdir(parents=True, exist_ok=True)
    ssh_config_path.touch(mode=SSH_CONFIG_MODE)
    
    # Read existing configuration
    content = ssh_config_path.read_text() if ssh_config_path.exists() else ""
    
    # Remove old Host configuration block with the same name
    lines = content.split('\n')
    new_lines = []
    skip = False
    
    for line in lines:
        # Check if this is the start of target Host
        if line.strip() == f'Host {name}':
            skip = True
            continue
        
        # If skipping, check if this is the start of next Host
        if skip:
            if line.strip().startswith('Host '):
                skip = False
            else:
                continue
        
        new_lines.append(line)
    
    # Determine which key to use for SSH config
    key_to_use = None
    if params.get('key'):
        # Use specified key (even if fallback happened - key might work next time)
        key_to_use = params['key']
    elif params.get('add_authorized_key'):
        # If add_authorized_key is set but no key specified, use the default key
        default_key = Path.home() / ".ssh" / "id_ed25519_remote"
        if default_key.exists():
            key_to_use = str(default_key)
    
    # Add new configuration
    new_lines.append(f"\nHost {name}")
    new_lines.append(f"    HostName {params['host']}")
    new_lines.append(f"    User {params['user']}")
    new_lines.append(f"    Port {params['port']}")
    if key_to_use:
        key_path = str(Path(key_to_use).expanduser())
        new_lines.append(f"    IdentityFile {key_path}")
        new_lines.append(f"    IdentitiesOnly yes")
    new_lines.append("")
    
    # Write to file
    ssh_config_path.write_text('\n'.join(new_lines))
    typer.echo(f"[✓] SSH configuration saved to {SSH_CONFIG_PATH}: Host {name}")

