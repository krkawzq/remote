"""
Rich-based user prompts
"""
from typing import Optional
from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.panel import Panel
from rich.text import Text

from ...core.logging import get_stdout_console


class RichPromptProvider:
    """Rich-based prompt provider"""
    
    def __init__(self, console: Optional[Console] = None):
        self.console = console or get_stdout_console()
    
    def prompt(self, message: str, default: Optional[str] = None, password: bool = False) -> str:
        """Prompt user for input"""
        # Format message with default value if provided
        if default is not None:
            formatted_message = f"{message} (default: {default})"
        else:
            formatted_message = message
        
        if password:
            return Prompt.ask(formatted_message, password=True, default=default, console=self.console)
        return Prompt.ask(formatted_message, default=default, console=self.console)
    
    def confirm(self, message: str, default: bool = False) -> bool:
        """Prompt user for confirmation"""
        return Confirm.ask(message, default=default, console=self.console)
    
    def info(self, message: str) -> None:
        """Display info message"""
        self.console.print(f"[cyan]ℹ[/cyan] {message}")
    
    def success(self, message: str) -> None:
        """Display success message"""
        self.console.print(f"[green]✓[/green] {message}")
    
    def warning(self, message: str) -> None:
        """Display warning message"""
        self.console.print(f"[yellow]⚠[/yellow] {message}")
    
    def error(self, message: str) -> None:
        """Display error message"""
        self.console.print(f"[red]✗[/red] {message}")
    
    def panel(self, content: str, title: str = "", border_style: str = "blue") -> None:
        """Display content in a panel"""
        self.console.print(Panel(content, title=title, border_style=border_style))

