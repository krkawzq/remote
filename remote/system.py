import json
import time
import uuid
import platform
import subprocess
from pathlib import Path
from typing import Dict, Any

from .client import RemoteClient
from .utils import resolve_remote_path


# ============================================================
# Local Machine ID
# ============================================================

def _read_local_machine_id() -> str:
    """
    获取本地机器码：
    - 优先读取系统 machine-id
    - 如果失败，则使用 ~/.rmt/machine-id 持久化生成
    """

    # 1. Linux/macOS
    if Path("/etc/machine-id").exists():
        return Path("/etc/machine-id").read_text().strip()

    # 2. Windows
    if platform.system().lower() == "windows":
        try:
            out = subprocess.check_output(
                ["wmic", "csproduct", "get", "UUID"],
                text=True
            ).splitlines()
            for line in out:
                if line.strip() and "UUID" not in line:
                    return line.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

    # 3. fallback → ~/.rmt/machine-id
    store = Path("~/.rmt/machine-id").expanduser()
    if store.exists():
        return store.read_text().strip()

    mid = uuid.uuid4().hex
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(mid)

    return mid


def get_local_machine_id() -> str:
    """对外接口，确保唯一性"""
    return _read_local_machine_id()


# ============================================================
# Remote State Management
# ============================================================

REMOTE_STATE_PATH = ":~/.rmt_state.json"


def load_remote_state(client: RemoteClient) -> Dict[str, Any]:
    """从远程读取状态文件，不存在则返回空结构"""
    remote_path = resolve_remote_path(client, REMOTE_STATE_PATH)
    sftp = client.open_sftp()

    try:
        with sftp.open(remote_path, "r") as f:
            text = f.read().decode()
            return json.loads(text)
    except IOError:
        return {"machines": {}}


def save_remote_state(client: RemoteClient, state: Dict[str, Any]) -> None:
    """保存状态到远程 JSON 文件"""
    remote_path = resolve_remote_path(client, REMOTE_STATE_PATH)
    sftp = client.open_sftp()

    payload = json.dumps(state, indent=2)
    with sftp.open(remote_path, "w") as f:
        f.write(payload)


# ============================================================
# High-Level APIs
# ============================================================

def ensure_remote_state(client: RemoteClient) -> Dict[str, Any]:
    """
    读取远程状态，
    如果不存在则新建基础结构。
    """
    state = load_remote_state(client)

    if "machines" not in state:
        state["machines"] = {}

    return state


def register_machine(
    client: RemoteClient, meta: Dict[str, Any] | None = None
) -> bool:
    """
    注册当前本地机器到远程，返回：
    - True → 当前机器是第一次连接
    - False → 之前连接过
    """

    mid = get_local_machine_id()
    state = ensure_remote_state(client)

    machines = state["machines"]

    is_first = mid not in machines

    if is_first:
        machines[mid] = {
            "first_connect": int(time.time()),
            "last_sync": None,
            "meta": meta or {},
        }
    else:
        # 更新 meta（可选）
        if meta:
            machines[mid]["meta"].update(meta)

    save_remote_state(client, state)
    return is_first


def is_first_connect(client: RemoteClient) -> bool:
    """判断是否第一次连接"""
    mid = get_local_machine_id()
    state = ensure_remote_state(client)
    return mid not in state["machines"]


def update_last_sync(client: RemoteClient) -> None:
    """更新最后一次同步时间"""
    mid = get_local_machine_id()
    state = ensure_remote_state(client)

    if mid not in state["machines"]:
        # 首次连接
        register_machine(client)

    state["machines"][mid]["last_sync"] = int(time.time())
    save_remote_state(client, state)
