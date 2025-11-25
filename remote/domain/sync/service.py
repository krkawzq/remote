"""
Sync domain service - business logic
"""
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable

from ...core.client import RemoteClient
from ...core.interfaces import ConnectionFactory
from ...core.exceptions import SyncError
from ...core.logging import get_logger
from ...core.system import is_first_connect, register_machine, update_last_sync
from ...core.utils import generate_ssh_key_pair, add_authorized_key
from .models import FileSync, BlockGroup, ScriptExec, GlobalEnv
from .file_sync import sync_files
from .block_sync import sync_block_groups
from .script_exec import run_script

logger = get_logger(__name__)


class SyncService:
    """
    Sync service - pure business logic.
    
    Handles file sync, block sync, and script execution.
    No direct dependency on CLI, Typer, or file system.
    """
    
    def __init__(
        self,
        connection_factory: ConnectionFactory,
        on_connected: Optional[Callable[[str, int], None]] = None,
        on_key_generated: Optional[Callable[[str], None]] = None,
        on_key_added: Optional[Callable[[str], None]] = None,
        on_first_connect: Optional[Callable[[], None]] = None,
        on_script_skip: Optional[Callable[[str, str], None]] = None,
        on_script_exec: Optional[Callable[[str], None]] = None,
        on_complete: Optional[Callable[[], None]] = None,
    ):
        """
        Initialize sync service.
        
        Args:
            connection_factory: SSH connection factory
            on_connected: Callback when connected (host, port)
            on_key_generated: Callback when key is generated (key_path)
            on_key_added: Callback when key is added (remote_path)
            on_first_connect: Callback on first connection
            on_script_skip: Callback when script is skipped (script_path, reason)
            on_script_exec: Callback when script is executed (script_path)
            on_complete: Callback when sync completes
        """
        self.connection_factory = connection_factory
        self.on_connected = on_connected
        self.on_key_generated = on_key_generated
        self.on_key_added = on_key_added
        self.on_first_connect = on_first_connect
        self.on_script_skip = on_script_skip
        self.on_script_exec = on_script_exec
        self.on_complete = on_complete
        self._client: Optional[RemoteClient] = None
    
    def sync(
        self,
        connection_params: Dict[str, Any],
        file_items: List[FileSync],
        block_groups: List[BlockGroup],
        scripts: List[ScriptExec],
        global_env: GlobalEnv,
        add_authorized_key_flag: bool = False,
    ) -> bool:
        """
        Execute sync tasks.
        
        Process:
        1. Establish SSH connection
        2. Handle add_authorized_key if specified
        3. Check system status (first connection)
        4. Sync files
        5. Sync blocks
        6. Execute scripts
        7. Update sync time
        
        Args:
            connection_params: SSH connection parameters
            file_items: List of file sync items
            block_groups: List of block groups
            scripts: List of scripts to execute
            global_env: Global environment configuration
            add_authorized_key_flag: Whether to add authorized key
        
        Returns:
            used_key_fallback: True if key auth was attempted but fell back to password
        
        Raises:
            SyncError: If an error occurs during sync
        """
        used_key_fallback = False
        
        try:
            # Step 1: Establish SSH connection
            # Try key authentication if key is specified
            if connection_params.get("key"):
                try:
                    self._client = self.connection_factory.create(connection_params)
                    used_key_fallback = False
                except Exception:
                    if connection_params.get("password"):
                        used_key_fallback = True
                        logger.warning("Key authentication failed, trying password...")
                        # Retry with password
                        params_without_key = connection_params.copy()
                        params_without_key.pop("key", None)
                        self._client = self.connection_factory.create(params_without_key)
                    else:
                        raise
            else:
                self._client = self.connection_factory.create(connection_params)
            
            # Notify connection established
            if self.on_connected:
                self.on_connected(
                    connection_params["host"],
                    connection_params.get("port", 22)
                )
            
            # Step 1.5: Handle add_authorized_key if specified
            if add_authorized_key_flag:
                # Determine which key to use
                if connection_params.get("key"):
                    # Use specified key
                    key_path = Path(connection_params["key"]).expanduser()
                    pub_key_path = Path(str(key_path) + ".pub")
                else:
                    # Use default key
                    default_key = Path.home() / ".ssh" / "id_ed25519_remote"
                    if not default_key.exists():
                        if self.on_key_generated:
                            self.on_key_generated(str(default_key))
                        generate_ssh_key_pair(default_key)
                    key_path = default_key
                    pub_key_path = Path(str(default_key) + ".pub")
                
                # Add public key to remote authorized_keys
                add_authorized_key(self._client, str(pub_key_path))
                if self.on_key_added:
                    out, _ = self._client.exec("printf $HOME")
                    home = out.strip() or "/root"
                    self.on_key_added(f"{home}/.ssh/authorized_keys")
            
            # Step 2: System check (check only, don't register)
            is_first = is_first_connect(self._client)
            
            # Step 3: Filter scripts based on first connection
            scripts_to_run = []
            for script in scripts:
                if script.mode == "init" and not is_first:
                    if self.on_script_skip:
                        self.on_script_skip(script.src, "init mode, not first connection")
                    continue
                scripts_to_run.append(script)
            
            # Use try-except to ensure registration only on complete success
            try:
                # Step 4: File sync
                if file_items:
                    sync_files(file_items, self._client)
                
                # Step 5: Block sync
                if block_groups:
                    sync_block_groups(block_groups, self._client)
                
                # Step 6: Script execution
                for script in scripts_to_run:
                    if self.on_script_exec:
                        self.on_script_exec(script.src)
                    
                    out, err, code = run_script(script, self._client, global_env)
                    
                    # Display error message if any
                    if err and code != 0:
                        logger.error(f"[script] Error output:\n{err}")
                    
                    if code != 0 and not script.allow_fail:
                        raise SyncError(
                            f"Script execution failed: {script.src} (exit code: {code})"
                        )
                
                # Step 7: All operations successful, register machine and update sync time
                if is_first:
                    if self.on_first_connect:
                        self.on_first_connect()
                    register_machine(self._client, meta={"client": "remote"})
                
                update_last_sync(self._client)
                
                if self.on_complete:
                    self.on_complete()
                
                return used_key_fallback
            
            except Exception as e:
                # If any operation fails, don't register machine, re-raise exception
                if is_first:
                    logger.warning(
                        "Sync failed, not registered as first connection, "
                        "init operations will be retried next time"
                    )
                if isinstance(e, SyncError):
                    raise
                raise SyncError(f"Sync failed: {e}") from e
        
        finally:
            # Clean up connection
            if self._client:
                self._client.close()
                self._client = None

