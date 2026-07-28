"""
Thin wrapper around the LLM chat completion API. Supports two
interchangeable providers, selected via config.LLM_PROVIDER:
  - "groq" (default): Groq's native SDK.
  - "openrouter": OpenAI-compatible SDK pointed at OpenRouter's API -
    typically much higher rate limits (paid), wider model choice.
Both expose the same Chat Completions request/response shape and the
same exception class names/attributes, so the rest of this module
(retry logic, structured-output parsing) doesn't need to know which
provider is active.

Responsibilities:
  - Sequential (synchronous) calls - no concurrency needed for this
    experiment-scale pipeline.
  - Basic retry with exponential backoff on rate limit (429) and
    transient server (5xx) errors.
  - Structured output: agents ask the model for JSON matching a given
    Pydantic schema; if parsing/validation fails, we retry once with a
    "repair" message that includes the validation error, before giving up.
"""
from __future__ import annotations

import json
import re
import time
from typing import Type, TypeVar, Union

from pydantic import BaseModel, ValidationError

import config

if config.LLM_PROVIDER == "openrouter":
    from openai import OpenAI as _ProviderClient
    from openai import APIStatusError, APIConnectionError
else:
    from groq import Groq as _ProviderClient
    from groq import APIStatusError, APIConnectionError

T = TypeVar("T", bound=BaseModel)

_client: "_ProviderClient | None" = None

# Set once per run by runner.py so call_structured can log truncation-retry
# events to that run's workflow_log.jsonl without threading run_dir through
# every agent function signature (agents only care about their own I/O).
_current_run_dir: str | None = None


def set_current_run_dir(run_dir: str | None) -> None:
    global _current_run_dir
    _current_run_dir = run_dir


def get_client() -> "_ProviderClient":
    global _client
    if _client is None:
        if config.LLM_PROVIDER == "openrouter":
            if not config.OPENROUTER_API_KEY:
                raise RuntimeError(
                    "LLM_PROVIDER=openrouter but OPENROUTER_API_KEY is not set. "
                    "Add it to .env."
                )
            _client = _ProviderClient(
                api_key=config.OPENROUTER_API_KEY,
                base_url=config.OPENROUTER_BASE_URL,
            )
        else:
            if not config.GROQ_API_KEY:
                raise RuntimeError(
                    "GROQ_API_KEY is not set. Copy .env.example to .env and add your key."
                )
            _client = _ProviderClient(api_key=config.GROQ_API_KEY)
    return _client


class LLMCallStats:
    """Simple mutable counters shared across a workflow run for logging."""

    def __init__(self) -> None:
        self.total_calls = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_tokens = 0

    def record(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.total_calls += 1
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        self.total_tokens += prompt_tokens + completion_tokens


class LLMOutputTruncatedError(RuntimeError):
    """Raised when a model response was cut off by max_tokens before the
    model finished writing its JSON output."""


class LLMEmptyResponseError(RuntimeError):
    """Raised when the model returned no content at all (empty/None
    message.content) despite finishing normally (finish_reason != "length",
    which is handled separately as LLMOutputTruncatedError). Seen in
    practice with some OpenRouter-routed models under transient upstream
    provider hiccups - not a JSON formatting problem, so a "fix your JSON"
    repair prompt makes no sense; a plain retry is the right response."""


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, APIConnectionError):
        return True
    if isinstance(exc, APIStatusError):
        # 429 = rate limit, 5xx = transient server error
        return exc.status_code == 429 or exc.status_code >= 500
    return False


_RETRY_AFTER_TEXT_RE = re.compile(r"try again in ([\d.]+)s", re.IGNORECASE)


def _retry_after_seconds(exc: Exception) -> float | None:
    """Best-effort extraction of how long to wait before retrying a 429.

    Groq's rate-limit error tells us exactly how long until the per-minute
    window frees up (e.g. "Please try again in 27.2s"), either in a
    `retry-after` response header or in the error message text. Using that
    exact figure is far more reliable than guessing with generic
    exponential backoff, which can either give up too early (if the real
    wait is longer) or waste time (if it's much shorter).
    """
    response = getattr(exc, "response", None)
    header_value = response.headers.get("retry-after") if response is not None else None
    if header_value:
        try:
            return float(header_value)
        except ValueError:
            pass

    message = str(exc)
    match = _RETRY_AFTER_TEXT_RE.search(message)
    if match:
        return float(match.group(1))
    return None



# Conservative chars-per-token estimate for this content (structured JSON
# with embedded source code tends to tokenize less efficiently than plain
# English prose). Deliberately on the low side (i.e. overestimates token
# count) so the safety margin below is not accidentally eaten into.
#_CHARS_PER_TOKEN_ESTIMATE = 3.3
_CHARS_PER_TOKEN_ESTIMATE = 4.0

# Tokens deliberately left unused as a buffer against the token estimate
# being imperfect (the real tokenizer isn't available to us here).
_SAFETY_MARGIN_TOKENS = 300


def _estimate_tokens(char_count: int) -> int:
    return int(char_count / _CHARS_PER_TOKEN_ESTIMATE) + 1


def _safe_max_tokens(messages: list[dict], agent_role: str | None = None) -> int:
    prompt_chars = sum(len(m.get("content") or "") for m in messages)
    estimated_prompt_tokens = _estimate_tokens(prompt_chars)

    budget = (
        config.MODEL_TPM_LIMIT
        - estimated_prompt_tokens
        - _SAFETY_MARGIN_TOKENS
    )

    print(
        f"[llm] agent_role={agent_role}, prompt_chars={prompt_chars}, "
        f"estimated_prompt_tokens={estimated_prompt_tokens}, "
        f"completion_budget={budget}"
    )

    if budget < 1500:
        raise RuntimeError(
            f"Prompt too large: only {budget} completion tokens remain."
        )

    ceiling = config.MAX_TOKENS
    # Non-developer roles produce short, structured artifacts - cap their
    # completion budget well below the TPM-derived ceiling so they don't
    # consume more of the per-minute budget than they need. Developer
    # (agent_role == "developer" or None) is left uncapped beyond the
    # dynamic TPM budget, since generated code length genuinely varies.
    role_cap = config.AGENT_MAX_TOKENS.get(agent_role) if agent_role else None
    if role_cap is not None:
        ceiling = min(ceiling, role_cap)

    return min(ceiling, budget)


def _sanitize_json_string_literals(text: str) -> str:
    """
    Best-effort local repair for a very common LLM JSON failure mode: raw
    control characters (literal newlines/tabs/carriage returns) left
    un-escaped inside JSON string values - typically when the model embeds
    multi-line source code as a string. This walks the text tracking
    whether we are inside a string literal (respecting `\\` escapes) and
    escapes any raw control characters found there.

    Doing this locally (no LLM call) avoids paying for an expensive
    "repair" round-trip - which re-sends the entire (often large) failed
    response back to the model - for what is usually a trivial formatting
    slip, and avoids that round-trip pushing the request over a model's
    tokens-per-minute limit.
    """
    out = []
    in_string = False
    escaped = False
    for ch in text:
        if in_string:
            if escaped:
                out.append(ch)
                escaped = False
                continue
            if ch == "\\":
                out.append(ch)
                escaped = True
                continue
            if ch == '"':
                in_string = False
                out.append(ch)
                continue
            if ch == "\n":
                out.append("\\n")
                continue
            if ch == "\r":
                out.append("\\r")
                continue
            if ch == "\t":
                out.append("\\t")
                continue
            out.append(ch)
        else:
            if ch == '"':
                in_string = True
            out.append(ch)
    return "".join(out)


def _chat_completion(
    messages: list[dict],
    model: str,
    stats: LLMCallStats | None = None,
    agent_role: str | None = None,
) -> str:
    """Call Groq chat completion with retry/backoff. Returns raw text content."""
    client = get_client()
    backoff = config.INITIAL_BACKOFF_SECONDS
    last_exc: Exception | None = None
    max_tokens = _safe_max_tokens(messages, agent_role=agent_role)

    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=config.TEMPERATURE,
                max_tokens=max_tokens,
            )
            if stats is not None:
                usage = response.usage
                stats.record(
                    prompt_tokens=usage.prompt_tokens if usage else 0,
                    completion_tokens=usage.completion_tokens if usage else 0,
                )
            choice = response.choices[0]
            if choice.finish_reason == "length":
                # The model's response was cut off mid-output because it
                # hit max_tokens - the JSON will be truncated/invalid, and
                # this is NOT a formatting problem a repair retry can fix.
                # Surface this clearly instead of letting it fail as a
                # confusing downstream JSON parse error.
                raise LLMOutputTruncatedError(
                    f"Response truncated at max_tokens={max_tokens} "
                    f"(model={model}). The task likely needs more output "
                    "than fits in one call at this token budget."
                )
            content = choice.message.content or ""
            if not content.strip():
                # Some providers (seen via OpenRouter with gpt-oss models)
                # occasionally return a normal-looking response with
                # finish_reason="stop" but empty content - e.g. a transient
                # upstream routing hiccup, or the model spending its whole
                # budget on hidden reasoning tokens with none left for the
                # visible answer. Downstream JSON parsing would only ever
                # produce a confusing "Expecting value: line 1 column 1"
                # error for this, so raise something explicit instead.
                raise LLMEmptyResponseError(
                    f"Model returned empty content (model={model}, "
                    f"finish_reason={choice.finish_reason})."
                )
            return content
        except (LLMOutputTruncatedError, LLMEmptyResponseError):
            raise
        except Exception as exc:  # noqa: BLE001 - deliberately broad, we classify below
            last_exc = exc
            if attempt < config.MAX_RETRIES and _is_retryable(exc):
                # Prefer Groq's own stated wait time (exact, from the
                # rate-limit window) over a blind exponential guess - a
                # small fixed buffer avoids retrying a fraction of a
                # second too early and hitting the same limit again.
                exact_wait = _retry_after_seconds(exc)
                wait_time = exact_wait + 1.0 if exact_wait is not None else backoff
                time.sleep(wait_time)
                backoff *= config.BACKOFF_MULTIPLIER
                continue
            raise

    # Should not be reached, but keeps type-checkers happy.
    assert last_exc is not None
    raise last_exc


def _extract_json(text: str) -> str:
    """Extract a JSON object from model output, tolerating markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        # Strip ``` or ```json fences
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # Fallback: find the first '{' and the last '}' to be resilient against
    # any stray prose the model may add despite instructions.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def call_structured(
    system_prompt: str,
    user_prompt: str,
    schema: Type[T],
    stats: LLMCallStats | None = None,
    model: str | None = None,
    agent_role: str | None = None,
) -> T:
    """
    Call the LLM and parse+validate its JSON response into `schema`.

    On invalid JSON / schema validation failure, retries once with the
    validation error fed back to the model asking it to fix the output.

    `model` lets each agent use a different Groq model (e.g. a stronger
    model for Architect/Developer, a smaller/faster one for
    Reviewer/Tester) - see config.py's per-agent *_MODEL settings.
    Defaults to config.LLM_MODEL if not given.

    `agent_role` selects a per-role completion token cap (see
    config.AGENT_MAX_TOKENS) - short structured artifacts (requirements,
    architecture, review, test_result) are capped low; "developer" (or
    None) is left uncapped beyond the dynamic TPM-derived budget, since
    generated code length varies a lot with task complexity.
    """
    model = model or config.LLM_MODEL
    schema_hint = json.dumps(schema.model_json_schema())
    # temperary
    print("[structured] system_prompt chars:", len(system_prompt))
    print("[structured] schema chars:", len(schema_hint))
    print("[structured] user_prompt chars:", len(user_prompt))

    full_system_prompt = (
        f"{system_prompt}\n\n"
        "You MUST respond with a single valid JSON object only - no markdown "
        "fences, no prose before or after. The JSON must conform to this "
        f"JSON Schema:\n{schema_hint}"
    )

    messages = [
        {"role": "system", "content": full_system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    last_error: Exception | None = None
    for repair_attempt in range(3):  # 1 initial try + 2 repair tries
        try:
            raw = _chat_completion(
                messages, model=model, stats=stats, agent_role=agent_role
            )
        except LLMEmptyResponseError as exc:
            # Not a formatting problem - nothing to "fix" - so just ask
            # again plainly. Seen in practice as a transient upstream
            # provider hiccup via OpenRouter, so a plain retry often
            # succeeds outright.
            last_error = exc
            print(
                f"[llm] empty response for agent_role={agent_role} "
                f"(attempt {repair_attempt + 1}/3) - retrying"
            )
            if _current_run_dir is not None:
                from src import persistence

                persistence.append_log(
                    _current_run_dir,
                    "empty_response_retry",
                    agent_role=agent_role,
                    attempt=repair_attempt + 1,
                    model=model,
                    error=str(exc),
                )
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your previous response was empty. Please respond "
                        "again with the full required JSON output."
                    ),
                }
            )
            continue
        except LLMOutputTruncatedError as exc:
            # Retrying with the exact same prompt would just be truncated
            # again - instead, ask explicitly for a more compact response
            # (this is the model's best chance to fit within the token
            # budget rather than a guaranteed repeat failure).
            last_error = exc
            print(
                f"[llm] output truncated for agent_role={agent_role} "
                f"(attempt {repair_attempt + 1}/3) - retrying with a "
                "'be more compact' follow-up message"
            )
            if _current_run_dir is not None:
                # Local import to avoid a circular import at module load
                # time (persistence doesn't import llm_client, but keeping
                # this import local makes the dependency direction explicit).
                from src import persistence

                persistence.append_log(
                    _current_run_dir,
                    "output_truncated_retry",
                    agent_role=agent_role,
                    attempt=repair_attempt + 1,
                    model=model,
                    error=str(exc),
                )
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your previous response was too long and got cut off "
                        "before finishing the JSON. Respond again with a "
                        "SIGNIFICANTLY more compact implementation: fewer "
                        "files, shorter docstrings/comments, and no "
                        "unnecessary code, while still meeting the "
                        "requirements. Output ONLY the JSON object."
                    ),
                }
            )
            continue
        json_text = _extract_json(raw)
        try:
            data = json.loads(json_text)
            return schema.model_validate(data)
        except json.JSONDecodeError:
            # Common failure mode: raw newlines/tabs left un-escaped inside
            # a string value (e.g. multi-line source code). Try a local,
            # no-LLM-call fix first - much cheaper than a full repair
            # round-trip, and avoids that round-trip's larger prompt
            # pushing the request over a model's TPM limit.
            try:
                data = json.loads(_sanitize_json_string_literals(json_text))
                return schema.model_validate(data)
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
        except ValidationError as exc:
            last_error = exc

        if last_error is not None:
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your previous response was not valid JSON matching the "
                        f"required schema. Error: {last_error}\n"
                        "Please respond again with ONLY the corrected JSON object."
                    ),
                }
            )
            continue

    raise ValueError(
        f"Failed to obtain valid structured output after retries: {last_error}"
    )


# --------------------------------------------------------------------------
# Developer-only code format
# --------------------------------------------------------------------------
# Embedding whole source files as escaped JSON string values is exactly the
# failure mode that produced the "Expecting ',' delimiter" parse errors seen
# in real runs: a model has to correctly backslash-escape every quote,
# newline, tab, etc. inside every file's content, across potentially many
# files, in a single response - one missed escape anywhere breaks the whole
# JSON object. Since the Developer is the only agent whose output actually
# contains large chunks of source code, it gets its own, code-friendly wire
# format instead: a small metadata header followed by raw (unescaped) file
# blocks delimited by simple markers. Every other agent (short structured
# prose/JSON artifacts) keeps using call_structured() above.
DEVELOPER_FORMAT_INSTRUCTIONS = """\
You MUST respond in the following plain-text format - NOT JSON. Do not wrap \
anything in markdown code fences. Write raw source code directly, with no \
escaping of quotes/newlines (this is not a JSON string).

<<<REVISION>>>
<the revision number as a plain integer>
<<<SUMMARY>>>
<one short paragraph describing what was implemented/changed>
<<<NOTES_FOR_REVIEWER>>>
<one bullet per line starting with "- ", or the single line "(none)">
<<<FILE: relative/path/to/file.py>>>
<the complete raw file content, verbatim>
<<<END FILE>>>
<<<FILE: another/file.py>>>
<the complete raw file content, verbatim>
<<<END FILE>>>

Rules:
- Include one <<<FILE: ...>>> / <<<END FILE>>> block per source file, with \
no escaping - paste the code exactly as it should appear on disk.
- Never write the literal text "<<<END FILE>>>" inside a file's own \
content.
- Emit the four header markers exactly once each, in the order shown, \
before the first <<<FILE:>>> block.
"""

_FILE_BLOCK_RE = re.compile(
    r"<<<FILE:\s*(?P<path>.+?)\s*>>>\n(?P<content>.*?)"
    # The closing "\n<<<END FILE>>>" marker and the next "<<<FILE:" marker
    # are matched with an optional leading newline (\n?) rather than a
    # required one - models sometimes omit the trailing newline after the
    # last line of a file's content, and requiring "\n" here caused the
    # literal "<<<END FILE>>>"/"<<<FILE:" text to leak into the previous
    # file's content instead of being recognised as the delimiter (seen in
    # practice: leaked "<<<END FILE>>>" text caused a SyntaxError that
    # failed every QA test). See _extract_file_blocks for a second,
    # defensive cleanup pass in case a leak still slips through.
    r"(?:\n?<<<END FILE>>>|\n?(?=<<<FILE:)|\Z)",
    re.DOTALL,
)

# Belt-and-braces cleanup: strip a leaked delimiter from the tail of a
# parsed file's content, in case some other model quirk still lets one
# through despite the more tolerant regex above.
_LEAKED_MARKER_RE = re.compile(r"\s*<<<(?:END FILE|FILE:.*?)>>>\s*\Z", re.DOTALL)


def _strip_markdown_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _split_header_and_body(text: str) -> tuple[str, str]:
    """Split a header+file-blocks response into the header portion (before
    the first <<<FILE: ...>>> marker) and the body portion (from that
    marker onwards, containing all the file blocks)."""
    first_file_idx = text.find("<<<FILE:")
    header = text[:first_file_idx] if first_file_idx != -1 else text
    body = text[first_file_idx:] if first_file_idx != -1 else ""
    return header, body


def _parse_header_fields(header: str, tags: list[str]) -> dict[str, str]:
    """Extract `<<<TAG>>>\\n<content>` sections from a header block for the
    given list of tag names, returning {tag: content}. Tags not present in
    the text are simply absent from the returned dict."""
    tag_re = re.compile(r"<<<(" + "|".join(tags) + r")>>>\n")
    parts = tag_re.split(header)
    # split() with a capturing group returns
    # [preamble, tag1, content1, tag2, content2, ...]
    fields: dict[str, str] = {}
    it = iter(parts[1:])
    for tag, content in zip(it, it):
        fields[tag] = content
    return fields


def _extract_file_blocks(body: str) -> list[dict[str, str]]:
    files = []
    for m in _FILE_BLOCK_RE.finditer(body):
        content = _LEAKED_MARKER_RE.sub("", m.group("content"))
        files.append({"path": m.group("path").strip(), "content": content})
    return files


def _parse_developer_response(text: str, schema: Type[T]) -> T:
    """Parse the Developer's header+file-blocks format (see
    DEVELOPER_FORMAT_INSTRUCTIONS) into `schema` (normally CodeArtifact).

    Raises ValueError with a description suitable for feeding back to the
    model as a repair prompt if the text doesn't match the expected shape.
    """
    text = _strip_markdown_fences(text)
    header, body = _split_header_and_body(text)
    fields = _parse_header_fields(
        header, ["REVISION", "SUMMARY", "NOTES_FOR_REVIEWER"]
    )

    if "REVISION" not in fields:
        raise ValueError(
            "Missing <<<REVISION>>> header block in Developer response."
        )
    if "SUMMARY" not in fields:
        raise ValueError(
            "Missing <<<SUMMARY>>> header block in Developer response."
        )

    try:
        revision = int(fields["REVISION"].strip())
    except ValueError as exc:
        raise ValueError(
            f"<<<REVISION>>> value must be a plain integer, got: "
            f"{fields['REVISION'].strip()!r}"
        ) from exc

    summary = fields["SUMMARY"].strip()

    notes_raw = fields.get("NOTES_FOR_REVIEWER", "").strip()
    notes = []
    if notes_raw and notes_raw != "(none)":
        for line in notes_raw.splitlines():
            line = line.strip()
            if not line:
                continue
            notes.append(line[2:].strip() if line.startswith("- ") else line)

    files = _extract_file_blocks(body)
    if not files:
        raise ValueError(
            "No <<<FILE: ...>>> blocks found in Developer response."
        )

    data = {
        "revision": revision,
        "summary": summary,
        "source_files": files,
        "notes_for_reviewer": notes,
    }
    return schema.model_validate(data)


def _call_file_block_format(
    system_prompt: str,
    user_prompt: str,
    format_instructions: str,
    parse_fn,
    schema: Type[T],
    stats: LLMCallStats | None = None,
    model: str | None = None,
    agent_role: str | None = None,
) -> T:
    """
    Shared engine behind call_developer_code() and call_tester_code():
    asks for a header+raw-file-blocks response (per `format_instructions`)
    instead of JSON, so multi-line source code never needs JSON
    string-escaping, then parses it with `parse_fn(raw, schema)`. Retries
    with a repair message if parsing fails or the response is empty/
    truncated, same policy as call_structured().
    """
    model = model or config.LLM_MODEL
    print("[structured] system_prompt chars:", len(system_prompt))
    print("[structured] user_prompt chars:", len(user_prompt))

    full_system_prompt = f"{system_prompt}\n\n{format_instructions}"

    messages = [
        {"role": "system", "content": full_system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    last_error: Exception | None = None
    for repair_attempt in range(3):  # 1 initial try + 2 repair tries
        try:
            raw = _chat_completion(
                messages, model=model, stats=stats, agent_role=agent_role
            )
        except LLMEmptyResponseError as exc:
            last_error = exc
            print(
                f"[llm] empty response for agent_role={agent_role} "
                f"(attempt {repair_attempt + 1}/3) - retrying"
            )
            if _current_run_dir is not None:
                from src import persistence

                persistence.append_log(
                    _current_run_dir,
                    "empty_response_retry",
                    agent_role=agent_role,
                    attempt=repair_attempt + 1,
                    model=model,
                    error=str(exc),
                )
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your previous response was empty. Please respond "
                        "again with the full required output in the exact "
                        "header+file-block format."
                    ),
                }
            )
            continue
        except LLMOutputTruncatedError as exc:
            last_error = exc
            print(
                f"[llm] output truncated for agent_role={agent_role} "
                f"(attempt {repair_attempt + 1}/3) - retrying with a "
                "'be more compact' follow-up message"
            )
            if _current_run_dir is not None:
                from src import persistence

                persistence.append_log(
                    _current_run_dir,
                    "output_truncated_retry",
                    agent_role=agent_role,
                    attempt=repair_attempt + 1,
                    model=model,
                    error=str(exc),
                )
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your previous response was too long and got cut off "
                        "before finishing. Respond again with a "
                        "SIGNIFICANTLY more compact implementation: fewer "
                        "files, shorter docstrings/comments, and no "
                        "unnecessary code, while still meeting the "
                        "requirements. Use the exact same header+file-block "
                        "format."
                    ),
                }
            )
            continue

        try:
            return parse_fn(raw, schema)
        except (ValueError, ValidationError) as exc:
            last_error = exc
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your previous response did not match the required "
                        f"header+file-block format. Error: {last_error}\n"
                        "Please respond again with ONLY the corrected "
                        "output in that exact format."
                    ),
                }
            )
            continue

    raise ValueError(
        f"Failed to obtain valid output after retries: {last_error}"
    )


def call_developer_code(
    system_prompt: str,
    user_prompt: str,
    schema: Type[T],
    stats: LLMCallStats | None = None,
    model: str | None = None,
    agent_role: str | None = None,
) -> T:
    """
    Like call_structured(), but for the Developer agent only: asks for the
    header+raw-file-blocks format (DEVELOPER_FORMAT_INSTRUCTIONS) instead
    of JSON, so multi-line source code never needs JSON string-escaping.
    """
    return _call_file_block_format(
        system_prompt,
        user_prompt,
        DEVELOPER_FORMAT_INSTRUCTIONS,
        _parse_developer_response,
        schema,
        stats=stats,
        model=model,
        agent_role=agent_role,
    )


# --------------------------------------------------------------------------
# Tester/QA-only test file format
# --------------------------------------------------------------------------
# Same rationale as DEVELOPER_FORMAT_INSTRUCTIONS above: QA's qa_test_files
# field embeds multi-line source code (test files) - the exact failure mode
# that produces broken JSON (or, as seen in practice, doubly-escaped "\n"
# sequences written literally to disk instead of real newlines). QA gets
# the same header+raw-file-blocks wire format as the Developer.
TESTER_FORMAT_INSTRUCTIONS = """\
You MUST respond in the following plain-text format - NOT JSON. Do not wrap \
anything in markdown code fences. Write raw source code directly, with no \
escaping of quotes/newlines (this is not a JSON string).

<<<SUMMARY>>>
<one short paragraph summarizing the test run/coverage>
<<<TEST_CASES>>>
<one test case per line, formatted exactly as:>
<id> | <description> | <comma-separated acceptance criteria ids, or "none">
<<<FILE: relative/path/to/test_file.py>>>
<the complete raw test file content, verbatim>
<<<END FILE>>>
<<<FILE: another/test_file.py>>>
<the complete raw test file content, verbatim>
<<<END FILE>>>

Rules:
- Include one <<<FILE: ...>>> / <<<END FILE>>> block per test file, with \
no escaping - paste the code exactly as it should appear on disk.
- Never write the literal text "<<<END FILE>>>" inside a file's own \
content.
- Emit the <<<SUMMARY>>> and <<<TEST_CASES>>> header markers exactly once \
each, in the order shown, before the first <<<FILE:>>> block.
- Do not include the source files being tested - only your own \
independent test files.
"""


def _parse_tester_response(text: str, schema: Type[T]) -> T:
    """Parse the Tester's header+file-blocks format (see
    TESTER_FORMAT_INSTRUCTIONS) into `schema` (normally QATestPartial).

    Raises ValueError with a description suitable for feeding back to the
    model as a repair prompt if the text doesn't match the expected shape.
    """
    text = _strip_markdown_fences(text)
    header, body = _split_header_and_body(text)
    fields = _parse_header_fields(header, ["SUMMARY", "TEST_CASES"])

    if "SUMMARY" not in fields:
        raise ValueError("Missing <<<SUMMARY>>> header block in QA response.")
    if "TEST_CASES" not in fields:
        raise ValueError(
            "Missing <<<TEST_CASES>>> header block in QA response."
        )

    summary = fields["SUMMARY"].strip()

    test_cases = []
    for line in fields["TEST_CASES"].strip().splitlines():
        line = line.strip()
        if not line:
            continue
        pieces = [p.strip() for p in line.split("|")]
        if len(pieces) < 2:
            raise ValueError(
                "Each <<<TEST_CASES>>> line must be "
                "'<id> | <description> | <acceptance criteria ids>', got: "
                f"{line!r}"
            )
        case_id, description = pieces[0], pieces[1]
        ac_ids_raw = pieces[2] if len(pieces) > 2 else ""
        ac_ids = (
            []
            if not ac_ids_raw or ac_ids_raw.lower() == "none"
            else [a.strip() for a in ac_ids_raw.split(",") if a.strip()]
        )
        test_cases.append(
            {
                "id": case_id,
                "description": description,
                "related_acceptance_criteria": ac_ids,
            }
        )

    if not test_cases:
        raise ValueError(
            "No test case lines found under <<<TEST_CASES>>> in QA response."
        )

    files = _extract_file_blocks(body)
    if not files:
        raise ValueError("No <<<FILE: ...>>> blocks found in QA response.")

    data = {
        "qa_test_cases": test_cases,
        "qa_test_files": files,
        "summary": summary,
    }
    return schema.model_validate(data)


def call_tester_code(
    system_prompt: str,
    user_prompt: str,
    schema: Type[T],
    stats: LLMCallStats | None = None,
    model: str | None = None,
    agent_role: str | None = None,
) -> T:
    """
    Like call_structured(), but for the Tester/QA agent only: asks for the
    header+raw-file-blocks format (TESTER_FORMAT_INSTRUCTIONS) instead of
    JSON, so multi-line test file source code never needs JSON
    string-escaping (schema is normally QATestPartial).
    """
    return _call_file_block_format(
        system_prompt,
        user_prompt,
        TESTER_FORMAT_INSTRUCTIONS,
        _parse_tester_response,
        schema,
        stats=stats,
        model=model,
        agent_role=agent_role,
    )
