"""
Project constants definitions
"""

# ============================================================
# Remote State
# ============================================================

REMOTE_STATE_PATH = ":~/.remote.json"
LOCAL_MACHINE_ID_PATH = "~/.remote/machine-id"

# ============================================================
# Block Sync Markers
# ============================================================

GLOBAL_START_MARKER = "# >>> remote:global-start <<<"
GLOBAL_END_MARKER = "# <<< remote:global-end <<<"

# ============================================================
# Default Values
# ============================================================

DEFAULT_SSH_PORT = 22
DEFAULT_SSH_TIMEOUT = 10
DEFAULT_INTERPRETER = "/bin/bash"
DEFAULT_BLOCK_HOME = "blocks"
DEFAULT_SCRIPT_HOME = "scripts"

# ============================================================
# Proxy Default Values
# ============================================================

DEFAULT_PROXY_LOCAL_PORT = 7890
DEFAULT_PROXY_REMOTE_PORT = 1081
DEFAULT_PROXY_MODE = "http"
DEFAULT_PROXY_LOCAL_HOST = "localhost"

# ============================================================
# SSH Config
# ============================================================

SSH_CONFIG_PATH = "~/.ssh/config"
SSH_CONFIG_MODE = 0o600

# ============================================================
# State Storage
# ============================================================

DEFAULT_STATE_DIR = "~/.remote/proxy"
DEFAULT_LOG_DIR = "~/.remote/logs"

