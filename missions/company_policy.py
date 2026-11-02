"""Company work uses the registered OpenAI API, including nested work.

The business workspace emits prompts beginning with EMPRESA:. Context variables
keep the policy isolated between concurrent company and personal missions.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Iterator

_company_work: ContextVar[bool] = ContextVar("company_openai_api", default=False)


def is_company_prompt(prompt: str) -> bool:
    return prompt.lstrip().startswith("EMPRESA:")


def company_api_required() -> bool:
    return _company_work.get()


@contextmanager
def company_scope(prompt: str) -> Iterator[None]:
    token = _company_work.set(company_api_required() or is_company_prompt(prompt))
    try:
        yield
    finally:
        _company_work.reset(token)


def require_company_provider(provider: str) -> None:
    if company_api_required() and provider != "openai":
        raise RuntimeError("Company work requires the registered OpenAI API; provider switching is disabled.")
