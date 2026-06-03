# app/core/tools/registry.py

class ToolRegistry:
    def __init__(self):
        self._tools = {}

    def register(self, name, handler):
        self._tools[name] = handler

    def get(self, name):
        return self._tools.get(name)

    def all(self):
        return dict(self._tools)

tool_registry = ToolRegistry()