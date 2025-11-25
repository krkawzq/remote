"""
Sync CLI commands
"""
import typer
from pathlib import Path
from typing import Optional, Dict, Any

from rich.console import Console

from ...core.logging import get_logger, get_stdout_console, get_stderr_console
from ...core.exceptions import SyncError, ConfigError
from ...core.constants import DEFAULT_SSH_PORT, DEFAULT_SSH_TIMEOUT
from ...core import load_ssh_config
from ...domain.sync import SyncService
from ...adapters.cli.connection import RemoteConnectionFactory
from ...adapters.cli.prompts import RichPromptProvider
from ...adapters.config.loader import ConfigLoader
from ...adapters.config.sync_parser import (
    resolve_home_dirs,
    parse_file_configs,
    parse_block_configs,
    parse_script_configs,
    parse_global_env,
)

logger = get_logger(__name__)
stdout_console = get_stdout_console()
stderr_console = get_stderr_console()
prompt_provider = RichPromptProvider()


def register_sync_command(app: typer.Typer) -> None:
    """Register sync command directly on the main app"""
    app.command(name="sync")(sync_run)


def sync_run(
    config_path: str = typer.Argument(..., help="Configuration file path (TOML)"),
    ssh_config: Optional[str] = typer.Option(
        None, "--ssh-config", help="Save SSH configuration to ~/.ssh/config with specified Host name"
    ),
    force_init: bool = typer.Option(
        False, "--force-init", help="Force init mode (treat as first connection, execute init scripts and sync init files)"
    ),
):
    """
    Sync remote server configuration
    
    Examples: 
        remote sync config.toml
        remote sync config.toml --ssh-config machine-name
        remote sync config.toml --force-init  # Force init mode (execute init scripts/files)
    """
    try:
        # Load configuration
        config_loader = ConfigLoader()
        path = Path(config_path).expanduser()
        if not path.exists():
            stderr_console.print(f"[red]Error:[/red] Configuration file not found: {config_path}")
            raise typer.Exit(1)
        
        cfg = config_loader.load(toml_path=path)
        
        # Resolve connection parameters
        params = _resolve_connection_params(cfg)
        
        # Resolve directory configuration
        block_home, script_home = resolve_home_dirs(cfg, path)
        
        # Parse configurations
        file_items = parse_file_configs(cfg)
        block_groups = parse_block_configs(cfg, block_home)
        global_env = parse_global_env(cfg)
        
        # Create connection factory
        connection_factory = RemoteConnectionFactory()
        
        # Create sync service with callbacks
        service = SyncService(
            connection_factory=connection_factory,
            on_connected=lambda host, port: stdout_console.print(
                f"[green]✓[/green] Connected to [cyan]{params['user']}@{host}:{port}[/cyan]"
            ),
            on_key_generated=lambda key_path: stdout_console.print(
                f"[cyan]ℹ[/cyan] Generating SSH key pair: {key_path}"
            ),
            on_key_added=lambda remote_path: stdout_console.print(
                f"[green]✓[/green] Public key added to {remote_path}"
            ),
            on_first_connect=lambda: stdout_console.print(
                "[cyan]ℹ[/cyan] First connection, registering local machine info..."
            ),
            on_script_skip=lambda script_path, reason: stdout_console.print(
                f"[yellow]⊘[/yellow] Skipped: {script_path}"
            ),
            on_script_exec=lambda script_path: stdout_console.print(
                f"[cyan]▶[/cyan] Executing: {script_path}"
            ),
            on_complete=lambda: stdout_console.print(
                "[green]✓[/green] Sync completed successfully"
            ),
        )
        
        # Parse scripts (is_first will be determined by service, or forced by --force-init)
        scripts = parse_script_configs(cfg, script_home, False)
        
        # Execute sync
        used_key_fallback = service.sync(
            connection_params=params,
            file_items=file_items,
            block_groups=block_groups,
            scripts=scripts,
            global_env=global_env,
            add_authorized_key_flag=params.get("add_authorized_key", False),
            force_init=force_init,
        )
        
        # Save SSH config if requested
        if ssh_config:
            _save_ssh_config(ssh_config, params)
    
    except SyncError as e:
        stderr_console.print(f"[red]Sync Error:[/red] {e}")
        raise typer.Exit(1)
    except ConfigError as e:
        stderr_console.print(f"[red]Config Error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        logger.exception("Failed to sync")
        stderr_console.print(f"[red]Error:[/red] Failed to sync: {e}")
        raise typer.Exit(1)


def _resolve_connection_params(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Resolve remote connection parameters from TOML configuration.
    
    Supports:
    - ssh_config: Load configuration from ~/.ssh/config
    - host/user/port/password/key: Direct configuration
    - Missing parameters will prompt user for input
    """
    from ...core.constants import DEFAULT_SSH_PORT, DEFAULT_SSH_TIMEOUT
    
    params: Dict[str, Any] = {}

    # Load from ssh_config if specified
    if "ssh_config" in cfg:
        entry = load_ssh_config(cfg["ssh_config"])
        params.update(entry)

    # Read from TOML configuration if present
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
        params["host"] = prompt_provider.prompt("Enter remote host address")
    if not params.get("user"):
        params["user"] = prompt_provider.prompt("Enter SSH username", default="root")
    if "port" not in params:
        port_input = prompt_provider.prompt("Enter SSH port", default=str(DEFAULT_SSH_PORT))
        params["port"] = int(port_input) if port_input else DEFAULT_SSH_PORT
    else:
        params["port"] = int(params["port"])
    
    # Prompt for password if neither password nor key is provided
    if not params.get("password") and not params.get("key"):
        password_input = prompt_provider.prompt(
            "Enter SSH password",
            password=True,
            default=""
        )
        params["password"] = password_input if password_input else None

    return params


def _save_ssh_config(name: str, params: Dict[str, Any]) -> None:
    """Save SSH configuration to ~/.ssh/config"""
    from ...core.constants import SSH_CONFIG_PATH, SSH_CONFIG_MODE
    import paramiko
    
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
        key_to_use = params['key']
    elif params.get('add_authorized_key'):
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
    stdout_console.print(f"[green]✓[/green] SSH configuration saved to {SSH_CONFIG_PATH}: Host {name}")

