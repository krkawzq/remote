"""
Host string parser for connect command

Handles parsing of host strings in various formats:
- hostname
- user@hostname
- user@hostname:port
"""
from typing import Optional, Tuple


def parse_host_string(host: str, user: Optional[str] = None, port: Optional[int] = None) -> Tuple[str, Optional[str], Optional[int]]:
    """
    Parse host string into components.
    
    Supports formats:
    - "hostname"
    - "user@hostname"
    - "user@hostname:port"
    
    Args:
        host: Host string (may include user and port)
        user: Optional user override
        port: Optional port override
        
    Returns:
        Tuple of (hostname, user, port)
        
    Examples:
        parse_host_string("server") -> ("server", None, None)
        parse_host_string("user@server") -> ("server", "user", None)
        parse_host_string("user@server:2222") -> ("server", "user", 2222)
        parse_host_string("user@server:2222", port=3333) -> ("server", "user", 3333)
    """
    parsed_user = user
    parsed_host = host
    parsed_port = port
    
    # Parse user@host format
    if "@" in host:
        parts = host.split("@", 1)
        if len(parts) == 2:
            parsed_user = parts[0] if not parsed_user else parsed_user
            host_part = parts[1]
            
            # Check for port in host part (user@host:port)
            if ":" in host_part:
                host_port_parts = host_part.rsplit(":", 1)
                if len(host_port_parts) == 2:
                    parsed_host = host_port_parts[0]
                    try:
                        parsed_port = int(host_port_parts[1]) if not parsed_port else parsed_port
                    except ValueError:
                        # If port parsing fails, treat as part of path (e.g., IPv6)
                        parsed_host = host_part
            else:
                parsed_host = host_part
        else:
            parsed_host = host
    else:
        parsed_host = host
    
    return parsed_host, parsed_user, parsed_port

