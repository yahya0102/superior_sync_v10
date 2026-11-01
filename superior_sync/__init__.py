# -*- coding: utf-8 -*-
"""SUPERIOR SYNC ULTIMATE — حزمة النظام.

The version is declared here exactly once; ``pyproject.toml`` reads it
via ``[tool.setuptools.dynamic]``.  ``APP_VERSION`` remains as a
backwards-compatible alias used throughout the codebase.
"""
APP_NAME = "SUPERIOR SYNC ULTIMATE"
__version__ = "4.1.1"
APP_VERSION = __version__

__all__ = ["APP_NAME", "APP_VERSION", "__version__"]