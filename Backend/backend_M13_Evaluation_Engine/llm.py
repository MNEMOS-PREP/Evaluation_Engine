"""The one place this module talks to a model — spec §11, master plan §47.

Three rules from the master plan are enforced here rather than remembered:

**Routing rule 1 — anything a student sees as a score is mid tier or above.**
`model_for()` refuses to return a cheap-tier model for a scoring job. A later
cost squeeze can drop the ensemble *count* (§6.4) but cannot drop the *tier*,
because the function will not produce one.

**No sampling parameters.** `claude-sonnet-5` and `claude-opus-5` reject
`temperature`, `top_p` and `top_k` with a 400 — they were removed. This is
also why the ensemble needs an explicit decorrelator (§6.4): there is no knob
to vary, so two identical calls to one model are one sample twice.

**The cached prefix must clear the model's minimum or the cost model is
fiction.** §11's per-call figure assumes an ~80% cached rubric prefix. Below
`claude-sonnet-5`'s 1024-token minimum the cache silently never fills — no
error, `cache_creation_input_tokens: 0` — and the bill roughly triples with
nothing on screen to say why. `should_cache_system()` is the guard, and
`cache_read_ratio` is the telemetry that catches it in production.

No key is a degradation, not a failure: `get_llm()` returns `NullLLM`, the
module still starts, `/v1/deps` says so, and the whole test suite runs offline.
"""

from __future__ import annotations

import json as _json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from . import keys as keys_module

log = logging.getLogger(__name__)

#: urllib defaults to `Python-urllib/3.x`, which Cloudflare rejects with error
#: 1010 — an HTTP 403 that looks exactly like a bad API key and is not one.
USER_AGENT = "M13-EvaluationEngine/0.1 (AI-Interviewer)"
REQUEST_TIMEOUT = float(os.getenv("M13_LLM_TIMEOUT", "60"))

#: Attempts per call on an OpenAI-compatible provider.
ATTEMPTS = (0, 1, 2)
LAST_ATTEMPT = ATTEMPTS[-1]
#: Fallback wait when a provider rate-limits without saying for how long.
RATE_LIMIT_BACKOFF = float(os.getenv("M13_RATE_LIMIT_BACKOFF", "20"))


def _retry_after(exc: Any) -> float | None:
    """Honour the provider's own advice about when to come back, if it gives any.

    Capped, because a provider that says "try again in an hour" is telling you
    the run is over, not that the process should sleep through lunch.
    """
    headers = getattr(exc, "headers", None)
    if not headers:
        return None
    for header in ("retry-after", "x-ratelimit-reset-tokens", "x-ratelimit-reset-requests"):
        raw = headers.get(header)
        if not raw:
            continue
        try:
            return min(float(str(raw).rstrip("s")), 60.0)
        except ValueError:
            continue
    return None


class ScoreGrade(StrEnum):
    """What a score produced by this provider is fit for.

    The single most important thing in this module that is not a test. Running
    on a free tier is the right call while the rubric anchors are still being
    argued about — you want a hundred cheap opinions before you buy one
    expensive one. What must never happen is a free-tier score quietly
    becoming a number a student is shown, or an item in the corpus the
    calibration is fitted on.

    Master plan §47.1 routing rule 1 says a student-visible score runs at mid
    tier or above. This enum is that rule made checkable rather than
    remembered: `dev` scores are real evaluations with real verified evidence,
    and they are excluded from the display gate and from the calibration
    corpus by their grade rather than by anyone's discipline.
    """

    #: Anthropic mid tier or above. Eligible for display and for calibration.
    calibration = "calibration"
    #: Free tier / open models. Real output, real evidence, exploratory only.
    dev = "dev"

# ── Jobs ─────────────────────────────────────────────────────────────────

JOB_EVALUATE = "evaluate"
JOB_ADJUDICATE = "adjudicate"

#: Jobs whose output a student sees as a score. Master plan §47.1 rule 1.
SCORING_JOBS = frozenset({JOB_EVALUATE, JOB_ADJUDICATE})

# ── Tiers (master plan §47.1) ────────────────────────────────────────────

FRONTIER = "claude-opus-5"
MID = "claude-sonnet-5"
CHEAP = "claude-haiku-4-5"

_DEFAULT_MODELS = {
    JOB_EVALUATE: MID,
    JOB_ADJUDICATE: FRONTIER,
}

_ENV_OVERRIDES = {
    JOB_EVALUATE: "M13_MODEL_EVALUATE",
    JOB_ADJUDICATE: "M13_MODEL_ADJUDICATE",
}


@dataclass(frozen=True)
class ModelProfile:
    """List price per 1M tokens, and the caching minimum that gates §11."""

    model: str
    usd_in: float
    usd_out: float
    #: Minimum cacheable prefix. NOT monotonic across generations — 512 on
    #: Opus 5, 1024 on Sonnet 5, 4096 on Haiku 4.5 — so it has to be per model.
    cache_min_tokens: int


_PROFILES = {
    FRONTIER: ModelProfile(FRONTIER, 5.0, 25.0, 512),
    MID: ModelProfile(MID, 3.0, 15.0, 1024),
    CHEAP: ModelProfile(CHEAP, 1.0, 5.0, 4096),
}


def profile_for(model: str) -> ModelProfile:
    return _PROFILES.get(model, ModelProfile(model, 3.0, 15.0, 1024))


def model_for(job: str) -> str:
    """The model for a job, env-overridable — but never below mid tier for a score."""
    chosen = os.getenv(_ENV_OVERRIDES.get(job, ""), "") or _DEFAULT_MODELS.get(job, MID)
    if job in SCORING_JOBS and chosen == CHEAP:
        raise ValueError(
            f"job '{job}' produces a score a student sees; master plan §47.1 routing "
            f"rule 1 forbids the cheap tier. Drop the ensemble COUNT to save money, "
            f"never the tier."
        )
    return chosen


def usd_to_inr() -> float:
    """plan_in_depth/README.md fixes the convention at ≈88."""
    try:
        return float(os.getenv("USD_INR", "88"))
    except ValueError:
        return 88.0


def cost_inr(
    model: str, tokens_in: int, tokens_out: int, cached_in: int = 0, cache_write: int = 0
) -> float:
    p = profile_for(model)
    usd = (
        tokens_in * p.usd_in
        + tokens_out * p.usd_out
        + cached_in * p.usd_in * 0.1  # cache reads ≈ 0.1× input
        + cache_write * p.usd_in * 1.25  # 5-minute TTL write premium
    ) / 1_000_000
    return usd * usd_to_inr()


def rough_tokens(text: str) -> int:
    """A cheap estimate, only ever used to decide whether caching is worth trying."""
    return max(1, len(text) // 4)


def should_cache_system(system: str, model: str) -> bool:
    """Whether the prefix clears this model's minimum. Below it, caching is a no-op."""
    return rough_tokens(system) >= profile_for(model).cache_min_tokens


# ── Results ──────────────────────────────────────────────────────────────


@dataclass
class LLMResult:
    """One call's outcome and its bill.

    `ok` is False for every non-success — no key, refusal, transport error,
    malformed JSON. Callers branch on `ok`, never on the presence of `data`,
    because "the model said nothing useful" and "the model was never asked"
    must be handled identically.
    """

    ok: bool
    data: dict[str, Any] | None = None
    model: str = ""
    job: str = ""
    reason: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cached_in: int = 0
    cache_write: int = 0
    latency_ms: int = 0

    @property
    def cost_inr(self) -> float:
        return cost_inr(
            self.model, self.tokens_in, self.tokens_out, self.cached_in, self.cache_write
        )


class LLM(Protocol):
    name: str

    def structured(
        self, *, job: str, system: str, user: str, schema: dict, max_tokens: int = 8000
    ) -> LLMResult: ...


@dataclass
class NullLLM:
    """No key, no network. The module runs; the scoring feature says why it can't."""

    name: str = "null"
    grade: ScoreGrade = ScoreGrade.dev
    _warned: bool = field(default=False, repr=False)

    def structured(
        self, *, job: str, system: str, user: str, schema: dict, max_tokens: int = 8000
    ) -> LLMResult:
        if not self._warned:
            log.info("no ANTHROPIC_API_KEY — evaluation is unavailable; everything else runs")
            self._warned = True
        return LLMResult(ok=False, job=job, reason="no_api_key")


@dataclass
class AnthropicLLM:
    """The real one. Imported lazily so a checkout without the SDK still runs."""

    api_key: str
    name: str = "anthropic"
    #: Master plan §47.1 roster — the only grade eligible for display and for
    #: the calibration corpus.
    grade: ScoreGrade = ScoreGrade.calibration
    _client: Any = field(default=None, repr=False)

    def _get_client(self) -> Any:
        if self._client is None:
            import anthropic  # noqa: PLC0415 — lazy on purpose

            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def structured(
        self, *, job: str, system: str, user: str, schema: dict, max_tokens: int = 8000
    ) -> LLMResult:
        model = model_for(job)
        started = time.monotonic()
        system_block: Any = system
        if should_cache_system(system, model):
            system_block = [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ]

        try:
            response = self._get_client().messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_block,
                messages=[{"role": "user", "content": user}],
                # NO temperature / top_p / top_k — removed on Sonnet 5 and
                # Opus 5; sending one is a 400. Decorrelation is §6.4's job.
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
        except Exception as exc:  # transport, auth, validation
            log.warning("llm call failed job=%s model=%s: %s", job, model, exc)
            return LLMResult(ok=False, job=job, model=model, reason=f"error:{type(exc).__name__}")

        latency_ms = int((time.monotonic() - started) * 1000)

        # stop_reason BEFORE content: a refusal is a 200 with no usable body.
        if getattr(response, "stop_reason", None) == "refusal":
            return LLMResult(
                ok=False, job=job, model=model, reason="refusal", latency_ms=latency_ms
            )

        import json  # noqa: PLC0415

        text = next((b.text for b in response.content if getattr(b, "type", "") == "text"), "")
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            return LLMResult(
                ok=False, job=job, model=model, reason="unparseable", latency_ms=latency_ms
            )

        usage = getattr(response, "usage", None)
        return LLMResult(
            ok=True,
            data=data,
            job=job,
            model=model,
            tokens_in=getattr(usage, "input_tokens", 0) or 0,
            tokens_out=getattr(usage, "output_tokens", 0) or 0,
            cached_in=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_write=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            latency_ms=latency_ms,
        )


def _tune(model: str) -> dict[str, Any]:
    """Per-model body fields that a provider needs and the dialect does not cover.

    **`reasoning_effort` on the gpt-oss family, and it is not an optimisation.**
    These are reasoning models: the reasoning tokens come out of the same
    `max_tokens` budget as the answer. On a free tier where the whole request
    must fit inside 8,000 tokens per minute, the default effort spends the
    entire budget thinking and returns an EMPTY completion — which the provider
    then reports as `json_validate_failed` with `failed_generation: ""`, an
    error message that points at the schema when the schema was never the
    problem. Cost me an hour; hence the paragraph.

    At `low` the same call answers in ~3s using ~1,100 output tokens, and the
    scores are good: the verbose-but-empty adversarial case comes back 0/0/1,
    which is exactly its band.
    """
    if "gpt-oss" in model:
        return {"reasoning_effort": os.getenv("M13_REASONING_EFFORT", "low")}
    return {}


@dataclass
class OpenAICompatProvider:
    """An OpenAI-compatible chat endpoint plus its pool of keys.

    Groq and NVIDIA NIM both speak the OpenAI chat-completions dialect, so one
    client covers both and swapping either is a config change.
    """

    name: str
    base_url: str
    model: str
    ring: keys_module.KeyRing
    grade: ScoreGrade = ScoreGrade.dev
    #: Extra body fields this provider/model needs. See `_tune()`.
    extra_body: dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.ring) and bool(self.model)

    def tuned_body(self) -> dict[str, Any]:
        return dict(self.extra_body)

    @classmethod
    def groq(cls) -> OpenAICompatProvider:
        model = os.getenv("M13_GROQ_MODEL", os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"))
        return cls(
            name="groq",
            base_url="https://api.groq.com/openai/v1",
            # The bigger free model by default: this job is a judgement about a
            # student's answer, and it is the one place on the free tier where
            # capability is genuinely load-bearing.
            model=model,
            ring=keys_module.KeyRing.from_env("GROQ_API_KEYS", "GROQ_API_KEY"),
            extra_body=_tune(model),
        )

    @classmethod
    def nvidia(cls) -> OpenAICompatProvider:
        return cls(
            name="nvidia",
            base_url="https://integrate.api.nvidia.com/v1",
            model=os.getenv("NVIDIA_MODEL", "meta/llama-3.3-70b-instruct"),
            ring=keys_module.KeyRing.from_env("NVIDIA_API_KEYS", "NVIDIA_API_KEY"),
        )


@dataclass
class OpenAICompatLLM:
    """Groq / NVIDIA NIM, over the OpenAI chat-completions dialect.

    **The schema is a hint here, not a wall.** The Anthropic path constrains
    `raw_score` to an enum and `artifact_id` to this turn's artifacts, so an
    out-of-range score or an invented artifact cannot be returned. These
    providers accept `response_format` with a JSON schema but enforcement
    varies by model, so both become strong suggestions.

    Which is exactly why span verification re-checks every quote against the
    artifact and why `_parse_scores` re-validates every score rather than
    trusting the schema. Those were never the belt to the schema's braces —
    they are the load-bearing part, and this configuration is what proves it.

    Keys round-robin per request: the rate limit is per key, so a pool is a
    pool of quota.
    """

    provider: OpenAICompatProvider
    name: str = ""

    def __post_init__(self) -> None:
        self.name = self.provider.name

    @property
    def grade(self) -> ScoreGrade:
        return self.provider.grade

    def structured(
        self, *, job: str, system: str, user: str, schema: dict, max_tokens: int = 8000
    ) -> LLMResult:
        model = os.getenv(_ENV_OVERRIDES.get(job, ""), "").strip() or self.provider.model
        started = time.monotonic()

        body: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": job, "schema": schema, "strict": True},
            },
            **self.provider.tuned_body(),
        }

        result = LLMResult(ok=False, job=job, model=f"{self.provider.name}/{model}")

        # Three attempts, each on a different key, and each failure handled as
        # the thing it actually is rather than as a generic error:
        #   400/422  "this model does not enforce json_schema" → drop to
        #            json_object and put the schema in the prompt instead.
        #   413/429  a rate limit → wait for the window (see below).
        for attempt in ATTEMPTS:
            if attempt == 1:
                body["response_format"] = {"type": "json_object"}
                body["messages"][0]["content"] = (
                    system
                    + "\n\nReturn ONLY a JSON object matching this schema:\n"
                    + _json.dumps(schema)
                )

            try:
                api_key = self.provider.ring.next()
            except RuntimeError:
                result.reason = "no keys configured"
                return result

            request = urllib.request.Request(
                f"{self.provider.base_url}/chat/completions",
                data=_json.dumps(body).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": USER_AGENT,
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                    payload = _json.loads(response.read())
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:200]
                result.reason = f"http_{exc.code} ({keys_module.redact(api_key)}): {detail}"
                if attempt == LAST_ATTEMPT or exc.code not in (400, 413, 422, 429):
                    result.latency_ms = int((time.monotonic() - started) * 1000)
                    return result
                if exc.code in (413, 429):
                    # A RATE LIMIT, not a bad request. On a free tier the
                    # per-minute token budget counts `max_tokens` as already
                    # spent, so the fix is to wait for the window — retrying
                    # instantly on another key does not help, because the
                    # quota belongs to the org rather than to the key.
                    wait = _retry_after(exc) or RATE_LIMIT_BACKOFF
                    log.info("rate limited on %s; waiting %.1fs", self.provider.name, wait)
                    time.sleep(wait)
            except Exception as exc:  # noqa: BLE001 — an outage must not become ours
                result.reason = f"{type(exc).__name__}: {exc}"
                result.latency_ms = int((time.monotonic() - started) * 1000)
                return result
        else:  # pragma: no cover — the loop always breaks or returns
            return result

        result.latency_ms = int((time.monotonic() - started) * 1000)
        usage = payload.get("usage") or {}
        result.tokens_in = usage.get("prompt_tokens", 0) or 0
        result.tokens_out = usage.get("completion_tokens", 0) or 0

        choices = payload.get("choices") or []
        if not choices:
            result.reason = "no choices in response"
            return result

        message = choices[0].get("message") or {}
        text = (message.get("content") or "").strip()
        if not text:
            result.reason = f"empty content (finish_reason={choices[0].get('finish_reason')})"
            return result

        # Some models wrap JSON in a ```json fence despite response_format.
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        try:
            parsed = _json.loads(text)
        except _json.JSONDecodeError as exc:
            result.reason = f"unparseable JSON: {exc}"
            return result

        if not isinstance(parsed, dict):
            result.reason = "response was not a JSON object"
            return result

        result.ok = True
        result.data = parsed
        return result


@dataclass
class PooledLLM:
    """Several OpenAI-compatible providers, tried in order.

    **The rate limit is the reason this exists.** Groq's free tier allows 8,000
    tokens per minute and counts `max_tokens` as already spent, so one
    evaluation costs roughly a third of a minute's budget. A pool of *keys*
    does not help — that quota belongs to the organisation, not the key — but a
    pool of *providers* does, because each has its own.

    So on a rate limit we move to the next provider rather than sleeping, and
    only sleep when every provider is limited. On any other failure we fail
    over too: a provider can be unreachable from one network and fine from
    another, and a run should not end because the preferred endpoint was
    blocked from this machine.

    The reason from the first attempt is kept. A silent failover is how you
    end up not noticing a provider has been dead for a week.
    """

    providers: list[OpenAICompatProvider]
    name: str = "pooled"
    grade: ScoreGrade = ScoreGrade.dev
    _next: int = field(default=0, repr=False)

    def __post_init__(self) -> None:
        self.name = "+".join(p.name for p in self.providers) or "pooled"

    def structured(
        self, *, job: str, system: str, user: str, schema: dict, max_tokens: int = 8000
    ) -> LLMResult:
        first: LLMResult | None = None
        count = len(self.providers)
        for offset in range(count):
            provider = self.providers[(self._next + offset) % count]
            result = OpenAICompatLLM(provider=provider).structured(
                job=job, system=system, user=user, schema=schema, max_tokens=max_tokens
            )
            if result.ok:
                # Start the next call on the following provider, so a steady
                # stream of evaluations spreads across the pool instead of
                # hammering one until it limits.
                self._next = (self._next + offset + 1) % count
                if first is not None:
                    result.reason = f"failover from {first.model}: {first.reason[:80]}"
                return result
            first = first or result
            if offset < count - 1:
                log.warning("llm failover %s -> next: %s", provider.name, result.reason[:120])
        return first or LLMResult(ok=False, job=job, reason="no providers configured")


def grade_of(llm: LLM) -> ScoreGrade:
    """What the scores from this client are fit for. Defaults to `dev`.

    Defaulting to the *lower* grade is the point: a provider nobody has
    classified is not one whose scores should reach a student.
    """
    return getattr(llm, "grade", ScoreGrade.dev)


_llm: LLM | None = None


def get_llm(*, refresh: bool = False) -> LLM:
    """The module's evaluator client, resolved from whatever keys are configured.

    Order is quality first, then availability:

        Anthropic   the master plan's roster, and strict JSON-schema support,
                    which is what makes an out-of-range score and an invented
                    artifact id structurally impossible. Calibration grade.
        Groq        free tier, fast, a strong open model. Dev grade: real
                    evaluations with real verified evidence, but never a
                    number a student sees and never in the calibration corpus.
        NVIDIA NIM  same deal, different endpoint.
        nothing     NullLLM. Scoring is off, the module still runs, and
                    /v1/deps says which feature is missing and why.
    """
    global _llm
    if _llm is not None and not refresh:
        return _llm

    keys_module.load_keys()

    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if anthropic_key:
        _llm = AnthropicLLM(api_key=anthropic_key)
        return _llm

    configured = [p for p in (OpenAICompatProvider.groq(), OpenAICompatProvider.nvidia()) if p]
    if configured:
        log.info(
            "evaluating on %s — DEV GRADE: real evidence, but these scores are not "
            "student-facing and do not enter the calibration corpus",
            ", ".join(f"{p.name}/{p.model}" for p in configured),
        )
        _llm = (
            PooledLLM(providers=configured)
            if len(configured) > 1
            else OpenAICompatLLM(provider=configured[0])
        )
        return _llm

    _llm = NullLLM()
    return _llm


def set_llm(llm: LLM | None) -> None:
    """Injection point for tests. No test in this repo opens a socket."""
    global _llm
    _llm = llm


def is_available() -> bool:
    return not isinstance(get_llm(), NullLLM)


def describe() -> dict[str, str]:
    """What /v1/deps reports: who is scoring, and what the scores are fit for."""
    llm = get_llm()
    return {
        "provider": llm.name,
        "grade": str(grade_of(llm)),
        "student_facing": "false",  # nothing displays a number until §6.7's gate opens
    }


__all__ = [
    "CHEAP",
    "FRONTIER",
    "JOB_ADJUDICATE",
    "JOB_EVALUATE",
    "MID",
    "AnthropicLLM",
    "LLM",
    "LLMResult",
    "NullLLM",
    "OpenAICompatLLM",
    "OpenAICompatProvider",
    "ScoreGrade",
    "cost_inr",
    "describe",
    "grade_of",
    "get_llm",
    "is_available",
    "model_for",
    "profile_for",
    "set_llm",
    "should_cache_system",
]
