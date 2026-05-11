"""
LumenStudio - Script Interpreter

Executes commands and provides the scripting API.
Every GUI action translates to a command that is recorded and executed.
"""
import os
import sys
import traceback
from typing import Any, Dict, Optional, Callable
from pathlib import Path


class CommandRegistry:
    """Registry of all available commands."""
    
    _commands: Dict[str, Callable] = {}
    _aliases: Dict[str, str] = {}
    
    @classmethod
    def register(cls, name: str, func: Callable, aliases: list = None):
        """Register a command."""
        cls._commands[name] = func
        if aliases:
            for alias in aliases:
                cls._aliases[alias] = name
    
    @classmethod
    def get(cls, name: str) -> Optional[Callable]:
        """Get a command by name or alias."""
        if name in cls._commands:
            return cls._commands[name]
        if name in cls._aliases:
            return cls._commands[cls._aliases[name]]
        return None
    
    @classmethod
    def list_commands(cls) -> list:
        """List all available commands."""
        return sorted(cls._commands.keys())


class ScriptInterpreter:
    """
    Interprets and executes commands.
    
    Commands can be:
    - Function calls: place_component(device="nmos", x=100, y=200)
    - Direct assignments: library = "myLib"
    - Control flow: for, if, etc.
    """
    
    def __init__(self):
        self._context: Dict[str, Any] = {}
        self._result: Any = None
        self._error: Optional[str] = None
        self._output: list = []
        
        # Import and register all commands
        self._register_commands()
    
    def _register_commands(self):
        """Register all available commands."""
        from lumen.scripting import api
        import inspect
        
        # Get all public functions from api module
        for name, func in inspect.getmembers(api, inspect.isfunction):
            if not name.startswith('_'):
                CommandRegistry.register(name, func)
    
    def execute(self, command: str) -> Any:
        """
        Execute a command string.
        
        Args:
            command: Command string (e.g., "place_component(device='nmos')")
            
        Returns:
            Result of the command execution
        """
        self._error = None
        self._result = None
        self._output = []
        
        try:
            # Parse and execute as Python code
            result = eval(command, {"__builtins__": {}}, self._context)
            self._result = result
            return result
        except Exception as e:
            self._error = f"{type(e).__name__}: {str(e)}"
            # Log to output for debugging
            self._output.append(traceback.format_exc())
            return None
    
    def execute_script(self, script: str) -> list:
        """
        Execute a multi-line script.
        
        Args:
            script: Script text with multiple commands
            
        Returns:
            List of results from each command
        """
        results = []
        lines = script.split('\n')
        
        # Join lines to form complete statements
        current_stmt = ""
        for line in lines:
            stripped = line.strip()
            
            # Skip empty lines and comments
            if not stripped or stripped.startswith('#'):
                continue
            
            current_stmt += " " + stripped
            
            # Check if statement is complete
            # (simple heuristic: count parentheses)
            if current_stmt.count('(') == current_stmt.count(')'):
                if current_stmt.strip():
                    result = self.execute(current_stmt)
                    results.append(result)
                current_stmt = ""
        
        return results
    
    def get_result(self) -> Any:
        """Get the last result."""
        return self._result
    
    def get_error(self) -> Optional[str]:
        """Get the last error."""
        return self._error
    
    def get_output(self) -> list:
        """Get all output messages."""
        return self._output
    
    def set_context(self, key: str, value: Any):
        """Set a context variable."""
        self._context[key] = value
    
    def get_context(self, key: str) -> Any:
        """Get a context variable."""
        return self._context.get(key)
    
    def list_commands(self) -> list:
        """List available commands."""
        return CommandRegistry.list_commands()
    
    def help(self, command: str = "") -> str:
        """Get help for a command."""
        if not command:
            return f"Available commands: {', '.join(self.list_commands())}"
        
        func = CommandRegistry.get(command)
        if func:
            import inspect
            sig = inspect.signature(func)
            doc = func.__doc__ or "No documentation"
            return f"{command}{sig}\n\n{doc}"
        
        return f"Unknown command: {command}"


# Global interpreter instance
_interpreter: Optional[ScriptInterpreter] = None


def get_interpreter() -> ScriptInterpreter:
    """Get the global interpreter instance."""
    global _interpreter
    if _interpreter is None:
        _interpreter = ScriptInterpreter()
    return _interpreter


def execute_command(command: str) -> Any:
    """Execute a single command using the global interpreter."""
    return get_interpreter().execute(command)


def execute_script(script: str) -> list:
    """Execute a script using the global interpreter."""
    return get_interpreter().execute_script(script)