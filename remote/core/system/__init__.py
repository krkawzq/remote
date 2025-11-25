"""
System state management
"""
from .machine import (
    get_local_machine_id,
    is_first_connect,
    register_machine,
    update_last_sync,
)

__all__ = [
    "get_local_machine_id",
    "is_first_connect",
    "register_machine",
    "update_last_sync",
]

