"""
CLI entry point
"""
import typer
import tomllib
from pathlib import Path
from typing import Optional

from .config import resolve_connection_params
from .utils import save_ssh_config, load_ssh_config
from .sync import run_sync_with_config
from .proxy import ProxyManager, ProxyConfig
from .exceptions import ProxyError, ConfigError
from .constants import (
    DEFAULT_PROXY_LOCAL_PORT,
    DEFAULT_PROXY_REMOTE_PORT,
    DEFAULT_PROXY_MODE,
    DEFAULT_PROXY_LOCAL_HOST,
)


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
    - proxy: Manage SSH reverse proxy tunnels
    """
    pass


# ============================================================
# Proxy Subcommands
# ============================================================

proxy_app = typer.Typer(
    name="proxy",
    help="Manage SSH reverse proxy tunnels",
    add_completion=False,
)

app.add_typer(proxy_app)


@proxy_app.command(name="start")
def proxy_start(
    name: str = typer.Argument(..., help="Proxy instance name (SSH config host name)"),
    local_port: int = typer.Option(
        DEFAULT_PROXY_LOCAL_PORT,
        "--local-port", "-l",
        help=f"Local proxy port (default: {DEFAULT_PROXY_LOCAL_PORT})"
    ),
    remote_port: int = typer.Option(
        DEFAULT_PROXY_REMOTE_PORT,
        "--remote-port", "-r",
        help=f"Remote mapped port (default: {DEFAULT_PROXY_REMOTE_PORT})"
    ),
    mode: str = typer.Option(
        DEFAULT_PROXY_MODE,
        "--mode", "-m",
        help=f"Proxy mode: http or socks5 (default: {DEFAULT_PROXY_MODE})"
    ),
    local_host: str = typer.Option(
        DEFAULT_PROXY_LOCAL_HOST,
        "--local-host",
        help=f"Local proxy host (default: {DEFAULT_PROXY_LOCAL_HOST})"
    ),
    foreground: bool = typer.Option(
        False, "--foreground", "-f",
        help="Run in foreground (default: background)"
    )
):
    """
    Start SSH reverse proxy tunnel (runs in background by default)
    
    Examples:
        remote proxy start my-server
        remote proxy start my-server --local-port 7890 --remote-port 1081
        remote proxy start my-server -l 7890 -r 1081 -m http
        remote proxy start my-server --foreground
    """
    # Load SSH config
    try:
        ssh_params = load_ssh_config(name)
    except ConfigError as e:
        raise typer.Exit(f"SSH config '{name}' not found: {e}")
    
    # Build connection parameters from SSH config
    params = {
        "host": ssh_params["host"],
        "user": ssh_params.get("user"),
        "port": ssh_params.get("port", 22),
        "key": ssh_params.get("key_file"),
        "password": None,
        "timeout": 10,
    }
    
    # Prompt for missing required fields
    if not params.get("user"):
        params["user"] = typer.prompt("Enter SSH username", default="root")
    
    # Prompt for password if no key is provided
    if not params.get("key") and not params.get("password"):
        password_input = typer.prompt(
            "Enter SSH password (press Enter to skip)",
            hide_input=True,
            default=""
        )
        params["password"] = password_input if password_input else None
    
    # Create proxy configuration
    try:
        proxy_cfg = ProxyConfig(
            local_port=local_port,
            remote_port=remote_port,
            mode=mode,
            local_host=local_host
        )
        proxy_cfg.validate()
    except Exception as e:
        raise typer.Exit(f"Invalid proxy configuration: {e}")
    
    # Start proxy (default: background)
    manager = ProxyManager(name=name)
    try:
        pid = manager.start(proxy_cfg, connection_params=params, ssh_host=name, background=not foreground)
    
    except ProxyError as e:
        raise typer.Exit(str(e))
    except Exception as e:
        raise typer.Exit(f"Failed to start proxy: {e}")


@proxy_app.command(name="stop")
def proxy_stop(
    name: Optional[str] = typer.Argument(None, help="Proxy instance name (default: stop all)")
):
    """
    Stop SSH reverse proxy tunnel
    
    Examples:
        remote proxy stop my-server
        remote proxy stop  # Stop all instances
    """
    if name:
        # Stop specific instance
        manager = ProxyManager(name=name)
        try:
            manager.stop()
        except ProxyError as e:
            raise typer.Exit(str(e))
        except Exception as e:
            raise typer.Exit(f"Failed to stop proxy: {e}")
    else:
        # Stop all instances
        instances = ProxyManager.list_all_instances()
        if not instances:
            typer.echo("[proxy] No running instances")
            return
        
        for instance_name in instances:
            manager = ProxyManager(name=instance_name)
            try:
                manager.stop()
            except ProxyError as e:
                typer.echo(f"[proxy] Failed to stop '{instance_name}': {e}")
            except Exception as e:
                typer.echo(f"[proxy] Failed to stop '{instance_name}': {e}")


@proxy_app.command(name="status")
def proxy_status(
    name: Optional[str] = typer.Argument(None, help="Proxy instance name (default: show all)")
):
    """
    Show proxy tunnel status
    
    Examples:
        remote proxy status
        remote proxy status my-server
    """
    if name:
        # Show specific instance status
        manager = ProxyManager(name=name)
        status = manager.get_status()
        
        if not status:
            typer.echo(f"[proxy] '{name}' is not running")
            return
        
        typer.echo(f"[proxy] '{name}' Status: Running")
        typer.echo(f"[proxy] PID: {status.get('pid', 'N/A')}")
        
        # Show SSH config name if available
        if "ssh_config" in status and status["ssh_config"]:
            typer.echo(f"[proxy] SSH Config: {status['ssh_config']}")
        
            # Show SSH host
        if "ssh_host" in status:
            typer.echo(f"[proxy] SSH host: {status['ssh_host']}")
        
        # Show proxy configuration
        if "config" in status:
            cfg = status["config"]
            typer.echo(f"[proxy] Local: {cfg.get('local_host', 'localhost')}:{cfg.get('local_port')}")
            typer.echo(f"[proxy] Remote port: {cfg.get('remote_port')}")
            typer.echo(f"[proxy] Mode: {cfg.get('mode', 'http')}")
        
        # Show tunnel info
        if "tunnel" in status:
            tunnel = status["tunnel"]
            typer.echo(f"[proxy] Tunnel: remote localhost:{tunnel.get('remote_port')} -> local {tunnel.get('local_host')}:{tunnel.get('local_port')}")
        
        # Show start time
        if "started_at" in status:
            import datetime
            started = datetime.datetime.fromtimestamp(status["started_at"])
            typer.echo(f"[proxy] Started at: {started.strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        # Show all instances status
        all_status = ProxyManager.get_all_status()
        
        if not all_status:
            typer.echo("[proxy] No running instances")
            return
        
        typer.echo(f"[proxy] Found {len(all_status)} running instance(s):\n")
        
        for instance_name, status in all_status.items():
            typer.echo(f"[proxy] '{instance_name}':")
            typer.echo(f"  PID: {status.get('pid', 'N/A')}")
            
            # Show SSH config name if available
            if "ssh_config" in status and status["ssh_config"]:
                typer.echo(f"  SSH Config: {status['ssh_config']}")
            
            # Show SSH host
            if "ssh_host" in status:
                typer.echo(f"  SSH host: {status['ssh_host']}")
            
            # Show proxy configuration
            if "config" in status:
                cfg = status["config"]
                typer.echo(f"  Local: {cfg.get('local_host', 'localhost')}:{cfg.get('local_port')}")
                typer.echo(f"  Remote port: {cfg.get('remote_port')}")
                typer.echo(f"  Mode: {cfg.get('mode', 'http')}")
            
            # Show start time
            if "started_at" in status:
                import datetime
                started = datetime.datetime.fromtimestamp(status["started_at"])
                typer.echo(f"  Started at: {started.strftime('%Y-%m-%d %H:%M:%S')}")
            
            typer.echo()


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
