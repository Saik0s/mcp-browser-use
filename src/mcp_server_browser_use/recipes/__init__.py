"""Recipes subsystem for browser-use learning and direct execution.

Recipes are MACHINE-GENERATED from successful learning sessions, not manually authored.
The workflow is:

1. LEARNING MODE: User calls run_browser_agent with learn=True
   - Agent executes with modified instructions (API discovery focus)
   - Recorder captures all network traffic via CDP
   - If agent finds an API endpoint that returns the data → success
   - Analyzer extracts recipe (request details, parameters, parsing rules)
   - Recipe is saved automatically

2. EXECUTION MODE (FAST): User calls run_browser_agent with recipe_name
   - If recipe.supports_direct_execution:
     - RecipeRunner executes fetch() via CDP directly
     - No agent navigation needed (~1-3s vs ~60-120s)
     - Falls back to agent if auth fails
   - Otherwise:
     - Legacy hint-based execution via RecipeExecutor
"""

from .analyzer import RecipeAnalyzer
from .executor import RecipeExecutor
from .models import (
    AuthRecovery,
    FallbackConfig,
    MoneyRequest,
    NavigationStep,
    NetworkRequest,
    NetworkResponse,
    Recipe,
    RecipeHints,
    RecipeParameter,
    RecipeRequest,
    SessionRecording,
)
from .recorder import RecipeRecorder
from .runner import RecipeRunner, RecipeRunResult
from .store import RecipeStore, get_default_recipes_dir

__all__ = [
    # Models - Recording
    "NetworkRequest",
    "NetworkResponse",
    "SessionRecording",
    # Models - Recipe (new direct execution)
    "Recipe",
    "RecipeRequest",
    "AuthRecovery",
    "RecipeRunResult",
    # Models - Recipe (legacy hints)
    "RecipeHints",
    "RecipeParameter",
    "MoneyRequest",
    "NavigationStep",
    "FallbackConfig",
    # Components
    "RecipeStore",
    "RecipeExecutor",
    "RecipeRunner",  # Direct execution
    "RecipeRecorder",
    "RecipeAnalyzer",
    "get_default_recipes_dir",
]
