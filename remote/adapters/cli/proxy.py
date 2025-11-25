"""
Proxy CLI commands
"""
import typer
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from ...core.logging import get_logger, get_stdout_console, get_stderr_console
from ...core.constants import (
    DEFAULT_PROXY_LOCAL_PORT,
    DEFAULT_PROXY_REMOTE_PORT,
    DEFAULT_PROXY_MODE,
    DEFAULT_PROXY_LOCAL_HOST,
    DEFAULT_STATE_DIR,
)
from ...core.exceptions import ProxyError
from ...domain.proxy import ProxyConfig, ProxyService
from ...infrastructure.state.file_store import FileStateStore
from .connection import RemoteConnectionFactory
from .prompts import RichPromptProvider
from ..config.loader import ConfigLoader

logger = get_logger(__name__)
stdout_console = get_stdout_console()
stderr_console = get_stderr_console()
prompt_provider = RichPromptProvider()


def register_proxy_app(app: typer.Typer) -> None:
    """Register proxy subcommand app"""
    proxy_app = typer.Typer(
        name="proxy",
        help="Manage SSH reverse proxy tunnels",
        add_completion=False,
    )
    
    proxy_app.command(name="start")(proxy_start)
    proxy_app.command(name="stop")(proxy_stop)
    proxy_app.command(name="status")(proxy_status)
    proxy_app.command(name="list")(proxy_list)
    
    app.add_typer(proxy_app, name="proxy")


def proxy_start(
    name: str = typer.Argument(..., help="Proxy instance name (SSH config host name)"),
    local_port: Optional[int] = typer.Option(
        None,
        "--local-port", "-l",
        help=f"Local proxy port (default: {DEFAULT_PROXY_LOCAL_PORT} or auto if --builtin)"
    ),
    remote_port: int = typer.Option(
        DEFAULT_PROXY_REMOTE_PORT,
        "--remote-port", "-r",
        help=f"Remote proxy port (default: {DEFAULT_PROXY_REMOTE_PORT})"
    ),
    mode: str = typer.Option(
        "socks5",
        "--mode", "-m",
        help=f"Proxy mode: http or socks5 (default: socks5)"
    ),
    local_host: str = typer.Option(
        DEFAULT_PROXY_LOCAL_HOST,
        "--local-host",
        help=f"Local proxy host (default: {DEFAULT_PROXY_LOCAL_HOST})"
    ),
    builtin: bool = typer.Option(
        False,
        "--builtin", "-b",
        help="Use built-in proxy server (no need for local Clash/proxy service)"
    ),
    foreground: bool = typer.Option(
        False, "--foreground", "-f",
        help="Run in foreground (default: background)"
    ),
    config_file: Optional[Path] = typer.Option(
        None,
        "--config", "-c",
        help="Configuration file path (TOML)"
    ),
):
    """
    Start SSH proxy tunnel (runs in background by default)
    
    Two modes:
    1. Built-in proxy mode (--builtin): Starts a local proxy server and forwards remote requests to it
       - No need for local Clash/proxy service
       - Local built-in proxy server listens on local_port (default: 7890)
       - Remote server can access proxy at localhost:remote_port (default: 1081)
       - Remote requests are forwarded to local proxy server through SSH reverse tunnel
    
    2. Reverse tunnel mode (default): Forwards remote proxy port to local proxy service
       - Requires local proxy service (like Clash) running on local_port
       - Remote connections come to local proxy through SSH tunnel
    
    Examples:
        # Built-in proxy mode: remote server accesses local built-in proxy
        remote proxy start my-server --builtin
        remote proxy start my-server -b --local-port 7890 --remote-port 1081
        # On remote server: export http_proxy=http://localhost:1081
        
        # Reverse tunnel mode: forward remote proxy to local Clash
        remote proxy start my-server --local-port 7890 --remote-port 1081
        remote proxy start my-server -l 7890 -r 1081 -m http
    """
    try:
        # Load configuration
        config_loader = ConfigLoader()
        cli_overrides = {
            "proxy": {
                "local_port": local_port,
                "remote_port": remote_port,
                "mode": mode,
                "local_host": local_host,
                "use_builtin": builtin,
            }
        }
        
        cfg = {}
        if config_file:
            cfg = config_loader.load(toml_path=config_file, cli_overrides=cli_overrides)
        else:
            cfg = config_loader.load(cli_overrides=cli_overrides)
        
        # Load SSH config
        from ...core import load_ssh_config
        try:
            ssh_params = load_ssh_config(name)
        except Exception as e:
            stderr_console.print(f"[red]Error:[/red] SSH config '{name}' not found: {e}")
            raise typer.Exit(1)
        
        # Build connection parameters
        params = {
            "host": ssh_params["host"],
            "user": ssh_params.get("user"),
            "port": ssh_params.get("port", 22),
            "key": ssh_params.get("key_file"),
            "password": None,
            "timeout": 10,
        }
        
        # Prompt for missing fields
        if not params.get("user"):
            params["user"] = prompt_provider.prompt("Enter SSH username", default="root")
        
        if not params.get("key") and not params.get("password"):
            password_input = prompt_provider.prompt(
                "Enter SSH password (press Enter to skip)",
                password=True,
                default=""
            )
            params["password"] = password_input if password_input else None
        
        # Determine if using built-in mode
        use_builtin = cfg.get("proxy", {}).get("use_builtin", builtin)
        
        # Auto-assign local_port if using built-in mode and not specified
        final_local_port = cfg.get("proxy", {}).get("local_port", local_port)
        if use_builtin and final_local_port is None:
            final_local_port = DEFAULT_PROXY_LOCAL_PORT
        
        # Create proxy configuration
        proxy_config = ProxyConfig(
            remote_port=cfg.get("proxy", {}).get("remote_port", remote_port),
            local_port=final_local_port,
            mode=cfg.get("proxy", {}).get("mode", mode),
            local_host=cfg.get("proxy", {}).get("local_host", local_host),
            use_builtin=use_builtin,
        )
        proxy_config.validate()
        
        # Create service
        state_store = FileStateStore()
        connection_factory = RemoteConnectionFactory()
        service = ProxyService(name, state_store, connection_factory)
        
        # Start proxy
        def on_started(pid: int):
            mode_str = "Built-in proxy" if proxy_config.use_builtin else "Reverse tunnel"
            stdout_console.print(f"[green]✓[/green] Started {mode_str} '{name}' in {'foreground' if foreground else 'background'}")
            stdout_console.print(f"  SSH host: [cyan]{name}[/cyan]")
            stdout_console.print(f"  PID: [yellow]{pid}[/yellow]")
            
            if proxy_config.use_builtin:
                stdout_console.print(f"  Local built-in proxy: [cyan]{proxy_config.local_host}:{proxy_config.local_port}[/cyan] ({proxy_config.mode.upper()})")
                stdout_console.print(f"  Remote access: [cyan]localhost:{proxy_config.remote_port}[/cyan] (on remote server)")
                stdout_console.print(f"  [yellow]On remote server, use:[/yellow] export http_proxy=http://localhost:{proxy_config.remote_port}")
            else:
                stdout_console.print(f"  Remote port: [cyan]{proxy_config.remote_port}[/cyan] -> Local: [cyan]{proxy_config.local_host}:{proxy_config.local_port}[/cyan]")
                stdout_console.print(f"  [yellow]Make sure local proxy is running on port {proxy_config.local_port}[/yellow]")
            
            if not foreground:
                stdout_console.print(f"  Use [cyan]remote proxy status {name}[/cyan] to check status")
        
        pid = service.start(
            config=proxy_config,
            connection_params=params,
            ssh_host=name,
            background=not foreground,
            on_started=on_started,
        )
        
        if foreground:
            # Keep running in foreground
            try:
                import signal
                import sys
                
                def signal_handler(sig, frame):
                    stdout_console.print("\n[yellow]Stopping proxy...[/yellow]")
                    service.stop()
                    sys.exit(0)
                
                signal.signal(signal.SIGINT, signal_handler)
                signal.signal(signal.SIGTERM, signal_handler)
                
                # Keep alive
                import time
                while service.is_running():
                    time.sleep(1)
            except KeyboardInterrupt:
                stdout_console.print("\n[yellow]Stopping proxy...[/yellow]")
                service.stop()
    
    except ProxyError as e:
        stderr_console.print(f"[red]Proxy Error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        logger.exception("Failed to start proxy")
        stderr_console.print(f"[red]Error:[/red] Failed to start proxy: {e}")
        raise typer.Exit(1)


def proxy_stop(
    name: Optional[str] = typer.Argument(None, help="Proxy instance name (default: stop all)")
):
    """
    Stop SSH reverse proxy tunnel
    
    Examples:
        remote proxy stop my-server
        remote proxy stop  # Stop all instances
    """
    try:
        state_store = FileStateStore()
        connection_factory = RemoteConnectionFactory()
        
        if name:
            # Stop specific instance
            service = ProxyService(name, state_store, connection_factory)
            service.stop()
            stdout_console.print(f"[green]✓[/green] Stopped proxy '{name}'")
        else:
            # Stop all instances
            instances = ProxyService.list_all(state_store)
            if not instances:
                stdout_console.print("[yellow]No running proxy instances[/yellow]")
                return
            
            for instance_name in instances:
                try:
                    service = ProxyService(instance_name, state_store, connection_factory)
                    service.stop()
                    stdout_console.print(f"[green]✓[/green] Stopped proxy '{instance_name}'")
                except ProxyError as e:
                    stderr_console.print(f"[red]Failed to stop '{instance_name}':[/red] {e}")
    
    except ProxyError as e:
        stderr_console.print(f"[red]Proxy Error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        logger.exception("Failed to stop proxy")
        stderr_console.print(f"[red]Error:[/red] Failed to stop proxy: {e}")
        raise typer.Exit(1)


def proxy_status(
    name: Optional[str] = typer.Argument(None, help="Proxy instance name (default: show all)")
):
    """
    Show proxy tunnel status
    
    Examples:
        remote proxy status
        remote proxy status my-server
    """
    try:
        state_store = FileStateStore()
        connection_factory = RemoteConnectionFactory()
        
        if name:
            # Show specific instance
            service = ProxyService(name, state_store, connection_factory)
            status = service.get_status()
            
            if not status:
                stdout_console.print(f"[yellow]Proxy '{name}' is not running[/yellow]")
                return
            
            # Display status
            table = Table(title=f"Proxy Status: {name}", show_header=True, header_style="bold cyan")
            table.add_column("Property", style="cyan")
            table.add_column("Value", style="green")
            
            table.add_row("Status", "[green]Running[/green]")
            table.add_row("PID", str(status.get("pid", "N/A")))
            table.add_row("SSH Host", status.get("ssh_host", "N/A"))
            
            if "config" in status:
                cfg = status["config"]
                table.add_row("Local", f"{cfg.get('local_host', 'localhost')}:{cfg.get('local_port')}")
                table.add_row("Remote Port", str(cfg.get("remote_port")))
                table.add_row("Mode", cfg.get("mode", "http"))
            
            if "started_at" in status:
                started = datetime.fromtimestamp(status["started_at"])
                table.add_row("Started At", started.strftime("%Y-%m-%d %H:%M:%S"))
            
            stdout_console.print(table)
        else:
            # Show all instances
            all_status = ProxyService.get_all_status(state_store)
            
            if not all_status:
                stdout_console.print("[yellow]No running proxy instances[/yellow]")
                return
            
            table = Table(title="All Proxy Instances", show_header=True, header_style="bold cyan")
            table.add_column("Name", style="cyan")
            table.add_column("PID", style="yellow")
            table.add_column("SSH Host", style="green")
            table.add_column("Local", style="blue")
            table.add_column("Remote", style="blue")
            table.add_column("Mode", style="magenta")
            table.add_column("Started", style="dim")
            
            for instance_name, status in all_status.items():
                cfg = status.get("config", {})
                started_at = status.get("started_at", 0)
                started_str = datetime.fromtimestamp(started_at).strftime("%Y-%m-%d %H:%M:%S") if started_at else "N/A"
                
                table.add_row(
                    instance_name,
                    str(status.get("pid", "N/A")),
                    status.get("ssh_host", "N/A"),
                    f"{cfg.get('local_host', 'localhost')}:{cfg.get('local_port')}",
                    str(cfg.get("remote_port")),
                    cfg.get("mode", "http"),
                    started_str,
                )
            
            stdout_console.print(table)
    
    except Exception as e:
        logger.exception("Failed to get proxy status")
        stderr_console.print(f"[red]Error:[/red] Failed to get proxy status: {e}")
        raise typer.Exit(1)


def proxy_list():
    """List all proxy instances"""
    proxy_status(None)

