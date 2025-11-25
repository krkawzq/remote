"""
Transfer manifest storage implementation
"""
import json
from pathlib import Path
from typing import Optional, Dict, Any

from ...core.constants import DEFAULT_TRANSFER_STATE_DIR
from ...core.exceptions import TransferError


class TransferManifestStore:
    """
    File-based transfer manifest storage.
    
    Stores manifests as JSON files in ~/.remote/state/transfer/
    File names are SHA256 hashes of src+dst paths.
    """
    
    def __init__(self, state_dir: Optional[Path] = None):
        """
        Initialize transfer manifest store.
        
        Args:
            state_dir: Directory for storing manifest files
        """
        if state_dir is None:
            state_dir = Path(DEFAULT_TRANSFER_STATE_DIR).expanduser()
        
        self.state_dir = Path(state_dir).expanduser()
        self.state_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_manifest_file(self, key: str) -> Path:
        """Get manifest file path for key"""
        return self.state_dir / f"{key}.json"
    
    def save(self, key: str, manifest: Dict[str, Any]) -> None:
        """
        Save manifest for a transfer.
        
        Args:
            key: Manifest key (SHA256 hash)
            manifest: Manifest dictionary
        """
        manifest_file = self._get_manifest_file(key)
        manifest_file.write_text(
            json.dumps(manifest, indent=2),
            encoding='utf-8'
        )
    
    def load(self, key: str) -> Optional[Dict[str, Any]]:
        """
        Load manifest for a transfer.
        
        Args:
            key: Manifest key (SHA256 hash)
        
        Returns:
            Manifest dictionary or None if not found
        """
        manifest_file = self._get_manifest_file(key)
        if not manifest_file.exists():
            return None
        
        try:
            return json.loads(manifest_file.read_text(encoding='utf-8'))
        except Exception as e:
            raise TransferError(f"Failed to load manifest: {e}") from e
    
    def delete(self, key: str) -> None:
        """
        Delete manifest for a transfer.
        
        Args:
            key: Manifest key (SHA256 hash)
        """
        manifest_file = self._get_manifest_file(key)
        if manifest_file.exists():
            manifest_file.unlink()
    
    def exists(self, key: str) -> bool:
        """
        Check if manifest exists.
        
        Args:
            key: Manifest key (SHA256 hash)
        
        Returns:
            True if manifest exists
        """
        return self._get_manifest_file(key).exists()

