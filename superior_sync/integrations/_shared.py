#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared standard-library and optional dependency imports."""
from __future__ import annotations

import base64
import collections
import contextlib
import hashlib
import http.client
import ipaddress
import json
import math
import os
import platform
import random
import shlex
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import uuid
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable

from ..utils import (HAS_CRYPTO, HAS_PSUTIL, PathError,
                    atomic_write_bytes, atomic_write_json, human_size,
                    is_ignored, is_safe_external_url, log, read_json,
                    safe_join)

try:
    import psutil
except ImportError:
    psutil = None

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:
    Fernet = None
    InvalidToken = Exception


# ==================================================================
# تصنيف الأخطاء — المستوى، الفئة، الاقتراح
# ==================================================================
