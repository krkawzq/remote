import re
import time
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Tuple, List

from ..client import RemoteClient
from ..utils import resolve_remote_path, log_info, log_warn


# ============================================================
# Data Models
# ============================================================

@dataclass
class TextBlock:
    """
    单个 block，对应多个 src 文件（模块）。
    每个 block 有自己的更新模式：
    - init
    - update
    - cover
    """
    name: str
    src: list[str]
    mode: Literal["init", "update", "cover"]


@dataclass
class BlockGroup:
    """
    一个 dist 文件包含若干 block，属于同一个 group。
    group_mode:
    - incremental：保留 unknown blocks
    - overwrite：完全重建 rmt 区域（删除 unknown blocks）
    """
    dist: str
    blocks: list[TextBlock]
    group_mode: Literal["incremental", "overwrite"]


# ============================================================
# Helper Functions
# ============================================================

def _calc_hash(text: str) -> str:
    """计算文本的 SHA256 哈希值（前16位）"""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _read_local_blocks(blk: TextBlock) -> Tuple[str, float]:
    """
    读取所有 src 文件，合并 body，返回合并内容和最大 mtime。
    
    Returns:
        (merged_content, latest_mtime)
    """
    bodies = []
    latest_mtime = 0.0

    for p in blk.src:
        path = Path(p).expanduser()
        body = path.read_text()
        bodies.append(body.rstrip() + "\n")
        latest_mtime = max(latest_mtime, path.stat().st_mtime)

    merged = "".join(bodies)
    return merged, latest_mtime


# ============================================================
# Main Sync Logic
# ============================================================

def sync_block_groups(groups: list[BlockGroup], client: RemoteClient) -> None:
    """
    同步多个 BlockGroup
    """
    for group in groups:
        _sync_one_group(group, client)


def _sync_one_group(group: BlockGroup, client: RemoteClient) -> None:
    """
    一个 dist 文件对应一个 group
    group_mode:
      - incremental：保留 unknown blocks
      - overwrite：删除 unknown blocks
    """
    remote_path = resolve_remote_path(client, group.dist)
    sftp = client.open_sftp()

    # ============================================================
    # STEP 1: read remote file
    # ============================================================
    try:
        with sftp.open(remote_path, "r") as f:
            remote_text = f.read().decode()
    except IOError:
        remote_text = ""

    if not remote_text.endswith("\n"):
        remote_text += "\n"

    # ============================================================
    # STEP 2: detect global wrapper
    # ============================================================
    G_START = "# >>> rmt:global-start <<<"
    G_END   = "# <<< rmt:global-end <<<"

    has_global = G_START in remote_text

    # ============================================================
    # STEP 3: parse existing blocks
    # ============================================================
    block_pattern = re.compile(
        r"(?ms)^# >>> rmt-block:(?P<name>[\w\-]+) "
        r"src=(?P<src>.+?) "
        r"mtime=(?P<mtime>\d+) "
        r"hash=(?P<hash>[0-9a-f]+) <<<$"
        r"\n(?P<body>.*?)"
        r"^# <<< rmt-block:(?P=name) <<<\s*$"
    )

    existing_blocks = {m.group("name"): m for m in block_pattern.finditer(remote_text)}

    # ============================================================
    # STEP 4: block-level sync logic
    # ============================================================
    new_blocks = []
    warnings = []

    for blk in group.blocks:
        new_body, new_mtime = _read_local_blocks(blk)
        new_hash = _calc_hash(new_body)

        # BLOCK EXISTS?
        existed = blk.name in existing_blocks

        # parse remote block if exists
        if existed:
            m = existing_blocks[blk.name]
            old_hash = m.group("hash")
            old_mtime = float(m.group("mtime"))
        else:
            old_hash = None
            old_mtime = None

        # --------------------------------------------------------
        # block-mode: init
        # --------------------------------------------------------
        if blk.mode == "init":
            if has_global:
                # 已存在 global，不写入
                continue
            # 第一次写入（global 新建时添加）
            new_blocks.append((blk.name, blk.src, new_mtime, new_hash, new_body))
            continue

        # --------------------------------------------------------
        # block-mode: update
        # --------------------------------------------------------
        if blk.mode == "update":
            if existed:
                # mtime 不新 → 无需更新
                if new_mtime <= old_mtime:
                    continue

                # hash 冲突 → 拒绝
                if new_hash != old_hash:
                    warnings.append(
f"""
[WARN] Block '{blk.name}' was manually modified on the remote. Update is rejected!
Local hash:  {new_hash}
Remote hash: {old_hash}
Local mtime:  {time.ctime(new_mtime)}
Remote mtime: {time.ctime(old_mtime)}

If you want to overwrite, please set block.mode to 'cover' and try again.
"""
                    )
                    continue
            # 否则需要添加或更新
            new_blocks.append((blk.name, blk.src, new_mtime, new_hash, new_body))
            continue

        # --------------------------------------------------------
        # block-mode: cover
        # --------------------------------------------------------
        if blk.mode == "cover":
            new_blocks.append((blk.name, blk.src, new_mtime, new_hash, new_body))
            continue

    # ============================================================
    # FAIL IF WARNINGS
    # ============================================================
    if warnings:
        sftp.close()
        for warning in warnings:
            log_warn(warning)
        raise RuntimeError("[ERROR] sync aborted due to remote modifications.")

    # ============================================================
    # STEP 5: build new global-block region
    # ============================================================
    # strip old region
    if has_global:
        wrapper_pattern = re.compile(
            rf"(?ms){re.escape(G_START)}.*?{re.escape(G_END)}"
        )
        untouched = wrapper_pattern.sub("", remote_text).rstrip() + "\n"
    else:
        untouched = remote_text

    # build wrapper
    wrapper_lines = [G_START]

    # group_mode: incremental → 保留 unknown blocks
    if group.group_mode == "incremental" and has_global:
        for name, m in existing_blocks.items():
            if name not in [blk.name for blk in group.blocks]:
                src = m.group("src")
                mtime = m.group("mtime")
                hsh = m.group("hash")
                body = m.group("body")
                wrapper_lines.append(
                    f"# >>> rmt-block:{name} src={src} mtime={mtime} hash={hsh} <<<"
                )
                wrapper_lines.append(body)
                wrapper_lines.append(f"# <<< rmt-block:{name} <<<")

    # new or updated blocks
    for name, src_list, mtime, hsh, body in new_blocks:
        src_str = ",".join(src_list)
        wrapper_lines.append(
            f"# >>> rmt-block:{name} src={src_str} mtime={int(mtime)} hash={hsh} <<<"
        )
        wrapper_lines.append(body)
        wrapper_lines.append(f"# <<< rmt-block:{name} <<<")

    wrapper_lines.append(G_END)
    final_text = untouched + "\n".join(wrapper_lines) + "\n"

    # ============================================================
    # STEP 6: write back
    # ============================================================
    with sftp.open(remote_path, "w") as f:
        f.write(final_text)

    sftp.close()
    log_info(f"[block] Updated {remote_path}")
