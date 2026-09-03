"""Orchestrator test suite package."""

import os

# Enable dev execution in automated unit tests so tests can run on any feature branch
os.environ.setdefault("NET_STREAM_ALLOW_DEV", "1")
