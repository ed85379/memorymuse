# app/core/commands/registry.py

class CommandRegistry:
    def __init__(self):
        self._commands = {}

    def register(self, name, handler):
        self._commands[name] = handler

    def get(self, name):
        return self._commands.get(name)

    def all(self):
        return dict(self._commands)

command_registry = CommandRegistry()