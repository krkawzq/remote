"""
Configuration loader with priority: env > CLI > TOML > defaults
"""
import os
import tomllib
from pathlib import Path
from typing import Dict, Any, Optional, List


class ConfigLoader:
    """Configuration loader with priority support"""
    
    def __init__(self):
        self._env_prefix = "REMOTE_"
    
    def load_toml(self, path: Path) -> Dict[str, Any]:
        """Load TOML configuration file"""
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {path}")
        
        try:
            return tomllib.loads(path.read_text(encoding='utf-8'))
        except Exception as e:
            raise ValueError(f"Failed to parse TOML configuration: {e}") from e
    
    def load_env(self) -> Dict[str, Any]:
        """Load configuration from environment variables"""
        config = {}
        
        # Map environment variables to config keys
        env_mappings = {
            "REMOTE_HOST": "host",
            "REMOTE_USER": "user",
            "REMOTE_PORT": "port",
            "REMOTE_KEY": "key",
            "REMOTE_PASSWORD": "password",
            "REMOTE_TIMEOUT": "timeout",
            "REMOTE_PROXY_LOCAL_PORT": "proxy.local_port",
            "REMOTE_PROXY_REMOTE_PORT": "proxy.remote_port",
            "REMOTE_PROXY_MODE": "proxy.mode",
            "REMOTE_PROXY_LOCAL_HOST": "proxy.local_host",
        }
        
        for env_key, config_key in env_mappings.items():
            value = os.getenv(env_key)
            if value:
                # Handle nested keys
                if "." in config_key:
                    parts = config_key.split(".")
                    if parts[0] not in config:
                        config[parts[0]] = {}
                    config[parts[0]][parts[1]] = self._convert_value(value)
                else:
                    config[config_key] = self._convert_value(value)
        
        return config
    
    def _convert_value(self, value: str) -> Any:
        """Convert string value to appropriate type"""
        # Try boolean
        if value.lower() in ("true", "yes", "1"):
            return True
        if value.lower() in ("false", "no", "0"):
            return False
        
        # Try integer
        try:
            return int(value)
        except ValueError:
            pass
        
        # Return as string
        return value
    
    def merge_configs(self, *configs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merge multiple configurations with priority.
        Later configs override earlier ones.
        """
        result = {}
        
        for config in configs:
            result = self._deep_merge(result, config)
        
        return result
    
    def _deep_merge(self, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """Deep merge two dictionaries"""
        result = base.copy()
        
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        
        return result
    
    def load(
        self,
        toml_path: Optional[Path] = None,
        cli_overrides: Optional[Dict[str, Any]] = None,
        use_env: bool = True,
    ) -> Dict[str, Any]:
        """
        Load configuration with priority: env > CLI > TOML > defaults
        
        Args:
            toml_path: Path to TOML configuration file
            cli_overrides: CLI parameter overrides
            use_env: Whether to load from environment variables
        
        Returns:
            Merged configuration dictionary
        """
        configs = []
        
        # 1. Load TOML if provided
        if toml_path:
            configs.append(self.load_toml(toml_path))
        
        # 2. Load environment variables
        if use_env:
            env_config = self.load_env()
            if env_config:
                configs.append(env_config)
        
        # 3. Apply CLI overrides (highest priority)
        if cli_overrides:
            configs.append(cli_overrides)
        
        # Merge all configs
        return self.merge_configs(*configs)

