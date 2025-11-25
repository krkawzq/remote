"""
Interactive shell for connect session

Simplified single-loop architecture with exec helpers
"""
import sys
import os
import readline
import shlex
from pathlib import Path
from typing import Optional, List

from ....domain.transfer.connect.models import ConnectSession
from ....domain.transfer.connect.command_parser import CommandParser
from ....domain.transfer.connect.exec_helpers import exec_local, exec_remote_with_code
from .builtin_commands import create_command_handlers
from .utils import format_size


class ConnectShell:
    """Interactive shell for connect session"""
    
    def __init__(self, session: ConnectSession):
        """
        Initialize shell.
        
        Args:
            session: Connect session
        """
        self.session = session
        self.running = True
        self.history: List[str] = []
        self.command_parser = CommandParser()
        self.builtin_commands = create_command_handlers(session)
        
        # Setup tab completion
        self._setup_completion()
    
    def run(self) -> None:
        """Run interactive shell"""
        self._print_welcome()
        
        while self.running:
            try:
                # Generate prompt
                prompt = self._generate_prompt()
                
                # Read input
                try:
                    line = input(prompt).strip()
                except (EOFError, KeyboardInterrupt):
                    print("\nUse 'exit' to quit")
                    continue
                
                if not line:
                    continue
                
                # Record history
                self.history.append(line)
                
                # Parse command
                parsed = self.command_parser.parse(line, self.session)
                
                # Handle exit
                if parsed.name in ('exit', 'quit'):
                    break
                
                # Execute command
                exit_code = self._execute_command(parsed, line)
                
                # Check for exit signal
                if exit_code == -1:
                    break
                
                self.session.increment_command_count()
                
            except KeyboardInterrupt:
                print("\nUse 'exit' to quit")
            except Exception as e:
                print(f"Error: {e}", file=sys.stderr)
        
        self._print_goodbye()
    
    def _generate_prompt(self) -> str:
        """Generate shell prompt"""
        # Show context based on last cd operation
        context = "remote" if self.session.last_cd_was_remote else "local"
        return f"[{context}] $ "
    
    def _setup_completion(self) -> None:
        """Setup tab completion with zsh-style fuzzy case-insensitive matching"""
        def completer(text: str, state: int) -> Optional[str]:
            """Tab completion function"""
            if state == 0:
                # First call: find matches
                line = readline.get_line_buffer()
                begidx = readline.get_begidx()
                
                # Get the word being completed
                words = line[:begidx].split()
                if not words:
                    return None
                
                # Determine if remote or local based on context
                is_remote_context = self.session.last_cd_was_remote
                
                # Check if prefix starts with ':'
                if text.startswith(':'):
                    is_remote_context = True
                    prefix = text[1:]
                else:
                    prefix = text
                
                # Get matches
                matches = self._get_path_completions(prefix, is_remote_context)
                
                # Store matches and context for subsequent calls
                if not hasattr(completer, 'matches'):
                    completer.matches = []
                completer.matches = matches
                completer.is_remote = is_remote_context
            
            # Return next match
            try:
                match = completer.matches[state]
                # Add ':' prefix back if remote
                if completer.is_remote and not match.startswith(':') and not match.startswith('/'):
                    return ':' + match
                return match
            except (IndexError, AttributeError):
                return None
        
        readline.set_completer(completer)
        readline.parse_and_bind('tab: complete')
    
    def _get_path_completions(self, prefix: str, is_remote: bool) -> List[str]:
        """Get path completions with fuzzy case-insensitive matching"""
        if is_remote:
            return self._get_remote_completions(prefix)
        else:
            return self._get_local_completions(prefix)
    
    def _get_local_completions(self, prefix: str) -> List[str]:
        """Get local path completions"""
        if not prefix:
            # List current directory
            try:
                items = os.listdir(str(self.session.local_cwd))
                return sorted([item + '/' if (self.session.local_cwd / item).is_dir() else item for item in items])
            except Exception:
                return []
        
        # Resolve prefix
        if prefix.startswith('~'):
            base_path = Path.home()
            suffix = prefix[1:].lstrip('/')
        elif prefix.startswith('/'):
            base_path = Path('/')
            suffix = prefix[1:]
        else:
            base_path = self.session.local_cwd
            suffix = prefix
        
        # Find matches with fuzzy case-insensitive matching
        matches = []
        try:
            if suffix:
                # Split into directory and filename parts
                parts = suffix.split('/')
                dir_part = '/'.join(parts[:-1]) if len(parts) > 1 else ''
                file_part = parts[-1]
                
                # Resolve directory
                if dir_part:
                    search_dir = base_path / dir_part
                else:
                    search_dir = base_path
                
                if not search_dir.exists() or not search_dir.is_dir():
                    return []
                
                # Get all items in directory
                items = os.listdir(str(search_dir))
                
                # Fuzzy match: case-insensitive prefix match
                file_lower = file_part.lower()
                for item in items:
                    item_lower = item.lower()
                    if item_lower.startswith(file_lower):
                        full_path = search_dir / item
                        if dir_part:
                            match = f"{dir_part}/{item}"
                        else:
                            match = item
                        
                        # Add '/' if directory
                        if full_path.is_dir():
                            match += '/'
                        matches.append(match)
            else:
                # No prefix, list current directory
                items = os.listdir(str(base_path))
                matches = [item + '/' if (base_path / item).is_dir() else item for item in items]
        except Exception:
            return []
        
        return sorted(matches)
    
    def _get_remote_completions(self, prefix: str) -> List[str]:
        """Get remote path completions"""
        if not prefix:
            # List current remote directory
            try:
                cmd = f"ls -1 {shlex.quote(self.session.remote_cwd)}"
                stdout, _ = self.session.client.exec(cmd)
                if stdout:
                    items = [line.strip() for line in stdout.strip().split('\n') if line.strip()]
                    # Check which are directories
                    matches = []
                    for item in items:
                        # Check if directory
                        check_cmd = f"test -d {shlex.quote(self.session.remote_cwd + '/' + item)} && echo dir || echo file"
                        check_stdout, _ = self.session.client.exec(check_cmd)
                        if 'dir' in check_stdout:
                            matches.append(item + '/')
                        else:
                            matches.append(item)
                    return sorted(matches)
            except Exception:
                pass
            return []
        
        # Resolve prefix
        if prefix.startswith('~'):
            base_path = '~'
            suffix = prefix[1:].lstrip('/')
        elif prefix.startswith('/'):
            base_path = '/'
            suffix = prefix[1:]
        else:
            base_path = self.session.remote_cwd
            suffix = prefix
        
        # Find matches
        matches = []
        try:
            if suffix:
                # Split into directory and filename parts
                parts = suffix.split('/')
                dir_part = '/'.join(parts[:-1]) if len(parts) > 1 else ''
                file_part = parts[-1]
                
                # Resolve directory
                if dir_part:
                    if base_path == '~':
                        search_dir = f"~/{dir_part}"
                    elif base_path == '/':
                        search_dir = f"/{dir_part}"
                    else:
                        search_dir = f"{base_path.rstrip('/')}/{dir_part}"
                else:
                    search_dir = base_path
                
                # List directory contents
                cmd = f"ls -1 {shlex.quote(search_dir)}"
                stdout, _ = self.session.client.exec(cmd)
                if stdout:
                    items = [line.strip() for line in stdout.strip().split('\n') if line.strip()]
                    
                    # Fuzzy match: case-insensitive prefix match
                    file_lower = file_part.lower()
                    for item in items:
                        item_lower = item.lower()
                        if item_lower.startswith(file_lower):
                            if dir_part:
                                match = f"{dir_part}/{item}"
                            else:
                                match = item
                            
                            # Check if directory
                            check_cmd = f"test -d {shlex.quote(search_dir + '/' + item)} && echo dir || echo file"
                            check_stdout, _ = self.session.client.exec(check_cmd)
                            if 'dir' in check_stdout:
                                match += '/'
                            matches.append(match)
            else:
                # No prefix, list current directory
                cmd = f"ls -1 {shlex.quote(base_path)}"
                stdout, _ = self.session.client.exec(cmd)
                if stdout:
                    items = [line.strip() for line in stdout.strip().split('\n') if line.strip()]
                    matches = []
                    for item in items:
                        check_cmd = f"test -d {shlex.quote(base_path + '/' + item)} && echo dir || echo file"
                        check_stdout, _ = self.session.client.exec(check_cmd)
                        if 'dir' in check_stdout:
                            matches.append(item + '/')
                        else:
                            matches.append(item)
        except Exception:
            return []
        
        return sorted(matches)
    
    def _execute_command(self, parsed, original_line: str) -> int:
        """
        Execute command.
        
        Args:
            parsed: ParsedCommand
            original_line: Original command line
            
        Returns:
            Exit code (-1 for exit signal)
        """
        # Check if builtin command
        if parsed.name in BUILTIN_COMMANDS:
            handler = BUILTIN_COMMANDS[parsed.name]
            exit_code = handler(parsed.args, self.session)
            
            # Track cd commands for context update
            if parsed.name == 'cd' and exit_code == 0:
                # Context already updated by cmd_cd
                pass
            
            return exit_code
        
        # Not a builtin command, forward to shell
        # Check if it's a forwarded command (! prefix)
        is_forwarded = original_line.startswith("!")
        
        if is_forwarded:
            # Forwarded command: execute in appropriate context
            # Remove ! prefix and any explicit context markers
            cmd_line = original_line[1:].strip()
            if cmd_line.startswith("local "):
                cmd_line = cmd_line[6:].strip()
                is_remote = False
            elif cmd_line.startswith("remote "):
                cmd_line = cmd_line[7:].strip()
                is_remote = True
            else:
                # Use parsed context
                is_remote = parsed.is_remote
            
            # Execute forwarded command
            if is_remote:
                result = exec_remote_with_code(cmd_line, self.session.client, self.session.remote_cwd)
            else:
                result = exec_local(cmd_line, cwd=self.session.local_cwd)
            
            # Display output
            if result.stdout:
                sys.stdout.write(result.stdout)
                sys.stdout.flush()
            if result.stderr:
                sys.stderr.write(result.stderr)
                sys.stderr.flush()
            
            # Track directory changes for forwarded commands
            if "cd " in cmd_line.lower():
                self._update_cwd_after_forwarded_cd(cmd_line, is_remote)
            
            return result.exit_code
        else:
            # Unknown command
            print(f"Unknown command: {parsed.name}")
            print("Type 'help' for available commands, or use '!command' to execute on shell")
            return 1
    
    def _update_cwd_after_forwarded_cd(self, cmd_line: str, is_remote: bool):
        """Update CWD after a forwarded cd command"""
        try:
            if is_remote:
                # Get new remote directory
                result = exec_remote_with_code("pwd", self.session.client)
                if result.success and result.stdout:
                    new_cwd = result.stdout.strip()
                    self.session.update_cwd(True, new_cwd)
            else:
                # Get new local directory
                result = exec_local("pwd", cwd=self.session.local_cwd)
                if result.success and result.stdout:
                    new_cwd = result.stdout.strip()
                    self.session.update_cwd(False, new_cwd)
        except Exception:
            pass  # Ignore errors when updating CWD
    
    def _print_welcome(self) -> None:
        """Print welcome message"""
        print(f"Connected to {self.session.host} ({self.session.user}@{self.session.host}:{self.session.port})")
        print(f"Local:  {self.session.local_cwd}")
        print(f"Remote: {self.session.remote_cwd}")
        print("Type 'help' for commands, 'exit' to quit.\n")
    
    def _print_goodbye(self) -> None:
        """Print goodbye message"""
        from .builtin_commands import format_size
        
        print(f"\nGoodbye! Transferred: {format_size(self.session.bytes_transferred)}")
