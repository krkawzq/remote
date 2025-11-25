"""
remote - SSH remote connection management tool

Provides high-level CLI tool abstractions to assist users with remote servers, supporting:
- File synchronization (multiple modes: sync, update, cover, init)
- Text block synchronization (intelligent management of code blocks in configuration files)
- Script execution (supports init and always modes)
- SSH connection management (supports password and key authentication)
- SSH reverse proxy tunnels
"""

__version__ = "0.1.0"

# Export core components
from .core import (
    RemoteClient,
    ClientConfig,
    load_ssh_config,
    generate_ssh_key_pair,
    add_authorized_key,
)

# Export domain models
from .domain.sync import (
    FileSync,
    TextBlock,
    BlockGroup,
    ScriptExec,
    GlobalEnv,
)

from .domain.proxy import (
    ProxyConfig,
    ProxyState,
    TunnelConfig,
)

# Export system utilities
from .core.system.machine import (
    register_machine,
    update_last_sync,
    is_first_connect,
    get_local_machine_id,
)

__all__ = [
    # Version
    "__version__",
    # Client
    "RemoteClient",
    "ClientConfig",
    # Utilities
    "load_ssh_config",
    "generate_ssh_key_pair",
    "add_authorized_key",
    # System
    "register_machine",
    "update_last_sync",
    "is_first_connect",
    "get_local_machine_id",
    # File sync models
    "FileSync",
    # Block sync models
    "TextBlock",
    "BlockGroup",
    # Script execution models
    "ScriptExec",
    "GlobalEnv",
    # Proxy models
    "ProxyConfig",
    "ProxyState",
    "TunnelConfig",
]
