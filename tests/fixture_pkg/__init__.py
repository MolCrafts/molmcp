"""Fixture package used by molmcp's introspection tests.

Do not import in production. Only on the test path via pyproject's
``pythonpath = ["src", "tests"]``.
"""

from __future__ import annotations

__all__ = ["greet", "Widget"]


def greet(name: str) -> str:
    """Return a greeting for ``name``.

    A function used by molmcp tests to verify ``get_signature`` and
    ``get_docstring`` work for plain functions.
    """
    return f"hello, {name}"


class Widget:
    """A small example class with a method.

    Used by molmcp tests to verify class-level introspection — including
    classmethod / staticmethod / property / nested-class discovery and
    PEP 563 annotation resolution.
    """

    DEFAULT_FACTOR: float = 2.0

    class Config:
        """Nested config class."""

        verbose: bool = False

    def __init__(self, weight: float):
        self.weight = weight

    def grow(self, factor: float) -> Widget:
        """Multiply the widget's weight by ``factor`` and return self.

        Under ``from __future__ import annotations`` (PEP 563) the
        return annotation is stored as the string ``"Widget"``; tests
        verify that ``get_signature`` resolves it back to the class.
        """
        self.weight *= factor
        return self

    @classmethod
    def of_default(cls) -> Widget:
        """Build a Widget with weight ``DEFAULT_FACTOR``."""
        return cls(cls.DEFAULT_FACTOR)

    @staticmethod
    def double(x: float) -> float:
        """Return ``x * 2``."""
        return x * 2

    @property
    def heavy(self) -> bool:
        """Whether the widget weighs more than ten units."""
        return self.weight > 10
