"""
File-based state storage implementation
"""
import json
import os
from pathlib import Path
from typing import Dict, Any, Optional

from ...core.interfaces import StateStore
from ...core.exceptions import ProxyError
from ...core.constants import DEFAULT_STATE_DIR


class FileStateStore(StateStore):
    """
    File-based state storage.
    
    Stores state as JSON files in a directory structure:
    - {state_dir}/{name}.pid - Process ID
    - {state_dir}/{name}.json - State data
    - {state_dir}/{name}.out - Stdout log
    - {state_dir}/{name}.err - Stderr log
    """
    
    def __init__(self, state_dir: Optional[Path] = None):
        """
        Initialize file state store.
        
        Args:
            state_dir: Directory for storing state files
        """
        if state_dir is None:
            state_dir = Path(DEFAULT_STATE_DIR).expanduser()
        
        self.state_dir = Path(state_dir).expanduser()
        self.state_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_pid_file(self, name: str) -> Path:
        """Get PID file path for instance"""
        return self.state_dir / f"{name}.pid"
    
    def _get_state_file(self, name: str) -> Path:
        """Get state file path for instance"""
        return self.state_dir / f"{name}.json"
    
    def _get_log_file(self, name: str, stream: str = "out") -> Path:
        """Get log file path for instance"""
        return self.state_dir / f"{name}.{stream}"
    
    def save(self, name: str, state: Dict[str, Any]) -> None:
        """Save state for a named instance"""
        state_file = self._get_state_file(name)
        state_file.write_text(json.dumps(state, indent=2), encoding='utf-8')
    
    def load(self, name: str) -> Optional[Dict[str, Any]]:
        """Load state for a named instance"""
        state_file = self._get_state_file(name)
        if not state_file.exists():
            return None
        
        try:
            return json.loads(state_file.read_text(encoding='utf-8'))
        except Exception:
            return None
    
    def delete(self, name: str) -> None:
        """Delete state for a named instance"""
        # Remove PID file
        pid_file = self._get_pid_file(name)
        if pid_file.exists():
            pid_file.unlink()
        
        # Remove state file
        state_file = self._get_state_file(name)
        if state_file.exists():
            state_file.unlink()
        
        # Remove log files (optional, keep for debugging)
        # for stream in ["out", "err"]:
        #     log_file = self._get_log_file(name, stream)
        #     if log_file.exists():
        #         log_file.unlink()
    
    def list(self) -> list[str]:
        """List all instance names"""
        instances = set()
        for json_file in self.state_dir.glob("*.json"):
            name = json_file.stem
            # Verify PID file exists and process is running
            pid_file = self._get_pid_file(name)
            if pid_file.exists():
                try:
                    pid = int(pid_file.read_text().strip())
                    # Check if process exists
                    os.kill(pid, 0)
                    instances.add(name)
                except (OSError, ValueError):
                    # Process doesn't exist, clean up
                    self.delete(name)
        
        return sorted(instances)
    
    def exists(self, name: str) -> bool:
        """Check if state exists for a named instance"""
        pid_file = self._get_pid_file(name)
        if not pid_file.exists():
            return False
        
        try:
            pid = int(pid_file.read_text().strip())
            # Check if process exists
            os.kill(pid, 0)
            return True
        except (OSError, ValueError):
            # Process doesn't exist, clean up
            self.delete(name)
            return False
    
    def save_pid(self, name: str, pid: int) -> None:
        """Save process ID"""
        pid_file = self._get_pid_file(name)
        pid_file.write_text(str(pid))
    
    def load_pid(self, name: str) -> Optional[int]:
        """Load process ID"""
        pid_file = self._get_pid_file(name)
        if not pid_file.exists():
            return None
        
        try:
            return int(pid_file.read_text().strip())
        except (ValueError, OSError):
            return None
    
    def get_log_file(self, name: str, stream: str = "out") -> Path:
        """Get log file path"""
        return self._get_log_file(name, stream)

