"""
remote - SSH remote connection management tool

Provides high-level CLI tool abstractions to assist users with remote servers, supporting:
- File synchronization (multiple modes: sync, update, cover, init)
- Text block synchronization (intelligent management of code blocks in configuration files)
- Script execution (supports init and always modes)
- SSH connection management (supports password and key authentication)
"""

__version__ = "0.1.0"

from .client import RemoteClient, ClientConfig
from .system import (
    register_machine,
    update_last_sync,
    is_first_connect,
    get_local_machine_id,
)
from .sync.file import FileSync, sync_files
from .sync.block import TextBlock, BlockGroup, sync_block_groups
from .sync.script import ScriptExec, GlobalEnv, run_script

__all__ = [
    # Client
    "RemoteClient",
    "ClientConfig",
    # System
    "register_machine",
    "update_last_sync",
    "is_first_connect",
    "get_local_machine_id",
    # File sync
    "FileSync",
    "sync_files",
    # Block sync
    "TextBlock",
    "BlockGroup",
    "sync_block_groups",
    # Script execution
    "ScriptExec",
    "GlobalEnv",
    "run_script",
]

