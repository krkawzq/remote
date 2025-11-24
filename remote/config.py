"""
Configuration parsing and management
"""
import typer
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from .client import RemoteClient
from .sync.file import FileSync
from .sync.block import TextBlock, BlockGroup
from .sync.script import ScriptExec, GlobalEnv
from .utils import load_ssh_config
from .constants import (
    DEFAULT_SSH_PORT,
    DEFAULT_SSH_TIMEOUT,
    DEFAULT_INTERPRETER,
    DEFAULT_BLOCK_HOME,
    DEFAULT_SCRIPT_HOME,
)
from .exceptions import ConfigError


# ============================================================
# Connection Parameters
# ============================================================

def resolve_connection_params(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Resolve remote connection parameters from TOML configuration.
    
    Supports:
    - ssh_config: Load configuration from ~/.ssh/config
    - host/user/port/password/key: Direct configuration
    - Missing parameters will prompt user for input
    
    Args:
        cfg: TOML configuration dictionary
    
    Returns:
        Connection parameters dictionary
    """
    params: Dict[str, Any] = {}

    # Load from ssh_config if specified
    if "ssh_config" in cfg:
        entry = load_ssh_config(cfg["ssh_config"])
        params.update(entry)

    # Read from TOML configuration if present
    # Note: Don't set defaults here, let interactive prompts handle them
    if "host" in cfg:
        params["host"] = cfg["host"]
    if "user" in cfg:
        params["user"] = cfg["user"]
    if "port" in cfg:
        params["port"] = cfg["port"]
    if "key" in cfg:
        params["key"] = cfg["key"]
    elif "key_file" in cfg:
        params["key"] = cfg["key_file"]
    if "password" in cfg:
        params["password"] = cfg["password"]
    if "add_authorized_key" in cfg:
        params["add_authorized_key"] = cfg["add_authorized_key"]
    params["timeout"] = cfg.get("timeout", DEFAULT_SSH_TIMEOUT)

    # Prompt user for missing fields with defaults
    if not params.get("host"):
        params["host"] = typer.prompt("Enter remote host address")
    if not params.get("user"):
        params["user"] = typer.prompt("Enter SSH username", default="root")
    if "port" not in params:
        port_input = typer.prompt("Enter SSH port", default=str(DEFAULT_SSH_PORT))
        params["port"] = int(port_input) if port_input else DEFAULT_SSH_PORT
    else:
        # Ensure port is an integer if already set
        params["port"] = int(params["port"])
    
    # Prompt for password if neither password nor key is provided
    if not params.get("password") and not params.get("key"):
        password_input = typer.prompt("Enter SSH password (press Enter to skip)", hide_input=True, default="")
        # If user presses Enter (empty string), set to None
        params["password"] = password_input if password_input else None

    return params


def create_client(params: Dict[str, Any]) -> Tuple[RemoteClient, bool]:
    """
    Create and connect RemoteClient.
    
    If key authentication fails, fallback to password.
    
    Args:
        params: Connection parameters dictionary
    
    Returns:
        Tuple of (Connected RemoteClient instance, used_key_fallback)
        used_key_fallback: True if key auth was attempted but fell back to password
    
    Raises:
        Exception: If connection fails and no password fallback available
    """
    used_key_fallback = False
    
    # Try key authentication if key is specified
    if params.get("key"):
        client = RemoteClient(
            host=params["host"],
            user=params["user"],
            port=params["port"],
            auth_method="key",
            password=params.get("password"),
            key_path=params.get("key"),
            timeout=params.get("timeout", DEFAULT_SSH_TIMEOUT),
        )
        
        try:
            client.connect()
            return client, False
        except Exception:
            if params.get("password"):
                used_key_fallback = True
                typer.echo("[warn] Key authentication failed, trying password...")
            else:
                raise
    
    # Use password authentication
    client = RemoteClient(
        host=params["host"],
        user=params["user"],
        port=params["port"],
        auth_method="password",
        password=params.get("password"),
        timeout=params.get("timeout", DEFAULT_SSH_TIMEOUT),
    )
    client.connect()
    return client, used_key_fallback


# ============================================================
# Path Resolution
# ============================================================

def resolve_path_with_home(path: str, home_dir: Optional[str] = None) -> str:
    """
    Resolve path, relative to home_dir if provided.
    
    Absolute paths and paths starting with ~ are not modified.
    
    Args:
        path: Original path
        home_dir: Base directory (optional)
    
    Returns:
        Resolved path
    """
    if home_dir:
        if path.startswith('/') or path.startswith('~'):
            return path
        return str(Path(home_dir) / path)
    return path


def resolve_home_dirs(
    cfg: Dict[str, Any],
    config_file_path: Optional[Path]
) -> Tuple[str, str]:
    """
    Resolve block_home and script_home directory paths.
    
    Args:
        cfg: TOML configuration dictionary
        config_file_path: Configuration file path
    
    Returns:
        (block_home, script_home)
    """
    block_home = cfg.get("block_home", DEFAULT_BLOCK_HOME)
    script_home = cfg.get("script_home", DEFAULT_SCRIPT_HOME)
    
    if config_file_path:
        config_dir = config_file_path.parent
        if not Path(block_home).is_absolute():
            block_home = str(config_dir / block_home)
        if not Path(script_home).is_absolute():
            script_home = str(config_dir / script_home)
    
    return block_home, script_home


# ============================================================
# Configuration Parsing
# ============================================================

def parse_file_configs(cfg: Dict[str, Any]) -> List[FileSync]:
    """Parse file configuration items"""
    if "file" not in cfg:
        return []
    
    return [
        FileSync(
            src=item["src"],
            dist=item["dist"],
            mode=item.get("mode", "sync"),
        )
        for item in cfg["file"]
    ]


def parse_block_configs(
    cfg: Dict[str, Any],
    block_home: str
) -> List[BlockGroup]:
    """Parse block configuration items"""
    if "block" not in cfg:
        return []
    
    groups = []
    block_configs = cfg["block"]
    if isinstance(block_configs, dict):
        block_configs = [block_configs]
    
    for group_cfg in block_configs:
        blocks = []
        for blk_cfg in group_cfg["blocks"]:
            src = blk_cfg["src"]
            src_list = (
                [resolve_path_with_home(src, block_home)]
                if isinstance(src, str)
                else [resolve_path_with_home(s, block_home) for s in src]
            )
            
            blocks.append(
                TextBlock(
                    src=src_list,
                    mode=blk_cfg.get("mode", "update"),
                )
            )
        
        groups.append(
            BlockGroup(
                dist=group_cfg["dist"],
                mode=group_cfg.get("mode", "incremental"),
                blocks=blocks,
            )
        )
    
    return groups


def parse_script_configs(
    cfg: Dict[str, Any],
    script_home: str,
    is_first: bool
) -> List[ScriptExec]:
    """Parse script configuration items"""
    if "script" not in cfg:
        return []
    
    scripts = []
    for sc_cfg in cfg["script"]:
        script_mode = sc_cfg.get("mode", "always")
        
        # Skip if init mode and not first connection
        if script_mode == "init" and not is_first:
            typer.echo(f"[script] Skipped (init mode, not first connection): {sc_cfg['src']}")
            continue
        
        script_src = resolve_path_with_home(sc_cfg["src"], script_home)
        scripts.append(
            ScriptExec(
                src=script_src,
                mode=script_mode,
                exec_mode=sc_cfg.get("exec_mode", "exec"),
                interpreter=sc_cfg.get("interpreter", None),
                flags=sc_cfg.get("flags", None),
                args=sc_cfg.get("args", None),
                interactive=sc_cfg.get("interactive", False),
                allow_fail=sc_cfg.get("allow_fail", False),
            )
        )
    
    return scripts


def parse_global_env(cfg: Dict[str, Any]) -> GlobalEnv:
    """Parse global environment configuration"""
    return GlobalEnv(
        interpreter=cfg.get("interpreter", DEFAULT_INTERPRETER),
        flags=cfg.get("interpreter_flags", []),
    )

