"""
CLI entry point and sync execution logic
"""
import typer
import tomllib
from pathlib import Path
from typing import Optional

from .client import RemoteClient
from .system import register_machine, update_last_sync, is_first_connect
from .sync.file import sync_files
from .sync.block import sync_block_groups
from .sync.script import run_script
from .config import (
    resolve_connection_params,
    create_client,
    resolve_home_dirs,
    parse_file_configs,
    parse_block_configs,
    parse_script_configs,
    parse_global_env,
)
from .utils import save_ssh_config, generate_ssh_key_pair, add_authorized_key
from .exceptions import SyncError


# ============================================================
# CLI App Setup
# ============================================================

app = typer.Typer(
    add_completion=False,
    help="SSH remote connection management tool",
    no_args_is_help=True,
)


@app.callback()
def main():
    """
    remote - SSH remote connection management tool
    
    Use subcommands to perform different operations:
    - sync: Sync remote server configuration
    """
    pass


# ============================================================
# Sync Execution
# ============================================================

def run_sync_with_config(
    cfg: dict,
    params: dict,
    config_file_path: Optional[Path] = None
) -> bool:
    """
    Execute sync tasks based on configuration file.
    
    Process:
    1. Parse configuration and paths
    2. Establish SSH connection
    3. Check system status
    4. Sync files (auto-create missing directories)
    5. Sync blocks
    6. Execute scripts
    7. Update sync time
    
    Args:
        cfg: TOML configuration dictionary
        params: Connection parameters dictionary (already resolved)
        config_file_path: Configuration file path for resolving relative paths
    
    Returns:
        used_key_fallback: True if key authentication was attempted but fell back to password
    
    Raises:
        SyncError: If an error occurs during sync
    """
    # Resolve directory configuration
    block_home, script_home = resolve_home_dirs(cfg, config_file_path)
    
    # Step 1: Establish SSH connection
    client, used_key_fallback = create_client(params)
    typer.echo(f"[connected] {params['user']}@{params['host']}:{params['port']}")
    
    # Step 1.5: Handle add_authorized_key if specified
    if params.get("add_authorized_key"):
        # Determine which key to use
        if params.get("key"):
            # Use specified key
            key_path = Path(params["key"]).expanduser()
            pub_key_path = Path(str(key_path) + ".pub")
        else:
            # Use default key
            default_key = Path.home() / ".ssh" / "id_ed25519_remote"
            if not default_key.exists():
                typer.echo(f"[info] Generating SSH key pair: {default_key}")
                generate_ssh_key_pair(default_key)
            key_path = default_key
            pub_key_path = Path(str(default_key) + ".pub")
        
        # Add public key to remote authorized_keys
        add_authorized_key(client, str(pub_key_path))
    
    # Step 2: System check (check only, don't register)
    is_first = is_first_connect(client)
    
    # Step 3: Global environment configuration
    global_env = parse_global_env(cfg)
    
    # Use try-except to ensure registration only on complete success
    try:
        # Step 4: File sync (sync files first, auto-create missing directories)
        file_items = parse_file_configs(cfg)
        if file_items:
            sync_files(file_items, client)
        
        # Step 5: Block sync
        block_groups = parse_block_configs(cfg, block_home)
        if block_groups:
            sync_block_groups(block_groups, client)
        
        # Step 6: Script execution
        scripts = parse_script_configs(cfg, script_home, is_first)
        for script in scripts:
            typer.echo(f"[script] Executing: {script.src}")
            out, err, code = run_script(script, client, global_env)
            
            # Display error message if any
            if err and code != 0:
                typer.echo(f"[script] Error output:\n{err}", err=True)
            if code != 0 and not script.allow_fail:
                # If script fails and failure is not allowed, raise exception
                raise SyncError(f"Script execution failed: {script.src} (exit code: {code})")
        
        # Step 7: All operations successful, register machine and update sync time
        if is_first:
            typer.echo("[system] First connection, registering local machine info...")
            register_machine(client, meta={"client": "remote"})
        
        update_last_sync(client)
        typer.echo("[done] remote sync completed")
        return used_key_fallback
    
    except Exception as e:
        # If any operation fails, don't register machine, re-raise exception
        if is_first:
            typer.echo("[warn] Sync failed, not registered as first connection, init operations will be retried next time")
        if isinstance(e, SyncError):
            raise
        raise SyncError(f"Sync failed: {e}") from e


# ============================================================
# CLI Commands
# ============================================================

@app.command(name="sync")
def sync(
    config_path: str = typer.Argument(..., help="Configuration file path"),
    ssh_config: Optional[str] = typer.Option(
        None, "--ssh-config", help="Save SSH configuration to ~/.ssh/config with specified Host name"
    )
):
    """
    Sync remote server configuration
    
    Examples: 
        remote sync config.toml
        remote sync config.toml --ssh-config machine-name
    """
    path = Path(config_path).expanduser()
    if not path.exists():
        raise typer.Exit(f"Configuration file not found: {config_path}")

    try:
        cfg = tomllib.loads(path.read_text(encoding='utf-8'))
    except Exception as e:
        raise typer.Exit(f"Failed to parse configuration file: {e}")
    
    # Resolve connection parameters (for saving SSH config and executing sync)
    params = resolve_connection_params(cfg)
    
    # Execute sync (this will establish connection and handle add_authorized_key)
    used_key_fallback = run_sync_with_config(cfg, params, path)
    
    # Save SSH config if requested
    if ssh_config:
        save_ssh_config(ssh_config, params, used_key_fallback)


def run():
    """CLI entry point"""
    app()


if __name__ == "__main__":
    run()
