"""
Central configuration for the multi-agent software development system.

Kept as a single flat module (rather than a package) so experiment
parameters are easy to find and tweak for dissertation runs.
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
    "openrouter": "openai/gpt-5",
}

# Model used by every agent by default.
LLM_MODEL = os.getenv("LLM_MODEL", _DEFAULT_MODEL_BY_PROVIDER.get(LLM_PROVIDER, "openai/gpt-5"))

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

# Max tokens for a single agent completion. This is a ceiling; the actual
# value used per call is dynamically reduced (see llm_client.py) to stay
# under MODEL_TPM_LIMIT once the prompt size for that specific call is
# known, since providers count (prompt_tokens + max_tokens) against a
# single per-minute budget and reject the request outright (HTTP 413) if
# that sum alone exceeds the limit - regardless of how much of the
# account's per-minute budget has actually been used so far. Default is
# provider-aware: Groq's tight TPM ceiling makes a large ceiling pointless,
# while OpenRouter's paid tiers can typically make good use of more.
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

# The tokens-per-minute ceiling for the model/tier you are actually using
# right now (check the `x-ratelimit-limit-tokens` response header, or your
# plan's limits on the provider's console).
_DEFAULT_TPM_LIMIT_BY_PROVIDER = {
    "groq": 8000,
    "openrouter": 200_000,
}
MODEL_TPM_LIMIT = int(
    os.getenv(
        "MODEL_TPM_LIMIT",
        str(_DEFAULT_TPM_LIMIT_BY_PROVIDER.get(LLM_PROVIDER, 8000)),
    )
)

# --- Per-agent completion token caps ---
# Requirements/architecture/review artifacts are short, structured JSON
# with a handful of fields - capping their completion budget low
# discourages the model from padding output with unnecessary verbosity.
# This is INDEPENDENT of which provider/TPM limit is in effect - it's a
# deliberate content-shape decision, not a rate-limit workaround (though
# on Groq it also happens to help stay under the tight TPM ceiling).
# Developer and Tester output (generated source code / test files) are
# the two roles whose length genuinely varies with task complexity, so
# they are NOT capped here - they get whatever the dynamic per-call
# budget (see llm_client._safe_max_tokens) allows, up to MAX_TOKENS.
AGENT_MAX_TOKENS = {
    "requirements": int(os.getenv("REQUIREMENTS_MAX_TOKENS", "6000")),
    "architecture": int(os.getenv("ARCHITECTURE_MAX_TOKENS", "6000")),
    "review": int(os.getenv("REVIEW_MAX_TOKENS", "6000")),
    "test_result": None,
    "developer": None,
}


# --- Retry / backoff for transient failures (rate limits, 5xx) ---
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "5"))
INITIAL_BACKOFF_SECONDS = float(os.getenv("INITIAL_BACKOFF_SECONDS", "2.0"))
BACKOFF_MULTIPLIER = float(os.getenv("BACKOFF_MULTIPLIER", "2.0"))

# --- Workflow control ---
# Max number of Developer -> Reviewer/Tester revision loops before the
# workflow is forcibly terminated with status "failed_max_revisions".
MAX_REVISIONS = int(os.getenv("MAX_REVISIONS", "2"))

# Timeout (seconds) for executing generated code / tests as subprocesses.
CODE_EXECUTION_TIMEOUT = int(os.getenv("CODE_EXECUTION_TIMEOUT", "30"))

# Per-test timeout (seconds), enforced via the pytest-timeout plugin.
PER_TEST_TIMEOUT = int(os.getenv("PER_TEST_TIMEOUT", "10"))

# --- Paths ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
TASKS_DIR = os.path.join(PROJECT_ROOT, "tasks")
RUNS_DIR = os.path.join(PROJECT_ROOT, "runs")
