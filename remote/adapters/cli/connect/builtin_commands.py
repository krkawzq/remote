"""
Builtin commands for connect shell

All commands use unified command executor for consistent execution
"""
import sys
import shlex
import os
import time
from typing import List, Dict, Callable
from pathlib import Path

from ....domain.transfer.connect.models import ConnectSession
from ....domain.transfer.connect.path_resolver import parse_path
from ....domain.transfer.connect.exec_helpers import exec_remote_with_code
from ....domain.transfer.connect.transfer import TransferHandler
from .config_manager import show_config, set_config
from .command_executor import CommandExecutor
from .utils import format_size


class BuiltinCommands:
    """Builtin command handlers"""
    
    def __init__(self, session: ConnectSession):
        """
        Initialize builtin commands.
        
        Args:
            session: Connect session
        """
        self.session = session
        self.executor = CommandExecutor(session)
        self.transfer_handler = TransferHandler()
    
    def cp(self, args: List[str]) -> int:
    """Copy files using TransferHandler"""
    if not args or len(args) < 2:
        print("Usage: cp <source> <destination>")
        return 1
    
        result = self.transfer_handler.copy(args, self.session)
    
    if result.success:
        return 0
    else:
        if result.stderr:
                sys.stderr.write(result.stderr.rstrip() + '\n')
            sys.stderr.flush()
        return result.exit_code

    def ls(self, args: List[str]) -> int:
    """List directory"""
    # Parse arguments: extract options and path
    options = []
    path_str = None
    
    for arg in args:
        if arg.startswith("-"):
            options.append(arg)
        elif path_str is None:
            path_str = arg
    
    # If no path specified, use default based on last cd context
    if path_str is None:
            path_str = self.session.get_default_path()
    
        return self.executor.execute_with_options("ls", options, [path_str] if path_str else [])
    
    def cd(self, args: List[str]) -> int:
    """Change directory"""
    if not args:
        print("Usage: cd <path>")
        return 1
    
    path_str = args[0]
    
    # If path doesn't start with ':', determine context from last_cd_was_remote
    if not path_str.startswith(":"):
            if self.session.last_cd_was_remote:
            path_str = ":" + path_str
    
        path_spec = parse_path(path_str, self.session)
    
    # Update session
    if path_spec.is_remote:
        # Change remote directory
            result = exec_remote_with_code(
                f"cd {shlex.quote(path_spec.resolved)} && pwd",
                self.session.client
            )
        
        if result.exit_code != 0 or not result.stdout:
            sys.stderr.write(f"cd: {path_str}: No such file or directory\n")
            sys.stderr.flush()
            return 1
        
        new_cwd = result.stdout.strip()
            self.session.update_cwd(True, new_cwd)
        return 0
    else:
        # Change local directory
        new_path = Path(path_spec.resolved)
        
        if not new_path.exists() or not new_path.is_dir():
            sys.stderr.write(f"cd: {path_str}: No such file or directory\n")
            sys.stderr.flush()
            return 1
        
            self.session.update_cwd(False, str(new_path))
        return 0

    def pwd(self, args: List[str]) -> int:
    """Print working directory"""
        print(f"Local:  {self.session.local_cwd}")
        print(f"Remote: {self.session.remote_cwd}")
    return 0

    def cat(self, args: List[str]) -> int:
    """Print file content"""
    if not args:
        print("Usage: cat <path>")
        return 1
    
        return self.executor.execute_simple("cat", args[0])
    
    def mkdir(self, args: List[str]) -> int:
    """Create directory"""
    if not args:
        print("Usage: mkdir <path>")
        return 1
    
        return self.executor.execute_simple("mkdir", args[0])
        
    def rm(self, args: List[str]) -> int:
    """Remove file or directory"""
    if not args:
        print("Usage: rm <path>")
        return 1
    
        return self.executor.execute_simple("rm", args[0])
        
    def du(self, args: List[str]) -> int:
    """Show disk usage"""
        path_str = args[0] if args else "."
        return self.executor.execute("du", ["-sh", path_str], path=path_str)
    
    def stat(self, args: List[str]) -> int:
    """Show file status"""
    if not args:
        print("Usage: stat <path>")
        return 1
    
        return self.executor.execute_simple("stat", args[0])
        
    def config(self, args: List[str]) -> int:
    """Show or set configuration"""
    if not args:
        # Show configuration
            print(show_config(self.session))
        return 0
    
    if args[0] == "show":
            print(show_config(self.session))
        return 0
    
    if args[0] == "set":
        if len(args) < 3:
            print("Usage: config set <key> <value>")
            return 1
        
        key = args[1]
        value = args[2]
        
            success, message = set_config(self.session, key, value)
        if success:
            print(message)
            return 0
        else:
            print(f"Error: {message}")
            return 1
    
    print("Usage: config [show|set <key> <value>]")
    return 1

    def status(self, args: List[str]) -> int:
    """Show session status"""
        uptime = time.time() - self.session.start_time
    uptime_str = f"{int(uptime // 60)}m {int(uptime % 60)}s"
    
    print(f"Session Status:")
        print(f"  Host: {self.session.user}@{self.session.host}:{self.session.port}")
        print(f"  Local directory: {self.session.local_cwd}")
        print(f"  Remote directory: {self.session.remote_cwd}")
    print(f"  Uptime: {uptime_str}")
        print(f"  Commands executed: {self.session.commands_executed}")
        print(f"  Bytes transferred: {format_size(self.session.bytes_transferred)}")
    return 0

    def help(self, args: List[str]) -> int:
    """Show help"""
    if args:
        cmd_name = args[0]
        if cmd_name in BUILTIN_COMMANDS:
            print(f"Help for '{cmd_name}':")
            print(HELP_TEXT.get(cmd_name, "No help available."))
            return 0
        else:
            print(f"Unknown command: {cmd_name}")
            return 1
    
    print("Available commands:")
    print("  cp <src> <dst>     - Copy files (supports : prefix for remote paths)")
    print("  ls [path]          - List directory")
    print("  cd <path>          - Change directory")
    print("  pwd                - Print working directories")
    print("  cat <path>         - Print file content")
    print("  mkdir <path>        - Create directory")
    print("  rm <path>          - Remove file or directory")
    print("  du [path]          - Show disk usage")
    print("  stat <path>        - Show file status")
    print("  config [show|set]  - Show or set configuration")
    print("  status             - Show session status")
    print("  clear              - Clear the terminal screen")
    print("  help [command]     - Show help")
    print("  exit               - Exit session")
    print("\nPath format:")
    print("  :path or :~/path   - Remote path")
    print("  path or ~/path     - Local path")
    print("\nForward commands:")
    print("  !command           - Execute in current context")
    print("  !local command     - Execute locally")
    print("  !remote command    - Execute remotely")
    return 0

    def clear(self, args: List[str]) -> int:
    """Clear the terminal screen"""
    os.system('clear' if os.name != 'nt' else 'cls')
    return 0

    def exit(self, args: List[str]) -> int:
    """Exit session"""
    return -1  # Special return code to signal exit


# Factory function to create command handlers
def create_command_handlers(session: ConnectSession) -> Dict[str, Callable[[List[str]], int]]:
    """
    Create command handlers for a session.
    
    Args:
        session: Connect session
        
    Returns:
        Dictionary mapping command names to handler functions
    """
    handlers = BuiltinCommands(session)
    
    return {
        'cp': handlers.cp,
        'ls': handlers.ls,
        'cd': handlers.cd,
        'pwd': handlers.pwd,
        'cat': handlers.cat,
        'mkdir': handlers.mkdir,
        'rm': handlers.rm,
        'du': handlers.du,
        'stat': handlers.stat,
        'config': handlers.config,
        'status': handlers.status,
        'clear': handlers.clear,
        'help': handlers.help,
        'exit': handlers.exit,
        'quit': handlers.exit,  # Alias
}


# Legacy compatibility: maintain global registry for backward compatibility
# This will be populated per-session in shell.py
BUILTIN_COMMANDS: Dict[str, Callable[[List[str], ConnectSession], int]] = {}

# Help text for commands
HELP_TEXT = {
    'cp': "Copy files between local and remote.\n"
          "  cp :~/file.txt ~/local.txt  # Download\n"
          "  cp ~/file.txt :~/remote.txt # Upload\n"
          "  cp :~/a.txt :~/b.txt        # Remote copy",
    'ls': "List directory contents.\n"
          "  ls           # List local current directory\n"
          "  ls :~/data   # List remote directory",
    'cd': "Change directory.\n"
          "  cd ~/projects  # Change local directory\n"
          "  cd :~/code     # Change remote directory",
    'pwd': "Print current working directories (local and remote).",
    'cat': "Print file content.\n"
           "  cat file.txt    # Local file\n"
           "  cat :~/file.txt # Remote file",
    'mkdir': "Create directory.\n"
             "  mkdir ~/newdir    # Local\n"
             "  mkdir :~/newdir   # Remote",
    'rm': "Remove file or directory.\n"
          "  rm file.txt    # Local\n"
          "  rm :~/file.txt # Remote",
    'du': "Show disk usage.\n"
          "  du           # Current directory\n"
          "  du :~/data   # Remote directory",
    'stat': "Show file status.\n"
            "  stat file.txt    # Local\n"
            "  stat :~/file.txt # Remote",
    'config': "Show or set configuration.\n"
              "  config show              # Show all settings\n"
              "  config set threshold 50M # Set large file threshold\n"
              "  config set parallel 8     # Set parallel connections",
    'status': "Show session status and statistics.",
    'clear': "Clear the terminal screen.",
    'help': "Show help for commands.",
    'exit': "Exit the connect session.",
}
