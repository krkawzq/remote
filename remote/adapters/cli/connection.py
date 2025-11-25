"""
Connection factory implementation
"""
from typing import Dict, Any

from ...core.interfaces import ConnectionFactory
from ...core.client import RemoteClient
from ...core.exceptions import ConnectionError


class RemoteConnectionFactory(ConnectionFactory):
    """RemoteClient connection factory"""
    
    def create(self, params: Dict[str, Any]) -> RemoteClient:
        """
        Create and connect SSH client.
        
        Args:
            params: Connection parameters dictionary
        
        Returns:
            Connected RemoteClient instance
        
        Raises:
            ConnectionError: If connection fails
        """
        # Determine auth method
        auth_method = "key" if params.get("key") else "password"
        
        client = RemoteClient(
            host=params["host"],
            user=params["user"],
            port=params.get("port", 22),
            auth_method=auth_method,
            password=params.get("password"),
            key_path=params.get("key"),
            timeout=params.get("timeout", 10),
        )
        
        try:
            client.connect()
            return client
        except Exception as e:
            raise ConnectionError(f"Failed to connect: {e}") from e

