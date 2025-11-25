"""
Transfer CLI main module

Registers transfer command
"""
import typer

from .transfer import register_transfer_command as register_transfer_cmd


def register_transfer_command(app: typer.Typer) -> None:
    """
    Register transfer command to main app.
    """
    # Create transfer subcommand app
    transfer_app = typer.Typer(
        name="transfer",
        help="Transfer files between local and remote hosts",
        add_completion=False,
        no_args_is_help=True,
    )
    
    # Register transfer command
    register_transfer_cmd(transfer_app)
    
    # Register transfer app to main app
    app.add_typer(transfer_app, name="transfer")

