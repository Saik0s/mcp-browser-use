"""Skills subsystem for browser-use learning and direct execution.

Skills are MACHINE-GENERATED from successful learning sessions, not manually authored.
The workflow is:

1. LEARNING MODE: User calls run_browser_agent with learn=True
   - Agent executes with modified instructions (API discovery focus)
   - Recorder captures all network traffic via CDP
   - If agent finds an API endpoint that returns the data → success
   - Analyzer extracts skill (request details, parameters, parsing rules)
   - Skill is saved automatically

2. EXECUTION MODE (FAST): User calls run_browser_agent with skill_name
   - If skill.supports_direct_execution:
     - SkillRunner executes fetch() via CDP directly
     - No agent navigation needed (~1-3s vs ~60-120s)
     - Falls back to agent if auth fails
   - Otherwise:
     - Legacy hint-based execution via SkillExecutor
"""

from .analyzer import SkillAnalyzer
from .executor import SkillExecutor
from .models import (
    AuthRecovery,
    FallbackConfig,
    MoneyRequest,
    NavigationStep,
    NetworkRequest,
    NetworkResponse,
    SessionRecording,
    Skill,
    SkillHints,
    SkillParameter,
    SkillRequest,
)
from .recorder import SkillRecorder
from .runner import SkillRunner, SkillRunResult
from .store import SkillStore

__all__ = [
    # Models - Recording
    "NetworkRequest",
    "NetworkResponse",
    "SessionRecording",
    # Models - Skill (new direct execution)
    "Skill",
    "SkillRequest",
    "AuthRecovery",
    "SkillRunResult",
    # Models - Skill (legacy hints)
    "SkillHints",
    "SkillParameter",
    "MoneyRequest",
    "NavigationStep",
    "FallbackConfig",
    # Components
    "SkillStore",
    "SkillExecutor",
    "SkillRunner",  # NEW: Direct execution
    "SkillRecorder",
    "SkillAnalyzer",
]
