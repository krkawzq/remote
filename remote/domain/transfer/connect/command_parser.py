"""
Command parser for connect module

Simplified parser that extracts command structure and path information
"""
import shlex
from typing import Dict, List, Optional

from .models import ConnectSession, ParsedCommand, PathInfo
from .path_resolver import parse_path


class CommandParser:
    """Parse user commands into structured format"""
    
    def parse(self, line: str, session: ConnectSession) -> ParsedCommand:
        """
        Parse command line.
        
        Returns:
            ParsedCommand with name, options, args, paths, and context
        """
        # Handle empty line
        if not line.strip():
            return ParsedCommand(
                name="",
                options=[],
                args=[],
                paths={},
                is_remote=session.last_cd_was_remote,
            )
        
        # Handle ! prefix for forwarded commands
        is_forwarded = line.startswith("!")
        if is_forwarded:
            line = line[1:].strip()
        
        # Check for explicit context: !local or !remote
        explicit_context = None
        if is_forwarded:
            if line.startswith("local "):
                explicit_context = False
                line = line[6:].strip()
            elif line.startswith("remote "):
                explicit_context = True
                line = line[7:].strip()
        
        try:
            parts = shlex.split(line)
        except ValueError:
            # Invalid quoting, treat as single word
            parts = [line]
        
        if not parts:
            return ParsedCommand(
                name="",
                options=[],
                args=[],
                paths={},
                is_remote=session.last_cd_was_remote,
            )
        
        # Extract command name
        name = parts[0]
        
        # Separate options and arguments
        options = []
        args = []
        
        for part in parts[1:]:
            if part.startswith('-'):
                options.append(part)
            else:
                args.append(part)
        
        # Parse paths
        paths = {}
        for i, arg in enumerate(args):
            if self._is_path(arg):
                path_info = self._parse_path(arg, session)
                paths[i] = path_info
        
        # Determine context
        if explicit_context is not None:
            is_remote = explicit_context
        else:
            is_remote = self._determine_context(paths, session, is_forwarded)
        
        return ParsedCommand(
            name=name,
            options=options,
            args=args,
            paths=paths,
            is_remote=is_remote,
        )
    
    def _is_path(self, arg: str) -> bool:
        """Check if argument looks like a path"""
        return '/' in arg or arg.startswith('~') or arg.startswith(':') or arg in ('.', '..')
    
    def _parse_path(self, arg: str, session: ConnectSession) -> PathInfo:
        """Parse a path argument into PathInfo"""
        has_colon_prefix = arg.startswith(':')
        
        # Parse using path_resolver
        path_spec = parse_path(arg, session)
        
        return PathInfo(
            original=arg,
            has_colon_prefix=has_colon_prefix,
            is_remote=path_spec.is_remote,
            resolved_path=path_spec.resolved,
        )
    
    def _determine_context(
        self,
        paths: Dict[int, PathInfo],
        session: ConnectSession,
        is_forwarded: bool = False,
    ) -> bool:
        """
        Determine command execution context.
        
        Rules:
        - If any path has : prefix → use that path's context
        - If forwarded (!cmd) → use current context
        - Otherwise → use current context (last_cd_was_remote)
        """
        # Check if any path has explicit : prefix
        for path_info in paths.values():
            if path_info.has_colon_prefix:
                return path_info.is_remote
        
        # Use current context
        return session.last_cd_was_remote

