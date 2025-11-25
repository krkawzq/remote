"""
Transfer strategy selection

Chooses between SFTP and TransferService based on file size
"""
from typing import Literal

from .models import ConnectConfig


class TransferStrategy:
    """Transfer strategy selector"""
    
    @staticmethod
    def choose_method(file_size: int, config: ConnectConfig) -> Literal["sftp", "transfer"]:
        """
        Choose transfer method based on file size.
        
        Args:
            file_size: File size in bytes
            config: Connect configuration
        
        Returns:
            "sftp" for small files, "transfer" for large files
        """
        if file_size < config.large_file_threshold:
            return "sftp"
        return "transfer"
    
    @staticmethod
    def should_use_transfer_service(file_size: int, config: ConnectConfig) -> bool:
        """
        Check if TransferService should be used.
        
        Args:
            file_size: File size in bytes
            config: Connect configuration
        
        Returns:
            True if TransferService should be used
        """
        return file_size >= config.large_file_threshold


def choose_transfer_method(file_size: int, config: ConnectConfig) -> Literal["sftp", "transfer"]:
    """
    Convenience function to choose transfer method.
    
    Args:
        file_size: File size in bytes
        config: Connect configuration
    
    Returns:
        "sftp" or "transfer"
    """
    return TransferStrategy.choose_method(file_size, config)

