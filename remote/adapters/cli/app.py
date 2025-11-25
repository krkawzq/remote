"""
Main CLI application
"""
import typer
from pathlib import Path
from typing import Optional

from rich.console import Console

from ...core.logging import setup_logging, get_logger, get_stdout_console
from .proxy import register_proxy_app
from .sync import register_sync_command
from .transfer.main import register_transfer_command
from .connect import register_connect_command

logger = get_logger(__name__)
console = get_stdout_console()

# Create main app
app = typer.Typer(
    name="remote",
    add_completion=False,
    help="SSH remote connection management tool",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

# Register sub-apps and commands
register_proxy_app(app)
register_sync_command(app)
register_transfer_command(app)
register_connect_command(app)


@app.callback()
def main(
    log_level: str = typer.Option(
        "INFO",
        "--log-level",
        "-l",
        help="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    ),
    log_file: Optional[Path] = typer.Option(
        None,
        "--log-file",
        help="Log file path",
    ),
):
    """
    Remote - SSH remote connection management tool
    
    Use subcommands to perform different operations:
    - proxy: Manage SSH reverse proxy tunnels
    - sync: Sync remote server configuration
    - transfer: Transfer files with resume support and parallel downloads
    """
    # Setup logging
    setup_logging(level=log_level, log_file=log_file)


def run():
    """CLI entry point"""
    app()


if __name__ == "__main__":
    run()

