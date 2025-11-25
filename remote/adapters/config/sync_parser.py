"""
Sync configuration parser
"""
from pathlib import Path
from typing import Dict, Any, List, Optional

from ...core.constants import (
    DEFAULT_INTERPRETER,
    DEFAULT_BLOCK_HOME,
    DEFAULT_SCRIPT_HOME,
)
from ...domain.sync import FileSync, BlockGroup, TextBlock, ScriptExec, GlobalEnv


def resolve_path_with_home(path: str, home_dir: Optional[str] = None) -> str:
    """
    Resolve path, relative to home_dir if provided.
    
    Absolute paths and paths starting with ~ are not modified.
    
    Args:
        path: Original path
        home_dir: Base directory (optional)
    
    Returns:
        Resolved path
    """
    if home_dir:
        if path.startswith('/') or path.startswith('~'):
            return path
        return str(Path(home_dir) / path)
    return path


def resolve_home_dirs(
    cfg: Dict[str, Any],
    config_file_path: Optional[Path]
) -> tuple[str, str]:
    """
    Resolve block_home and script_home directory paths.
    
    Args:
        cfg: TOML configuration dictionary
        config_file_path: Configuration file path
    
    Returns:
        (block_home, script_home)
    """
    block_home = cfg.get("block_home", DEFAULT_BLOCK_HOME)
    script_home = cfg.get("script_home", DEFAULT_SCRIPT_HOME)
    
    if config_file_path:
        config_dir = config_file_path.parent
        if not Path(block_home).is_absolute():
            block_home = str(config_dir / block_home)
        if not Path(script_home).is_absolute():
            script_home = str(config_dir / script_home)
    
    return block_home, script_home


def parse_file_configs(cfg: Dict[str, Any]) -> List[FileSync]:
    """Parse file configuration items"""
    if "file" not in cfg:
        return []
    
    return [
        FileSync(
            src=item["src"],
            dist=item["dist"],
            mode=item.get("mode", "sync"),
        )
        for item in cfg["file"]
    ]


def parse_block_configs(
    cfg: Dict[str, Any],
    block_home: str
) -> List[BlockGroup]:
    """Parse block configuration items"""
    if "block" not in cfg:
        return []
    
    groups = []
    block_configs = cfg["block"]
    if isinstance(block_configs, dict):
        block_configs = [block_configs]
    
    for group_cfg in block_configs:
        blocks = []
        for blk_cfg in group_cfg["blocks"]:
            src = blk_cfg["src"]
            src_list = (
                [resolve_path_with_home(src, block_home)]
                if isinstance(src, str)
                else [resolve_path_with_home(s, block_home) for s in src]
            )
            
            blocks.append(
                TextBlock(
                    src=src_list,
                    mode=blk_cfg.get("mode", "update"),
                )
            )
        
        groups.append(
            BlockGroup(
                dist=group_cfg["dist"],
                mode=group_cfg.get("mode", "incremental"),
                blocks=blocks,
            )
        )
    
    return groups


def parse_script_configs(
    cfg: Dict[str, Any],
    script_home: str,
    is_first: bool
) -> List[ScriptExec]:
    """Parse script configuration items"""
    if "script" not in cfg:
        return []
    
    scripts = []
    for sc_cfg in cfg["script"]:
        script_mode = sc_cfg.get("mode", "always")
        
        # Skip if init mode and not first connection
        if script_mode == "init" and not is_first:
            # Will be handled by SyncService
            pass
        
        script_src = resolve_path_with_home(sc_cfg["src"], script_home)
        scripts.append(
            ScriptExec(
                src=script_src,
                mode=script_mode,
                exec_mode=sc_cfg.get("exec_mode", "exec"),
                interpreter=sc_cfg.get("interpreter", None),
                flags=sc_cfg.get("flags", None),
                args=sc_cfg.get("args", None),
                interactive=sc_cfg.get("interactive", False),
                allow_fail=sc_cfg.get("allow_fail", False),
            )
        )
    
    return scripts


def parse_global_env(cfg: Dict[str, Any]) -> GlobalEnv:
    """Parse global environment configuration"""
    return GlobalEnv(
        interpreter=cfg.get("interpreter", DEFAULT_INTERPRETER),
        flags=cfg.get("interpreter_flags", []),
    )

