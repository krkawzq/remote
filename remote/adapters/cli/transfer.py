"""
Transfer CLI commands
"""
import typer
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, TransferSpeedColumn

from ...core.logging import get_logger, get_stdout_console, get_stderr_console
from ...core.exceptions import TransferError, ConnectionError
from ...core.constants import DEFAULT_SSH_PORT
from ...domain.transfer import TransferService, TransferConfig
from ...infrastructure.state.transfer_store import TransferManifestStore
from .connection import RemoteConnectionFactory

logger = get_logger(__name__)
stdout_console = get_stdout_console()
stderr_console = get_stderr_console()


def register_transfer_command(app: typer.Typer) -> None:
    """Register transfer command on the main app"""
    app.command(name="transfer")(transfer_run)


def transfer_run(
    src: str = typer.Argument(..., help="Source path (local or remote)"),
    dst: str = typer.Argument(..., help="Destination path (local or remote)"),
    # SCP-compatible options
    port: Optional[int] = typer.Option(
        None, "-P", "--port", help="SSH port (default: 22)"
    ),
    preserve: bool = typer.Option(
        False, "-p", help="Preserve file permissions and timestamps"
    ),
    verbose: bool = typer.Option(
        False, "-v", help="Verbose mode"
    ),
    quiet: bool = typer.Option(
        False, "-q", help="Quiet mode"
    ),
    compress: bool = typer.Option(
        False, "-C", help="Enable compression"
    ),
    limit_rate: Optional[str] = typer.Option(
        None, "-l", help="Limit transfer rate (e.g., 1M, 100K)"
    ),
    recursive: bool = typer.Option(
        False, "-r", help="Recursive transfer (not yet supported)"
    ),
    # Transfer-specific options
    resume: bool = typer.Option(
        True, "--resume/--no-resume", help="Enable/disable resume (default: enabled)"
    ),
    force: bool = typer.Option(
        False, "--force", help="Force re-download/re-upload (ignore manifest)"
    ),
    parallel: int = typer.Option(
        4, "--parallel", help="Number of parallel connections (default: 4)"
    ),
    aria2: bool = typer.Option(
        False, "--aria2", help="Enable aria2 mode (aggressive parallel with small chunks)"
    ),
    split: int = typer.Option(
        32, "--split", help="Number of chunks in aria2 mode (default: 32)"
    ),
    chunk: Optional[str] = typer.Option(
        None, "--chunk", help="Chunk size (e.g., 4M, 1MB)"
    ),
):
    """
    Transfer files between local and remote hosts.
    
    Supports SCP-compatible syntax and advanced features:
    - Resume support (default enabled)
    - Parallel transfers
    - Aria2 mode for maximum speed
    
    Examples:
        remote transfer ./file.txt user@host:/tmp/
        remote transfer user@host:~/data.zip .
        remote transfer --aria2 --parallel 16 big.iso host:big.iso
        remote transfer --no-resume --force host:file.txt .
    """
    if recursive:
        stderr_console.print("[red]Error:[/red] Recursive transfer (-r) is not yet supported")
        raise typer.Exit(1)
    
    # Parse chunk size
    parsed_chunk = None
    if chunk:
        parsed_chunk = _parse_size(chunk)
        if parsed_chunk is None:
            stderr_console.print(f"[red]Error:[/red] Invalid chunk size: {chunk}")
            raise typer.Exit(1)
    
    # Parse rate limit
    parsed_limit_rate = None
    if limit_rate:
        parsed_limit_rate = _parse_size(limit_rate)
        if parsed_limit_rate is None:
            stderr_console.print(f"[red]Error:[/red] Invalid rate limit: {limit_rate}")
            raise typer.Exit(1)
    
    # Create transfer config
    config = TransferConfig(
        resume=resume and not force,
        force=force,
        parallel=parallel,
        aria2=aria2,
        split=split,
        chunk=parsed_chunk or (4 * 1024 * 1024),  # Default 4MB
        preserve_permissions=preserve,
        verbose=verbose,
        quiet=quiet,
        compress=compress,
        limit_rate=parsed_limit_rate,
        ssh_port=port or DEFAULT_SSH_PORT,
    )
    
    # Create services
    connection_factory = RemoteConnectionFactory()
    manifest_store = TransferManifestStore()
    transfer_service = TransferService(connection_factory, manifest_store)
    
    # Perform transfer
    show_progress = not quiet and stdout_console.is_terminal
    
    try:
        if not quiet:
            stdout_console.print(f"[cyan]Transferring:[/cyan] {src} → {dst}")
        
        transferred_bytes = 0
        total_bytes = 0
        has_transfer = False
        
        progress_kwargs = {
            "console": stdout_console if show_progress else None,
            "disable": not show_progress,
            "transient": True,
        }
        
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TransferSpeedColumn(),
            **progress_kwargs,
        ) as progress:
            # Start with no task until we know we need one
            task = None
            
            def progress_callback(transferred: int, total: int) -> None:
                nonlocal transferred_bytes, total_bytes, has_transfer, task
                
                # First callback - create task if needed
                if task is None and show_progress and total > 0:
                    task = progress.add_task("Transferring...", total=total, completed=transferred)
                    has_transfer = True
                
                transferred_bytes = transferred
                total_bytes = total
                
                if task is not None and show_progress and total > 0:
                    progress.update(task, completed=transferred, total=total)
            
            # Perform transfer
            final_transferred, final_total = transfer_service.transfer(
                src,
                dst,
                config,
                progress_callback=progress_callback,
            )
            
            # Ensure final state is displayed if there was transfer
            if task is not None and show_progress and final_total > 0:
                progress.update(task, completed=final_transferred, total=final_total)
        
        if not quiet:
            stdout_console.print("[green]✓[/green] Transfer completed successfully")
    
    except TransferError as e:
        stderr_console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    except ConnectionError as e:
        stderr_console.print(f"[red]Connection error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        logger.exception("Transfer failed")
        stderr_console.print(f"[red]Unexpected error:[/red] {e}")
        raise typer.Exit(1)


def _parse_size(size_str: str) -> Optional[int]:
    """
    Parse size string (e.g., "4M", "100K", "1GB") to bytes.
    
    Args:
        size_str: Size string
    
    Returns:
        Size in bytes or None if invalid
    """
    size_str = size_str.strip().upper()
    
    if not size_str:
        return None
    
    # Extract number and unit
    unit_multipliers = {
        "B": 1,
        "K": 1024,
        "KB": 1024,
        "M": 1024 * 1024,
        "MB": 1024 * 1024,
        "G": 1024 * 1024 * 1024,
        "GB": 1024 * 1024 * 1024,
    }
    
    # Find unit
    unit = None
    for u in sorted(unit_multipliers.keys(), key=len, reverse=True):
        if size_str.endswith(u):
            unit = u
            break
    
    if unit:
        number_str = size_str[:-len(unit)]
    else:
        # No unit, assume bytes
        number_str = size_str
        unit = "B"
    
    try:
        number = float(number_str)
        multiplier = unit_multipliers[unit]
        return int(number * multiplier)
    except ValueError:
        return None
