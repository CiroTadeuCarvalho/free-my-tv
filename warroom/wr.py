#!/usr/bin/env python3
"""Atalho: python3 wr.py <comando> (o mesmo que python3 -m wr)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wr.cli import main  # noqa: E402

raise SystemExit(main())
