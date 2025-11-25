"""
Unified command executor for local and remote commands

Provides a clean interface for executing commands in both contexts
"""
import sys
import shlex
from pathlib import Path
from typing import Optional

from ....domain.transfer.connect.models import ConnectSession
from ....domain.transfer.connect.exec_helpers import exec_local, exec_remote_with_code
from ....domain.transfer.connect.path_resolver import parse_path


class CommandExecutor:
    """Unified executor for local and remote commands"""
    
    def __init__(self, session: ConnectSession):
        """
        Initialize executor.
        
        Args:
            session: Connect session
        """
        self.session = session
    
    def execute(
        self,
        command: str,
        args: list[str],
        path: Optional[str] = None,
        is_remote: Optional[bool] = None,
    ) -> int:
        """
        Execute a command in local or remote context.
        
        Args:
            command: Command name (e.g., "ls", "cat")
            args: Command arguments
            path: Optional path argument (if provided, determines context)
            is_remote: Explicit remote flag (overrides path-based detection)
            
        Returns:
            Exit code
        """
        # Determine context
        if is_remote is None:
            if path:
                path_spec = parse_path(path, self.session)
                is_remote = path_spec.is_remote
            else:
                is_remote = self.session.last_cd_was_remote
        
        # Build command parts
        cmd_parts = [command] + args
        
        if is_remote:
            return self._execute_remote(cmd_parts, path)
        else:
            return self._execute_local(cmd_parts, path)
    
    def _execute_local(self, cmd_parts: list[str], path: Optional[str] = None) -> int:
        """Execute command locally"""
        cwd = self.session.local_cwd
        if path:
            path_spec = parse_path(path, self.session)
            if not path_spec.is_remote:
                cwd = Path(path_spec.resolved).parent if Path(path_spec.resolved).is_file() else Path(path_spec.resolved)
        
        result = exec_local(cmd_parts, cwd=cwd)
        
        self._write_output(result.stdout, result.stderr)
        return result.exit_code
    
    def _execute_remote(self, cmd_parts: list[str], path: Optional[str] = None) -> int:
        """Execute command remotely"""
        cwd = self.session.remote_cwd
        if path:
            path_spec = parse_path(path, self.session)
            if path_spec.is_remote:
                # Use parent directory if path is a file
                import os
                remote_path = path_spec.resolved
                # Try to determine if it's a file or directory
                check_cmd = f"test -d {shlex.quote(remote_path)} && echo dir || echo file"
                check_result = exec_remote_with_code(check_cmd, self.session.client, self.session.remote_cwd)
                if check_result.success and 'dir' in check_result.stdout:
                    cwd = remote_path
                else:
                    cwd = os.path.dirname(remote_path) if os.path.dirname(remote_path) else self.session.remote_cwd
        
        cmd = ' '.join(shlex.quote(p) for p in cmd_parts)
        result = exec_remote_with_code(cmd, self.session.client, cwd)
        
        self._write_output(result.stdout, result.stderr)
        return result.exit_code
    
    def execute_simple(
        self,
        command: str,
        path: str,
        is_remote: Optional[bool] = None,
    ) -> int:
        """
        Execute a simple command with a single path argument.
        
        Args:
            command: Command name
            path: Path argument
            is_remote: Explicit remote flag
            
        Returns:
            Exit code
        """
        return self.execute(command, [path], path=path, is_remote=is_remote)
    
    def execute_with_options(
        self,
        command: str,
        options: list[str],
        paths: list[str],
        default_path: Optional[str] = None,
    ) -> int:
        """
        Execute command with options and paths.
        
        Args:
            command: Command name
            options: Command options (flags)
            paths: Path arguments
            default_path: Default path if paths is empty
            
        Returns:
            Exit code
        """
        if not paths and default_path:
            paths = [default_path]
        
        # Determine context from first path
        is_remote = None
        if paths:
            path_spec = parse_path(paths[0], self.session)
            is_remote = path_spec.is_remote
        
        cmd_parts = [command] + options + paths
        return self.execute(command, cmd_parts[1:], path=paths[0] if paths else None, is_remote=is_remote)
    
    @staticmethod
    def _write_output(stdout: str, stderr: str) -> None:
        """Write command output to stdout/stderr"""
        if stdout:
            sys.stdout.write(stdout if stdout.endswith('\n') else stdout + '\n')
            sys.stdout.flush()
        if stderr:
            sys.stderr.write(stderr if stderr.endswith('\n') else stderr + '\n')
            sys.stderr.flush()

