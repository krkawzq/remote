"""
Configuration manager for connect session
"""
from typing import Optional, Tuple

from ....domain.transfer.connect.models import ConnectConfig, ConnectSession
from .utils import format_size, parse_size


def show_config(session: ConnectSession) -> str:
    """Show current configuration"""
    config = session.config
    output = []
    output.append("Connect Configuration:")
    output.append(f"  Large file threshold: {format_size(config.large_file_threshold)}")
    output.append(f"  Transfer parallel: {config.transfer_config.parallel}")
    output.append(f"  Transfer chunk size: {format_size(config.transfer_config.chunk)}")
    output.append(f"  Transfer resume: {'enabled' if config.transfer_config.resume else 'disabled'}")
    output.append(f"  Transfer aria2: {'enabled' if config.transfer_config.aria2 else 'disabled'}")
    output.append(f"  Timeout: {config.timeout}s")
    return "\n".join(output)


def set_config(session: ConnectSession, key: str, value: str) -> Tuple[bool, str]:
    """
    Set configuration value.
    
    Args:
        session: Connect session
        key: Configuration key
        value: Configuration value
    
    Returns:
        (success, message) tuple
    """
    config = session.config
    
    if key == "threshold":
        size_bytes = parse_size(value)
        if size_bytes is None:
            return False, f"Invalid size format: {value}. Use format like '100M', '1GB', etc."
        config.large_file_threshold = size_bytes
        return True, f"threshold = {format_size(size_bytes)}"
    
    elif key == "parallel":
        try:
            parallel = int(value)
            if parallel < 1 or parallel > 32:
                return False, "Parallel must be between 1 and 32"
            config.transfer_config.parallel = parallel
            return True, f"parallel = {parallel}"
        except ValueError:
            return False, f"Invalid integer: {value}"
    
    elif key == "chunk":
        size_bytes = parse_size(value)
        if size_bytes is None:
            return False, f"Invalid size format: {value}. Use format like '4M', '1MB', etc."
        config.transfer_config.chunk = size_bytes
        return True, f"chunk = {format_size(size_bytes)}"
    
    elif key == "resume":
        if value.lower() in ("true", "1", "yes", "on", "enabled"):
            config.transfer_config.resume = True
            return True, "resume = enabled"
        elif value.lower() in ("false", "0", "no", "off", "disabled"):
            config.transfer_config.resume = False
            return True, "resume = disabled"
        else:
            return False, f"Invalid boolean value: {value}"
    
    elif key == "aria2":
        if value.lower() in ("true", "1", "yes", "on", "enabled"):
            config.transfer_config.aria2 = True
            return True, "aria2 = enabled"
        elif value.lower() in ("false", "0", "no", "off", "disabled"):
            config.transfer_config.aria2 = False
            return True, "aria2 = disabled"
        else:
            return False, f"Invalid boolean value: {value}"
    
    elif key == "timeout":
        try:
            timeout = int(value)
            if timeout < 1 or timeout > 300:
                return False, "Timeout must be between 1 and 300 seconds"
            config.timeout = timeout
            return True, f"timeout = {timeout}s"
        except ValueError:
            return False, f"Invalid integer: {value}"
    
    else:
        return False, f"Unknown configuration key: {key}. Available keys: threshold, parallel, chunk, resume, aria2, timeout"

