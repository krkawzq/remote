"""
CLI entry point for connect command
"""
import getpass
import typer
from typing import Optional

from ....core.logging import get_logger, get_stderr_console
from ....core.exceptions import ConnectionError
from ....domain.transfer.connect.session import ConnectSessionManager
from ....domain.transfer.connect.models import ConnectConfig
from .shell import ConnectShell
from .host_parser import parse_host_string
from .utils import parse_size

logger = get_logger(__name__)
stderr_console = get_stderr_console()


def connect_run(
    host: str = typer.Argument(..., help="Hostname or SSH config alias (supports user@host format)"),
    user: Optional[str] = typer.Option(None, "--user", "-u", help="Username"),
    port: Optional[int] = typer.Option(None, "--port", "-p", "-P", help="SSH port"),
    password: bool = typer.Option(False, "--password", help="Prompt for password"),
    key_file: Optional[str] = typer.Option(None, "--key", "-i", help="SSH key file path"),
    threshold: Optional[str] = typer.Option(None, "--threshold", help="Large file threshold (e.g., 100M)"),
    parallel: Optional[int] = typer.Option(None, "--parallel", help="Parallel connections"),
    chunk: Optional[str] = typer.Option(None, "--chunk", help="Chunk size (e.g., 4M)"),
    timeout: Optional[int] = typer.Option(None, "--timeout", help="Connection timeout (seconds)"),
) -> None:
    """
    Start interactive file management session.
    
    Provides a unified interface for managing files on local and remote hosts.
    Use ':' prefix for remote paths, e.g., ':~/file.txt' or ':~/data/'.
    
    Supports SSH-style host format: user@host or user@host:port
    
    Examples:
        remote connect myserver
        remote connect user@host
        remote connect user@host:2222
        remote connect user@host -p 2222
        remote connect host --password
        remote connect host --threshold 50M --parallel 8
    """
    # Parse host string
    parsed_host, parsed_user, parsed_port = parse_host_string(host, user, port)
    
    # Parse password if needed
    password_str: Optional[str] = None
    if password:
        password_str = getpass.getpass("Password: ")
    
    # Parse threshold
    threshold_bytes: Optional[int] = None
    if threshold:
        threshold_bytes = parse_size(threshold)
        if threshold_bytes is None:
            stderr_console.print(f"[red]Error:[/red] Invalid threshold format: {threshold}")
            raise typer.Exit(1)
    
    # Parse chunk size
    chunk_bytes: Optional[int] = None
    if chunk:
        chunk_bytes = parse_size(chunk)
        if chunk_bytes is None:
            stderr_console.print(f"[red]Error:[/red] Invalid chunk format: {chunk}")
            raise typer.Exit(1)
    
    # Create configuration
    config = ConnectConfig()
    if threshold_bytes:
        config.large_file_threshold = threshold_bytes
    if parallel:
        config.transfer_config.parallel = parallel
    if chunk_bytes:
        config.transfer_config.chunk = chunk_bytes
    if timeout:
        config.timeout = timeout
    
    # Create session
    try:
        session = ConnectSessionManager.create_session(
            host=parsed_host,
            user=parsed_user,
            port=parsed_port,
            password=password_str,
            key_file=key_file,
            config=config,
            prompt_password=True,  # Enable interactive password prompt
        )
    except ConnectionError as e:
        stderr_console.print(f"[red]Connection error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        logger.exception("Failed to create session")
        stderr_console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    
    # Run shell
    try:
        shell = ConnectShell(session)
        shell.run()
    except KeyboardInterrupt:
        print("\nInterrupted")
    except Exception as e:
        logger.exception("Shell error")
        stderr_console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    finally:
        # Cleanup
        ConnectSessionManager.close_session(session)


def register_connect_command(app: typer.Typer) -> None:
    """
    Register connect command to main app.
    
    Args:
        app: Typer app instance (main app)
    """
    # Register connect command directly to main app
    app.command(name="connect")(connect_run)

