"""
Script execution implementation
"""
import time
from pathlib import Path
from typing import Optional, Tuple

from ...core.client import RemoteClient
from ...core.utils import is_remote_path, resolve_remote_path
from ...core.logging import get_logger
from ...core.exceptions import ScriptExecutionError
from .models import ScriptExec, GlobalEnv

logger = get_logger(__name__)

# Interactive command timeout (seconds)
INTERACTIVE_TIMEOUT = 60


# ============================================================
# Helper Functions
# ============================================================

def detect_shebang(path: Path) -> Optional[str]:
    """
    Read shebang line from local file.
    
    Returns:
        Interpreter path from shebang, or None if not found
    """
    try:
        first_line = path.read_text().split("\n")[0].strip()
        if first_line.startswith("#!"):
            return first_line[2:].strip()
    except (OSError, IOError, IndexError):
        pass
    return None


def upload_script(client: RemoteClient, local_path: Path) -> str:
    """
    Upload local script to remote /tmp directory.
    
    Args:
        client: RemoteClient instance
        local_path: Local script path
    
    Returns:
        Remote script path
    """
    remote_path = f"/tmp/{local_path.name}"
    
    sftp = client.open_sftp()
    with sftp.open(remote_path, "w") as f:
        f.write(local_path.read_text())
    sftp.chmod(remote_path, 0o755)
    
    return remote_path


def delete_remote_file(client: RemoteClient, path: str) -> None:
    """
    Delete remote temporary file (ignore errors).
    
    Args:
        client: RemoteClient instance
        path: Remote file path
    """
    try:
        sftp = client.open_sftp()
        sftp.remove(path)
    except (IOError, OSError):
        # File doesn't exist or no permission to delete, ignore
        pass


# ============================================================
# Command Execution
# ============================================================

def exec_non_interactive(
    client: RemoteClient, cmd: str, allow_fail: bool
) -> Tuple[str, str, int]:
    """
    Execute command non-interactively with real-time output.
    
    Args:
        client: RemoteClient instance
        cmd: Command to execute
        allow_fail: Whether non-zero exit codes are allowed
    
    Returns:
        (stdout, stderr, exit_code)
    
    Raises:
        ScriptExecutionError: If command fails and allow_fail=False
    """
    out, err, code = client.exec_with_code_streaming(cmd)
    
    if code != 0 and not allow_fail:
        raise ScriptExecutionError(
            f"Script execution failed:\ncmd: {cmd}\ncode: {code}\nstderr:\n{err}"
        )
    
    return out, err, code


def exec_interactive(client: RemoteClient, cmd: str) -> Tuple[str, str, int]:
    """
    Execute command interactively (simplified implementation).
    
    Note: This is a simplified implementation and does not support true user interaction.
    
    Args:
        client: RemoteClient instance
        cmd: Command to execute
    
    Returns:
        (stdout, stderr, exit_code)
    
    Raises:
        TimeoutError: If command execution times out
    """
    chan = client.client.invoke_shell()
    chan.send(cmd + "\n")
    chan.send("exit\n")
    
    buf = []
    start_time = time.time()
    
    try:
        while True:
            if chan.recv_ready():
                data = chan.recv(4096).decode()
                buf.append(data)
            
            if chan.exit_status_ready():
                # Read remaining data
                while chan.recv_ready():
                    data = chan.recv(4096).decode()
                    buf.append(data)
                break
            
            # Timeout check
            if time.time() - start_time > INTERACTIVE_TIMEOUT:
                chan.close()
                raise TimeoutError(
                    f"Command execution timeout after {INTERACTIVE_TIMEOUT}s"
                )
            
            time.sleep(0.1)
        
        exit_code = chan.recv_exit_status()
        output = "".join(buf)
        return output, "", exit_code
    
    finally:
        if not chan.closed:
            chan.close()


# ============================================================
# Script Preparation
# ============================================================

class ScriptContext:
    """Script execution context"""
    def __init__(
        self,
        remote_path: str,
        local_path: Optional[Path],
        need_cleanup: bool
    ):
        self.remote_path = remote_path
        self.local_path = local_path
        self.need_cleanup = need_cleanup


def prepare_script(
    script: ScriptExec, client: RemoteClient
) -> ScriptContext:
    """
    Prepare script execution environment.
    
    Returns:
        ScriptContext object
    """
    if is_remote_path(script.src):
        # Remote script: use directly
        remote_path = resolve_remote_path(client, script.src)
        return ScriptContext(remote_path, None, False)
    else:
        # Local script: upload to remote
        local_path = Path(script.src).expanduser()
        if not local_path.exists():
            raise FileNotFoundError(f"Script not found: {script.src}")
        
        remote_path = upload_script(client, local_path)
        return ScriptContext(remote_path, local_path, True)


def resolve_interpreter(
    script: ScriptExec,
    global_env: GlobalEnv,
    local_path: Optional[Path]
) -> Tuple[str, list[str]]:
    """
    Resolve interpreter and flags used by script.
    
    Returns:
        (interpreter_path, flags_list)
    """
    if script.exec_mode == "source":
        # source mode: use global interpreter
        return global_env.interpreter, global_env.flags or []
    else:
        # exec mode: resolve interpreter
        interpreter = (
            script.interpreter or
            (detect_shebang(local_path) if local_path else None) or
            global_env.interpreter
        )
        flags = (
            script.flags
            if script.flags is not None
            else (global_env.flags or [])
        )
        return interpreter, flags


def build_command(
    script: ScriptExec,
    interpreter: str,
    flags: list[str],
    remote_path: str,
    args: list[str]
) -> str:
    """
    Build command to execute.
    
    Args:
        script: ScriptExec object
        interpreter: Interpreter path
        flags: Interpreter flags
        remote_path: Remote script path
        args: Script arguments
    
    Returns:
        Complete command string
    """
    flag_str = " ".join(flags)
    arg_str = " ".join(args)
    
    if script.exec_mode == "source":
        return f'{interpreter} {flag_str} -c "source {remote_path} {arg_str}"'
    else:
        return f"{interpreter} {flag_str} {remote_path} {arg_str}"


# ============================================================
# Main Script Runner
# ============================================================

def run_script(
    script: ScriptExec,
    client: RemoteClient,
    global_env: GlobalEnv
) -> Tuple[str, str, int]:
    """
    Execute script.
    
    Process:
    1. Prepare script (upload local script or resolve remote script)
    2. Resolve interpreter and flags
    3. Build command
    4. Execute command
    5. Clean up temporary files
    
    Returns:
        (stdout, stderr, exit_code)
    """
    # Step 1: Prepare script
    ctx = prepare_script(script, client)
    
    try:
        # Step 2: Resolve interpreter
        interpreter, flags = resolve_interpreter(
            script, global_env, ctx.local_path
        )
        
        # Step 3: Build command
        args = script.args or []
        cmd = build_command(script, interpreter, flags, ctx.remote_path, args)
        logger.info(f"[run] {cmd}")
        
        # Step 4: Execute command
        if script.interactive:
            out, err, code = exec_interactive(client, cmd)
        else:
            out, err, code = exec_non_interactive(client, cmd, script.allow_fail)
        
        return out, err, code
    
    finally:
        # Step 5: Clean up temporary files
        if ctx.need_cleanup:
            delete_remote_file(client, ctx.remote_path)

