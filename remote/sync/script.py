import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional, Tuple

from ..client import RemoteClient
from ..utils import is_remote_path, resolve_remote_path, log_info


# ============================================================
# Data Models
# ============================================================

@dataclass
class GlobalEnv:
    """全局解释器环境"""
    interpreter: str = "/bin/bash"     # 默认解释器
    flags: list[str] = None            # 解释器 flags，例如 ["-i"]


@dataclass
class ScriptExec:
    """单个脚本执行单元"""
    src: str                                     # 本地脚本 or 远程脚本 (":path")
    mode: Literal["exec", "source"] = "exec"     # 运行模式

    interpreter: Optional[str] = None            # 解释器覆盖
    flags: Optional[list[str]] = None            # 解释器 flags 覆盖
    args: Optional[list[str]] = None             # 脚本参数

    interactive: bool = False                    # 是否需要交互模式
    allow_fail: bool = False                     # 非零退出允许


# ============================================================
# Helpers
# ============================================================

def detect_shebang(path: Path) -> Optional[str]:
    """根据本地文件读取 shebang"""
    try:
        first = path.read_text().split("\n")[0].strip()
        if first.startswith("#!"):
            return first[2:].strip()
    except (OSError, IOError, IndexError) as e:
        return None
    return None


def upload_script(client: RemoteClient, local: Path) -> str:
    """上传本地脚本到远程 /tmp，返回远程路径"""
    remote_path = f"/tmp/rmt-{uuid.uuid4().hex}.sh"

    sftp = client.open_sftp()
    with sftp.open(remote_path, "w") as f:
        f.write(local.read_text())
    sftp.chmod(remote_path, 0o755)

    return remote_path


def delete_remote(client: RemoteClient, path: str) -> None:
    """删除远程临时文件"""
    try:
        sftp = client.open_sftp()
        sftp.remove(path)
    except (IOError, OSError):
        # 文件不存在或无权限删除，忽略
        pass


# ============================================================
# Exec Helpers
# ============================================================

def exec_non_interactive(
    client: RemoteClient, cmd: str, allow_fail: bool
) -> Tuple[str, str, int]:
    """非交互式执行命令，实时显示输出"""
    # 使用流式输出方法，实时显示 stdout 和 stderr
    out, err, code = client.exec_with_code_streaming(cmd)
    if code != 0 and not allow_fail:
        raise RuntimeError(
            f"[script failed]\ncmd: {cmd}\ncode: {code}\nstderr:\n{err}"
        )
    return out, err, code


def exec_interactive(client: RemoteClient, cmd: str) -> Tuple[str, str, int]:
    """
    使用 invoke_shell 交互式执行命令
    
    注意：这是一个简化实现，不支持真正的用户交互
    """
    chan = client.client.invoke_shell()
    chan.send(cmd + "\n")
    chan.send("exit\n")  # 执行完后退出

    buf = []
    timeout = 60  # 60秒超时
    start_time = time.time()
    
    while True:
        if chan.recv_ready():
            data = chan.recv(4096).decode()
            buf.append(data)
        
        if chan.exit_status_ready():
            # 读取剩余数据
            while chan.recv_ready():
                data = chan.recv(4096).decode()
                buf.append(data)
            break
        
        # 超时检查
        if time.time() - start_time > timeout:
            chan.close()
            raise TimeoutError(f"Command execution timeout after {timeout}s")
        
        # 避免 CPU 空转
        time.sleep(0.1)

    exit_code = chan.recv_exit_status()
    output = "".join(buf)
    
    return output, "", exit_code


# ============================================================
# Main Script Runner
# ============================================================

def run_script(
    script: ScriptExec, client: RemoteClient, global_env: GlobalEnv
) -> Tuple[str, str, int]:
    """
    执行一个 ScriptExec，支持本地 src 和远程 src，
    支持 exec/source/interpreter/flags/args/interactive，
    执行结束自动清理临时文件。
    
    Returns:
        (stdout, stderr, exit_code)
    """

    # ------------------------------------------------------------
    # Step 1: 准备 remote_script_path
    # ------------------------------------------------------------
    src_is_remote = is_remote_path(script.src)

    if src_is_remote:
        remote_script = resolve_remote_path(client, script.src)
        local_path = None
        need_cleanup = False

    else:
        local_path = Path(script.src).expanduser()
        if not local_path.exists():
            raise FileNotFoundError(f"Script not found: {script.src}")
        remote_script = upload_script(client, local_path)
        need_cleanup = True

    # ------------------------------------------------------------
    # Step 2: 解释器解析（优先级）
    # ------------------------------------------------------------
    interpreter = (
        script.interpreter or
        (detect_shebang(local_path) if local_path else None) or
        global_env.interpreter
    )

    flags = script.flags if script.flags is not None else (global_env.flags or [])
    args = script.args or []

    flag_str = " ".join(flags)
    arg_str = " ".join(args)

    # ------------------------------------------------------------
    # Step 3: 构建命令
    # ------------------------------------------------------------
    if script.mode == "source":
        # 使用全局解释器环境执行 source
        g_flag_str = " ".join(global_env.flags or [])
        cmd = f'{global_env.interpreter} {g_flag_str} -c "source {remote_script} {arg_str}"'

    elif script.mode == "exec":
        cmd = f"{interpreter} {flag_str} {remote_script} {arg_str}"

    else:
        raise RuntimeError(f"Unknown script mode: {script.mode}")

    log_info(f"[run] {cmd}")

    # ------------------------------------------------------------
    # Step 4: 执行命令
    # ------------------------------------------------------------
    try:
        if script.interactive:
            out, err, code = exec_interactive(client, cmd)
        else:
            out, err, code = exec_non_interactive(client, cmd, script.allow_fail)

    finally:
        # ------------------------------------------------------------
        # Step 5: 清理 tmp 文件
        # ------------------------------------------------------------
        if need_cleanup:
            delete_remote(client, remote_script)

    return out, err, code
