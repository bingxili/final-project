"""
Central configuration for the multi-agent software development system.
"""
import os
from dotenv import load_dotenv

load_dotenv(override=True)

# --- LLM provider selection ---
# "groq" (default - free)
# "openrouter"
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").lower()

# --- Groq API ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# --- OpenRouter API (OpenAI-compatible) ---
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
# Sensible default model per provider, only used if LLM_MODEL isn't set
# explicitly in .env - OpenRouter and Groq use different model name
# catalogues, so the "default" naturally differs.
_DEFAULT_MODEL_BY_PROVIDER = {
    "groq": "openai/gpt-oss-120b",
    "openrouter": "openai/gpt-oss-20b",
}

# Model used by every agent by default.
LLM_MODEL = os.getenv("LLM_MODEL", _DEFAULT_MODEL_BY_PROVIDER.get(LLM_PROVIDER, "openai/gpt-oss-120b"))

# --- Per-agent model overrides ---
# By default, every role uses LLM_MODEL - override individually via env vars if desired,
# e.g. in .env:
REQUIREMENTS_MODEL = os.getenv("REQUIREMENTS_MODEL", LLM_MODEL)
ARCHITECT_MODEL = os.getenv("ARCHITECT_MODEL", LLM_MODEL)
DEVELOPER_MODEL = os.getenv("DEVELOPER_MODEL", LLM_MODEL)
REVIEWER_MODEL = os.getenv("REVIEWER_MODEL", LLM_MODEL)
TESTER_MODEL = os.getenv("TESTER_MODEL", LLM_MODEL)

# Sampling temperature. Low-ish, since agents must produce structured,
# deterministic-ish JSON artifacts rather than creative text.
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.2"))

# Max tokens for a single agent completion. This is the global ceiling
# used when a role has no more specific AGENT_MAX_TOKENS entry (see
# below). Default is provider-aware, but can be overridden via the
# MAX_TOKENS env var if desired.
_DEFAULT_MAX_TOKENS_BY_PROVIDER = {
    "groq": 8192,
    "openrouter": 16384,
}
MAX_TOKENS = int(
    os.getenv(
        "MAX_TOKENS",
        str(_DEFAULT_MAX_TOKENS_BY_PROVIDER.get(LLM_PROVIDER, 8192)),
    )
)

# --- Per-agent completion token caps ---
# Requirements/architecture/review artifacts are short, structured JSON
# with a handful of fields, so they use conservative default completion
# caps to discourage unnecessary verbosity.
#
# Developer and Tester outputs (generated source code / test files) vary
# substantially with task complexity, so they have no agent-specific cap
# by default. Optional caps can still be supplied through the corresponding
# environment variables when needed.
#
# If a role has no entry (or the entry is None), MAX_TOKENS is used as
# the completion ceiling for that call instead.
AGENT_MAX_TOKENS = {
    "requirements": int(os.getenv("REQUIREMENTS_MAX_TOKENS", "16384")),
    "architecture": int(os.getenv("ARCHITECTURE_MAX_TOKENS", "16384")),
    "review": int(os.getenv("REVIEW_MAX_TOKENS", "16384")),
    "test_result": int(os.getenv("TEST_RESULT_MAX_TOKENS")) if os.getenv("TEST_RESULT_MAX_TOKENS") else None,
    "developer": int(os.getenv("DEVELOPER_MAX_TOKENS")) if os.getenv("DEVELOPER_MAX_TOKENS") else None,
}


# --- Retry / backoff for transient failures (rate limits, 5xx) ---
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "5"))
INITIAL_BACKOFF_SECONDS = float(os.getenv("INITIAL_BACKOFF_SECONDS", "2.0"))
BACKOFF_MULTIPLIER = float(os.getenv("BACKOFF_MULTIPLIER", "2.0"))

# --- Workflow control ---
# Max number of Developer -> Reviewer/Tester revision loops before the
# workflow is forcibly terminated with status "failed_max_revisions".
MAX_REVISIONS = int(os.getenv("MAX_REVISIONS", "2"))

# Whether the Developer writes and runs its own self-tests before handing
# off, and how many self-fix attempts it gets if they fail. This is a
# separate, internal loop from MAX_REVISIONS above (which governs the
# external Developer <-> Reviewer/Tester loop) - it's a fast local sanity
# check, not a replacement for QA's independent testing.
DEVELOPER_SELF_TEST_ENABLED = os.getenv("DEVELOPER_SELF_TEST_ENABLED", "true").lower() == "true"
DEVELOPER_SELF_FIX_ATTEMPTS = int(os.getenv("DEVELOPER_SELF_FIX_ATTEMPTS", "1"))

# Timeout (seconds) for executing generated code / tests as subprocesses.
CODE_EXECUTION_TIMEOUT = int(os.getenv("CODE_EXECUTION_TIMEOUT", "30"))

# Per-test timeout (seconds), enforced via the pytest-timeout plugin.
PER_TEST_TIMEOUT = int(os.getenv("PER_TEST_TIMEOUT", "10"))

# --- Paths ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
TASKS_DIR = os.path.join(PROJECT_ROOT, "tasks")
RUNS_DIR = os.path.join(PROJECT_ROOT, "runs")
