"""
Utility functions for connect CLI module
"""
import re
from typing import Optional


def format_size(size_bytes: int) -> str:
    """
    Format bytes to human-readable size string.
    
    Args:
        size_bytes: Size in bytes
        
    Returns:
        Formatted string like "100 MB", "1.5 GB", etc.
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


def parse_size(size_str: str) -> Optional[int]:
    """
    Parse size string to bytes.
    
    Supports formats: "100M", "1GB", "500K", "2TB"
    
    Args:
        size_str: Size string (e.g., "100M", "1GB")
        
    Returns:
        Size in bytes, or None if invalid format
        
    Examples:
        "100M" -> 100 * 1024 * 1024
        "1GB" -> 1 * 1024 * 1024 * 1024
        "500K" -> 500 * 1024
    """
    size_str = size_str.strip().upper()
    
    # Match number and unit
    match = re.match(r'^(\d+)([KMGT]?B?)$', size_str)
    if not match:
        return None
    
    number = int(match.group(1))
    unit = match.group(2) or "B"
    
    multipliers = {
        "B": 1,
        "KB": 1024,
        "MB": 1024 * 1024,
        "GB": 1024 * 1024 * 1024,
        "TB": 1024 * 1024 * 1024 * 1024,
    }
    
    return number * multipliers.get(unit, 1)

