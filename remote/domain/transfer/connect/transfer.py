"""
Transfer operations for connect module

Handles cp command with intelligent transfer strategy
"""
import os
from pathlib import Path
from typing import List

from .models import ConnectSession, CommandResult
from .path_resolver import parse_path
from .transfer_strategy import choose_transfer_method
from ..service import TransferService
from ....infrastructure.state.transfer_store import TransferManifestStore
from ....core.interfaces import ConnectionFactory
from ....adapters.cli.connection import RemoteConnectionFactory


class TransferHandler:
    """Handle file transfer operations"""
    
    def __init__(self):
        """Initialize transfer handler"""
        self.connection_factory: ConnectionFactory = RemoteConnectionFactory()
        self.manifest_store = TransferManifestStore()
        self.transfer_service = TransferService(self.connection_factory, self.manifest_store)
    
    def copy(self, args: List[str], session: ConnectSession) -> CommandResult:
        """
        Copy files between local and remote.
        
        Args:
            args: Command arguments (options + paths)
            session: Connect session
            
        Returns:
            CommandResult
        """
        # Parse arguments: extract options and paths
        options = []
        paths = []
        
        for arg in args:
            if arg.startswith("-"):
                options.append(arg)
            else:
                paths.append(arg)
        
        if len(paths) < 2:
            return CommandResult(
                exit_code=1,
                stdout="",
                stderr="Usage: cp [options] <source> <destination>",
                success=False,
            )
        
        src_path = paths[0]
        dst_path = paths[1]
        
        # Parse paths
        src_spec = parse_path(src_path, session)
        dst_spec = parse_path(dst_path, session)
        
        # Determine operation type
        if not src_spec.is_remote and not dst_spec.is_remote:
            # Local → Local: use shell cp command
            return self._local_copy(src_spec, dst_spec, options)
        
        if src_spec.is_remote and dst_spec.is_remote:
            # Remote → Remote: use remote cp command
            return self._remote_copy(src_spec, dst_spec, session, options)
        
        # Cross-host transfer
        return self._cross_host_copy(src_spec, dst_spec, session)
    
    def _local_copy(self, src_spec, dst_spec, options: List[str] = None) -> CommandResult:
        """Copy local to local using shell command"""
        import subprocess
        
        try:
            src = Path(src_spec.resolved)
            dst = Path(dst_spec.resolved)
            
            if not src.exists():
                return CommandResult(
                    exit_code=1,
                    stdout="",
                    stderr=f"No such file: {src_spec.original}",
                    success=False,
                )
            
            # Use native cp command for full option support
            cmd_parts = ["cp"] + (options or []) + [str(src), str(dst)]
            result = subprocess.run(
                cmd_parts,
                capture_output=True,
                text=True
            )
            
            return CommandResult(
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        except Exception as e:
            return CommandResult(
                exit_code=1,
                stdout="",
                stderr=f"Error copying: {e}",
                success=False,
            )
    
    def _remote_copy(self, src_spec, dst_spec, session: ConnectSession, options: List[str] = None) -> CommandResult:
        """Copy remote to remote using remote cp command"""
        try:
            options_str = " ".join(options or [])
            cmd = f"cp {options_str} {src_spec.resolved} {dst_spec.resolved}".strip()
            stdout, stderr = session.client.exec(cmd)
            
            if stderr:
                return CommandResult(
                    exit_code=1,
                    stdout=stdout,
                    stderr=stderr,
                    success=False,
                )
            
            return CommandResult(
                exit_code=0,
                stdout=stdout,
                stderr=stderr,
            )
        except Exception as e:
            return CommandResult(
                exit_code=1,
                stdout="",
                stderr=f"Error copying: {e}",
                success=False,
            )
    
    def _cross_host_copy(self, src_spec, dst_spec, session: ConnectSession) -> CommandResult:
        """Copy across hosts (local ↔ remote)"""
        try:
            # Get file size
            if src_spec.is_remote:
                # Download: remote → local
                file_size = self._get_remote_file_size(src_spec.resolved, session)
                if file_size is None:
                    return CommandResult(
                        exit_code=1,
                        stdout="",
                        stderr=f"Failed to get file size: {src_spec.original}",
                        success=False,
                    )
                
                # Choose transfer method
                method = choose_transfer_method(file_size, session.config)
                
                if method == "sftp":
                    # Use SFTP for small files
                    return self._sftp_download(src_spec, dst_spec, session)
                else:
                    # Use TransferService for large files
                    return self._transfer_download(src_spec, dst_spec, session)
            else:
                # Upload: local → remote
                file_size = self._get_local_file_size(src_spec.resolved)
                if file_size is None:
                    return CommandResult(
                        exit_code=1,
                        stdout="",
                        stderr=f"Failed to get file size: {src_spec.original}",
                        success=False,
                    )
                
                # Choose transfer method
                method = choose_transfer_method(file_size, session.config)
                
                if method == "sftp":
                    # Use SFTP for small files
                    return self._sftp_upload(src_spec, dst_spec, session)
                else:
                    # Use TransferService for large files
                    return self._transfer_upload(src_spec, dst_spec, session)
        except Exception as e:
            return CommandResult(
                exit_code=1,
                stdout="",
                stderr=f"Error in cross-host copy: {e}",
                success=False,
            )
    
    def _get_local_file_size(self, path: str) -> int:
        """Get local file size"""
        try:
            return os.path.getsize(path)
        except Exception:
            return None
    
    def _get_remote_file_size(self, path: str, session: ConnectSession) -> int:
        """Get remote file size"""
        try:
            cmd = f"stat -c %s {path}"
            stdout, stderr = session.client.exec(cmd)
            if stdout.strip():
                return int(stdout.strip())
            return None
        except Exception:
            return None
    
    def _sftp_download(self, src_spec, dst_spec, session: ConnectSession) -> CommandResult:
        """Download using SFTP"""
        try:
            sftp = session.client.open_sftp()
            sftp.get(src_spec.resolved, dst_spec.resolved)
            
            file_size = self._get_remote_file_size(src_spec.resolved, session)
            if file_size:
                session.add_transferred_bytes(file_size)
            
            return CommandResult(
                exit_code=0,
                stdout="",
                stderr="",
            )
        except Exception as e:
            return CommandResult(
                exit_code=1,
                stdout="",
                stderr=f"SFTP download failed: {e}",
                success=False,
            )
    
    def _sftp_upload(self, src_spec, dst_spec, session: ConnectSession) -> CommandResult:
        """Upload using SFTP"""
        try:
            sftp = session.client.open_sftp()
            sftp.put(src_spec.resolved, dst_spec.resolved)
            
            file_size = self._get_local_file_size(src_spec.resolved)
            if file_size:
                session.add_transferred_bytes(file_size)
            
            return CommandResult(
                exit_code=0,
                stdout="",
                stderr="",
            )
        except Exception as e:
            return CommandResult(
                exit_code=1,
                stdout="",
                stderr=f"SFTP upload failed: {e}",
                success=False,
            )
    
    def _transfer_download(self, src_spec, dst_spec, session: ConnectSession) -> CommandResult:
        """Download using TransferService"""
        try:
            # Build source path in scp format
            src_scp = f"{session.user}@{session.host}:{src_spec.resolved}"
            
            # Transfer using TransferService
            transferred, total = self.transfer_service.transfer(
                src_scp,
                dst_spec.resolved,
                session.config.transfer_config,
            )
            
            session.add_transferred_bytes(transferred)
            
            return CommandResult(
                exit_code=0,
                stdout="",
                stderr="",
            )
        except Exception as e:
            return CommandResult(
                exit_code=1,
                stdout="",
                stderr=f"Transfer download failed: {e}",
                success=False,
            )
    
    def _transfer_upload(self, src_spec, dst_spec, session: ConnectSession) -> CommandResult:
        """Upload using TransferService"""
        try:
            # Build destination path in scp format
            dst_scp = f"{session.user}@{session.host}:{dst_spec.resolved}"
            
            # Transfer using TransferService
            transferred, total = self.transfer_service.transfer(
                src_spec.resolved,
                dst_scp,
                session.config.transfer_config,
            )
            
            session.add_transferred_bytes(transferred)
            
            return CommandResult(
                exit_code=0,
                stdout="",
                stderr="",
            )
        except Exception as e:
            return CommandResult(
                exit_code=1,
                stdout="",
                stderr=f"Transfer upload failed: {e}",
                success=False,
            )

