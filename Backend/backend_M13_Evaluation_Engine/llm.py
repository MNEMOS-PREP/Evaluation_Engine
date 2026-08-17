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

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

log = logging.getLogger(__name__)

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


_llm: LLM | None = None


def get_llm(*, refresh: bool = False) -> LLM:
    global _llm
    if _llm is not None and not refresh:
        return _llm
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    _llm = AnthropicLLM(api_key=key) if key else NullLLM()
    return _llm


def set_llm(llm: LLM | None) -> None:
    """Injection point for tests. No test in this repo opens a socket."""
    global _llm
    _llm = llm


def is_available() -> bool:
    return not isinstance(get_llm(), NullLLM)


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
    "cost_inr",
    "get_llm",
    "is_available",
    "model_for",
    "profile_for",
    "set_llm",
    "should_cache_system",
]
