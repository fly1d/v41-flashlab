"""V41 FlashLab benchmarks for OpenAI-compatible chat APIs."""

from .cases import BenchmarkCase, BenchmarkSuite, CaseFormatError, load_suite
from .client import ChatCompletion, OpenAIChatClient, Usage
from .scoring import ScoreResult, score_response
from .version import __version__

__all__ = [
    "BenchmarkCase",
    "BenchmarkSuite",
    "CaseFormatError",
    "ChatCompletion",
    "OpenAIChatClient",
    "ScoreResult",
    "Usage",
    "__version__",
    "load_suite",
    "score_response",
]
