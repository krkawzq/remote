"""
共享工具函数
"""
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .client import RemoteClient


def is_remote_path(path: str) -> bool:
    """判断路径是否为远程路径（以 : 开头）"""
    return path.startswith(":")


def resolve_local_path(path: str) -> Path:
    """解析本地路径，展开 ~ 等符号"""
    return Path(path).expanduser()


def resolve_remote_path(client: "RemoteClient", path: str) -> str:
    """
    解析远程路径，展开 ~ 为远程 $HOME
    
    Args:
        client: RemoteClient 实例
        path: 远程路径，必须以 : 开头
    
    Returns:
        解析后的绝对路径
    
    Raises:
        AssertionError: 如果 path 不以 : 开头
    """
    assert path.startswith(":"), f"Remote path must start with ':', got: {path}"
    
    raw_path = path[1:]  # 去掉前缀 :
    
    if raw_path.startswith("~"):
        out, _ = client.exec("printf $HOME")
        home = out.strip() or "/root"
        return home + raw_path[1:]  # 去掉 ~
    
    return raw_path


# ============================================================
# 日志输出工具
# ============================================================

def log_info(message: str) -> None:
    """输出信息日志"""
    print(message)


def log_success(message: str) -> None:
    """输出成功日志"""
    print(f"[✓] {message}")


def log_error(message: str) -> None:
    """输出错误日志"""
    print(f"[✗] {message}")


def log_warn(message: str) -> None:
    """输出警告日志"""
    print(f"[!] {message}")

