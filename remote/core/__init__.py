"""
Core infrastructure layer
"""
from .client import RemoteClient, ClientConfig
from .constants import *
from .exceptions import *
from .logging import setup_logging, get_logger, get_stdout_console, get_stderr_console
from .interfaces import StateStore, ConnectionFactory, PromptProvider
from .telemetry import Telemetry, get_telemetry
from .utils import (
    load_ssh_config,
    is_remote_path,
    resolve_local_path,
    resolve_remote_path,
    generate_ssh_key_pair,
    add_authorized_key,
)

__all__ = [
    "RemoteClient",
    "ClientConfig",
    "setup_logging",
    "get_logger",
    "get_stdout_console",
    "get_stderr_console",
    "StateStore",
    "ConnectionFactory",
    "PromptProvider",
    "Telemetry",
    "get_telemetry",
    "load_ssh_config",
    "is_remote_path",
    "resolve_local_path",
    "resolve_remote_path",
    "generate_ssh_key_pair",
    "add_authorized_key",
]

