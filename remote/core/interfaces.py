"""
Core interfaces for dependency injection
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from pathlib import Path


class StateStore(ABC):
    """State storage interface"""
    
    @abstractmethod
    def save(self, name: str, state: Dict[str, Any]) -> None:
        """Save state for a named instance"""
        pass
    
    @abstractmethod
    def load(self, name: str) -> Optional[Dict[str, Any]]:
        """Load state for a named instance"""
        pass
    
    @abstractmethod
    def delete(self, name: str) -> None:
        """Delete state for a named instance"""
        pass
    
    @abstractmethod
    def list(self) -> list[str]:
        """List all instance names"""
        pass
    
    @abstractmethod
    def exists(self, name: str) -> bool:
        """Check if state exists for a named instance"""
        pass


class ConnectionFactory(ABC):
    """SSH connection factory interface"""
    
    @abstractmethod
    def create(self, params: Dict[str, Any]) -> Any:
        """Create and connect SSH client"""
        pass


class PromptProvider(ABC):
    """User prompt interface"""
    
    @abstractmethod
    def prompt(self, message: str, default: Optional[str] = None, password: bool = False) -> str:
        """Prompt user for input"""
        pass
    
    @abstractmethod
    def confirm(self, message: str, default: bool = False) -> bool:
        """Prompt user for confirmation"""
        pass

