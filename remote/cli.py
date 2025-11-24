import typer
import tomllib
from pathlib import Path
from typing import Dict, Any

from .client import RemoteClient
from .system import (
    register_machine,
    update_last_sync,
    is_first_connect,
)
from .sync.file import FileSync, sync_files
from .sync.block import TextBlock, BlockGroup, sync_block_groups
from .sync.script import ScriptExec, GlobalEnv, run_script

app = typer.Typer(
    add_completion=False,
    help="SSH远程连接管理工具",
    no_args_is_help=True,
)


@app.callback()
def main():
    """
    rmt - SSH远程连接管理工具
    
    使用子命令来执行不同的操作：
    - sync: 同步远程服务器配置
    """
    pass


# ============================================================
# SSH Config Loader
# ============================================================

def load_ssh_config(hostname: str) -> Dict[str, Any]:
    """
    从 ~/.ssh/config 读取 Host xxx 的配置
    
    Args:
        hostname: SSH 配置中的 Host 名称
    
    Returns:
        包含 host, user, port, key_file 的字典
    """
    config_path = Path("~/.ssh/config").expanduser()
    if not config_path.exists():
        raise RuntimeError("~/.ssh/config 不存在")

    import paramiko
    ssh_config = paramiko.SSHConfig.from_path(str(config_path))

    entry = ssh_config.lookup(hostname)

    return {
        "host": entry.get("hostname", hostname),
        "user": entry.get("user", None),
        "port": int(entry.get("port", 22)),
        "key_file": entry.get("identityfile", [None])[0],
    }


# ============================================================
# Credential Handler
# ============================================================

def resolve_connection_params(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    解析 toml 中的远程连接方式：
    - host/user/port/password/key 可以缺省
    - 缺省参数会提示用户输入
    - 支持 ssh_config = "machine-name"
    - key 登录失败会 fallback 到 password
    
    Args:
        cfg: TOML 配置字典
    
    Returns:
        连接参数字典
    """
    params: Dict[str, Any] = {}

    # a) 如果设置了 ssh_config
    if "ssh_config" in cfg:
        entry = load_ssh_config(cfg["ssh_config"])
        params.update(entry)

    # b) 覆盖/补齐配置
    params["host"] = cfg.get("host", params.get("host"))
    params["user"] = cfg.get("user", params.get("user"))
    params["port"] = cfg.get("port", params.get("port", 22))

    params["key"] = cfg.get("key", params.get("key_file"))
    params["password"] = cfg.get("password", None)

    # c) 如果关键字段缺失 → 询问用户
    if not params["host"]:
        params["host"] = typer.prompt("远程主机 host")
    if not params["user"]:
        params["user"] = typer.prompt("SSH 用户名")
    if not params.get("port"):
        params["port"] = typer.prompt("SSH 端口", default=22)
        params["port"] = int(params["port"])

    # 密码可选，如果 key 失败会 fallback
    return params


# ============================================================
# Runner
# ============================================================

def run_sync_with_config(cfg: Dict[str, Any]) -> None:
    """
    根据配置文件执行同步任务
    
    Args:
        cfg: TOML 配置字典
    """
    # ------------------------------------------------------------
    # Step 1: 建立 SSH 连接
    # ------------------------------------------------------------
    params = resolve_connection_params(cfg)

    client = RemoteClient(
        host=params["host"],
        user=params["user"],
        port=params["port"],
        auth_method="key" if params.get("key") else "password",
        password=params.get("password"),
        key_path=params.get("key"),
    )

    # key 登录失败 fallback 到密码
    try:
        client.connect()
    except Exception:
        if params.get("password"):
            typer.echo("[warn] key 登录失败，尝试使用密码…")
            client = RemoteClient(
                host=params["host"],
                user=params["user"],
                port=params["port"],
                auth_method="password",
                password=params["password"],
            )
            client.connect()
        else:
            raise

    typer.echo(f"[connected] {params['user']}@{params['host']}:{params['port']}")

    # ------------------------------------------------------------
    # Step 2: system check
    # ------------------------------------------------------------
    if is_first_connect(client):
        typer.echo("[system] 第一次连接，注册本机信息…")
        register_machine(client, meta={"client": "rmt"})

    # ------------------------------------------------------------
    # Step 3: global environment
    # ------------------------------------------------------------
    global_env = GlobalEnv(
        interpreter=cfg.get("interpreter", "/bin/bash"),
        flags=cfg.get("interpreter_flags", []),
    )

    # ------------------------------------------------------------
    # Step 4: 执行 file sync
    # ------------------------------------------------------------
    if "file" in cfg:
        file_items = []
        for item in cfg["file"]:
            file_items.append(
                FileSync(
                    src=item["src"],
                    dist=item["dist"],
                    mode=item.get("mode", "sync"),
                )
            )
        sync_files(file_items, client)

    # ------------------------------------------------------------
    # Step 5: 执行 block sync
    # ------------------------------------------------------------
    if "block" in cfg:
        groups = []
        for group in cfg["block"]:
            blocks = []
            for blk in group["blocks"]:
                blocks.append(
                    TextBlock(
                        name=blk["name"],
                        src=blk["src"],
                        mode=blk.get("mode", "update"),
                    )
                )
            groups.append(
                BlockGroup(
                    dist=group["dist"],
                    group_mode=group.get("group_mode", "incremental"),
                    blocks=blocks,
                )
            )
        sync_block_groups(groups, client)

    # ------------------------------------------------------------
    # Step 6: 执行 scripts
    # ------------------------------------------------------------
    if "script" in cfg:
        for sc in cfg["script"]:
            script = ScriptExec(
                src=sc["src"],
                mode=sc.get("mode", "exec"),
                interpreter=sc.get("interpreter", None),
                flags=sc.get("flags", None),
                args=sc.get("args", None),
                interactive=sc.get("interactive", False),
                allow_fail=sc.get("allow_fail", False),
            )
            typer.echo(f"[script] 执行: {sc['src']}")
            out, err, code = run_script(script, client, global_env)
            # 输出已经在执行过程中实时显示了，这里只显示错误信息（如果有）
            if err and code != 0:
                typer.echo(f"[script] 错误输出:\n{err}", err=True)
            if code != 0:
                typer.echo(f"[script] 退出码: {code}")

    # ------------------------------------------------------------
    # Step 7: system update
    # ------------------------------------------------------------
    update_last_sync(client)
    typer.echo("[done] rmt sync 完成")



# ============================================================
# CLI Entry
# ============================================================

@app.command(name="sync")
def sync(config_path: str = typer.Argument(..., help="配置文件路径")):
    """
    同步远程服务器配置
    
    示例: rmt sync config.toml
    """
    path = Path(config_path).expanduser()
    if not path.exists():
        raise typer.Exit(f"配置文件不存在: {config_path}")

    cfg = tomllib.loads(path.read_text())
    run_sync_with_config(cfg)



def run():
    app()


if __name__ == "__main__":
    run()
