"""
Unified exception definitions
"""


class RemoteError(Exception):
    """Base exception class"""
    pass


class ConfigError(RemoteError):
    """Configuration error"""
    pass


class ConnectionError(RemoteError):
    """Connection error"""
    pass


class SyncError(RemoteError):
    """Sync error"""
    pass


class FileSyncError(SyncError):
    """File sync error"""
    pass


class BlockSyncError(SyncError):
    """Text block sync error"""
    pass


class ScriptExecutionError(SyncError):
    """Script execution error"""
    pass


class ProxyError(RemoteError):
    """Proxy error"""
    pass


class TransferError(RemoteError):
    """Transfer error"""
    pass

