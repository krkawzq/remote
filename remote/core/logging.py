"""
Rich-based logging system
"""
import sys
import logging
from typing import Optional, Dict, Any
from pathlib import Path

from rich.logging import RichHandler
from rich.console import Console
from rich.traceback import install as install_traceback


# Global console instances
_stdout_console = Console(file=sys.stdout, force_terminal=True)
_stderr_console = Console(file=sys.stderr, force_terminal=True)

# Install rich traceback handler
install_traceback(show_locals=True, width=120)


def setup_logging(
    level: str = "INFO",
    log_file: Optional[Path] = None,
    rich_tracebacks: bool = True,
) -> None:
    """
    Setup Rich logging system.
    
    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional log file path
        rich_tracebacks: Enable rich tracebacks
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Remove existing handlers
    root_logger.handlers.clear()
    
    # Create Rich handler for stderr
    rich_handler = RichHandler(
        console=_stderr_console,
        show_time=True,
        show_path=True,
        rich_tracebacks=rich_tracebacks,
        markup=True,
        show_level=True,
    )
    rich_handler.setLevel(log_level)
    root_logger.addHandler(rich_handler)
    
    # Add file handler if specified
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(log_level)
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """
    Get logger instance.
    
    Args:
        name: Logger name (usually __name__)
    
    Returns:
        Logger instance
    """
    return logging.getLogger(name)


def get_stdout_console() -> Console:
    """Get stdout console for user-facing output"""
    return _stdout_console


def get_stderr_console() -> Console:
    """Get stderr console for errors and logs"""
    return _stderr_console

