"""Request lifecycle hooks for extensible processing without changing core logic.

This module provides a plugin-style hook system where custom pre/post-processing
can be injected without modifying the compose or optimize endpoints. Hooks are
called in definition order and must be idempotent (safe to retry).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

# Hook registry: ordered list of hooks to invoke
_GLOBAL_HOOKS: list[RequestHook] = []


class RequestHook(ABC):
    """Base class for request lifecycle hooks."""

    @abstractmethod
    def name(self) -> str:
        """Human-readable hook name for logging."""
        pass

    def pre_compose(self, request: Any) -> Any:
        """Called before compose is executed. Can modify request.
        
        Args:
            request: ComposeRequest instance
            
        Returns:
            Modified request, or original if unchanged
        """
        return request

    def post_compose(self, request: Any, response: Any) -> Any:
        """Called after compose completes successfully.
        
        Args:
            request: Original ComposeRequest
            response: ComposeResponse
            
        Returns:
            Modified response, or original if unchanged
        """
        return response

    def pre_optimize(self, request: Any) -> Any:
        """Called before optimize is executed."""
        return request

    def post_optimize(self, request: Any, response: Any) -> Any:
        """Called after optimize completes."""
        return response


def register_hook(hook: RequestHook) -> None:
    """Register a hook to be invoked for all requests."""
    _GLOBAL_HOOKS.append(hook)


def invoke_pre_compose(request: Any) -> Any:
    """Invoke all pre-compose hooks in order."""
    for hook in _GLOBAL_HOOKS:
        request = hook.pre_compose(request)
    return request


def invoke_post_compose(request: Any, response: Any) -> Any:
    """Invoke all post-compose hooks in order."""
    for hook in _GLOBAL_HOOKS:
        response = hook.post_compose(request, response)
    return response


def invoke_pre_optimize(request: Any) -> Any:
    """Invoke all pre-optimize hooks in order."""
    for hook in _GLOBAL_HOOKS:
        request = hook.pre_optimize(request)
    return request


def invoke_post_optimize(request: Any, response: Any) -> Any:
    """Invoke all post-optimize hooks in order."""
    for hook in _GLOBAL_HOOKS:
        response = hook.post_optimize(request, response)
    return response
