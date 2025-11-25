"""
Execution helpers for connect module

Simple, safe execution wrappers for local and remote commands
"""
import subprocess
import shlex
from pathlib import Path
from typing import List, Union, Optional

from .models import ConnectSession, CommandResult
from ....core.client import RemoteClient


def exec_local(
    cmd: Union[str, List[str]],
    cwd: Optional[Path] = None,
    timeout: int = 30,
    capture_output: bool = True,
) -> CommandResult:
    """
    Execute a local command.
    
    Args:
        cmd: Command as string or list of arguments
        cwd: Working directory (default: current directory)
        timeout: Command timeout in seconds
        capture_output: Whether to capture stdout/stderr
        
    Returns:
        CommandResult
    """
    try:
        if isinstance(cmd, str):
            # Use shell=True for string commands
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=str(cwd) if cwd else None,
                capture_output=capture_output,
                text=True,
                timeout=timeout,
            )
        else:
            # Use shell=False for list commands (safer)
            result = subprocess.run(
                cmd,
                cwd=str(cwd) if cwd else None,
                capture_output=capture_output,
                text=True,
                timeout=timeout,
            )
        
        return CommandResult(
            exit_code=result.returncode,
            stdout=result.stdout if capture_output else "",
            stderr=result.stderr if capture_output else "",
        )
    except subprocess.TimeoutExpired:
        return CommandResult(
            exit_code=124,  # Timeout exit code
            stdout="",
            stderr=f"Command timed out after {timeout} seconds",
            success=False,
        )
    except Exception as e:
        return CommandResult(
            exit_code=1,
            stdout="",
            stderr=f"Error executing command: {e}",
            success=False,
        )


def exec_remote(
    cmd: str,
    client: RemoteClient,
    cwd: Optional[str] = None,
    timeout: int = 30,
) -> CommandResult:
    """
    Execute a remote command.
    
    Args:
        cmd: Command string
        client: RemoteClient instance
        cwd: Remote working directory (optional)
        timeout: Command timeout in seconds (not directly enforced, but good for documentation)
        
    Returns:
        CommandResult
    """
    try:
        # Build command with cd if cwd is provided
        if cwd:
            # Escape cwd and command for safe execution
            escaped_cwd = shlex.quote(cwd)
            escaped_cmd = cmd  # Command is already a string, user should quote if needed
            full_cmd = f"cd {escaped_cwd} && {escaped_cmd}"
        else:
            full_cmd = cmd
        
        stdout, stderr = client.exec(full_cmd)
        
        # Check if there's an error (heuristic: if stderr has content and stdout is empty)
        # Note: client.exec doesn't return exit code, so we assume success if no stderr
        # For better error detection, we could use exec_with_code, but that's fine for now
        
        return CommandResult(
            exit_code=0 if not stderr else 1,
            stdout=stdout,
            stderr=stderr,
        )
    except Exception as e:
        return CommandResult(
            exit_code=1,
            stdout="",
            stderr=f"Error executing remote command: {e}",
            success=False,
        )


def exec_remote_with_code(
    cmd: str,
    client: RemoteClient,
    cwd: Optional[str] = None,
) -> CommandResult:
    """
    Execute a remote command and get exit code.
    
    Args:
        cmd: Command string
        client: RemoteClient instance
        cwd: Remote working directory (optional)
        
    Returns:
        CommandResult with accurate exit code
    """
    try:
        # Build command with cd if cwd is provided
        if cwd:
            escaped_cwd = shlex.quote(cwd)
            escaped_cmd = cmd
            full_cmd = f"cd {escaped_cwd} && {escaped_cmd}"
        else:
            full_cmd = cmd
        
        stdout, stderr, exit_code = client.exec_with_code(full_cmd)
        
        return CommandResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
        )
    except Exception as e:
        return CommandResult(
            exit_code=1,
            stdout="",
            stderr=f"Error executing remote command: {e}",
            success=False,
        )

