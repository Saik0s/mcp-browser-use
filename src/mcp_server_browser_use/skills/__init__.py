"""Skills subsystem for browser-use learning and hint injection.

Skills are MACHINE-GENERATED from successful learning sessions, not manually authored.
The workflow is:

1. LEARNING MODE: User calls run_browser_agent with learn=True
   - Agent executes with modified instructions (API discovery focus)
   - Recorder captures all network traffic
   - If agent finds an API endpoint that returns the data → success
   - Analyzer extracts skill (money request, parameters, navigation)
   - Skill is saved automatically

2. EXECUTION MODE: User calls run_browser_agent with skill_name
   - Skill is loaded from store
   - Hints are injected into agent prompt
   - Agent follows hints for efficient execution
   - Falls back to exploration if hints fail
"""

from .analyzer import SkillAnalyzer
from .executor import SkillExecutor
from .models import (
    FallbackConfig,
    MoneyRequest,
    NavigationStep,
    NetworkRequest,
    NetworkResponse,
    SessionRecording,
    Skill,
    SkillHints,
    SkillParameter,
)
from .recorder import SkillRecorder
from .store import SkillStore

__all__ = [
    # Models - Recording
    "NetworkRequest",
    "NetworkResponse",
    "SessionRecording",
    # Models - Skill
    "Skill",
    "SkillHints",
    "SkillParameter",
    "MoneyRequest",
    "NavigationStep",
    "FallbackConfig",
    # Components
    "SkillStore",
    "SkillExecutor",
    "SkillRecorder",
    "SkillAnalyzer",
]
