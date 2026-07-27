"""Anthropic thinking models reject a pinned temperature; older ones do not.

ESTATE FIX 2026-07-26. The newest Anthropic models run with extended thinking enabled
and reject any temperature other than 1. Routed through an OpenAI-compatible proxy the
rejection arrives as an opaque ``400 Bad request to upstream provider``, which contains
neither the word "temperature" nor an "unsupported parameter" marker, so
``_is_unsupported_parameter_error`` cannot classify it and the shipped
retry-without-temperature path never fires. The auxiliary and summary callers therefore
have to omit temperature PROACTIVELY for exactly those models.

Measured against the live provider 2026-07-26 with temperature=0.7:

    REJECTS (400): claude-sonnet-5, claude-opus-4-7, claude-opus-4-8, claude-fable-5
    ACCEPTS (200): claude-sonnet-4-6, claude-sonnet-4-5, claude-opus-4-6,
                   claude-opus-4-5, claude-opus-4-1, claude-haiku-4-5

The accepting half matters as much as the rejecting half: upstream ships
``test_non_kimi_models_preserve_temperature[anthropic/claude-sonnet-4-6]``, so a
family-wide rule would break a correct contract. These tests pin both directions.
"""

from __future__ import annotations

import pytest

from agent.auxiliary_client import (
    OMIT_TEMPERATURE,
    _fixed_temperature_for_model,
    _is_anthropic_thinking_model,
)


@pytest.mark.parametrize(
    "model",
    [
        "anthropic/claude-sonnet-5-subscription",
        "anthropic/claude-opus-4-7-subscription",
        "anthropic/claude-opus-4-8-subscription",
        "anthropic/claude-fable-5-subscription",
        "claude-sonnet-5",
        "claude-opus-4-8",
        # dated variants must still match
        "anthropic/claude-opus-4-8-20261115",
    ],
)
def test_thinking_models_omit_temperature(model):
    assert _is_anthropic_thinking_model(model) is True
    assert _fixed_temperature_for_model(model) is OMIT_TEMPERATURE


@pytest.mark.parametrize(
    "model",
    [
        # Measured as accepting temperature. Upstream asserts these keep it.
        "anthropic/claude-sonnet-4-6-subscription",
        "anthropic/claude-sonnet-4-5-subscription",
        "anthropic/claude-opus-4-6-subscription",
        "anthropic/claude-opus-4-5-subscription",
        "anthropic/claude-opus-4-1-subscription",
        "anthropic/claude-haiku-4-5-subscription",
        "claude-sonnet-4-6",
    ],
)
def test_older_anthropic_models_keep_temperature(model):
    assert _is_anthropic_thinking_model(model) is False
    assert _fixed_temperature_for_model(model) is not OMIT_TEMPERATURE


@pytest.mark.parametrize(
    "model",
    [
        "xai/grok-4.5-subscription",
        "openai/gpt-5.6-sol-subscription",
        "gemini/gemini-3.1-pro-preview-subscription",
        "gemma4:26b",
        # Lookalikes must not match on a substring.
        "some-vendor/claudia-7b",
        "claude-sonnet-50-experimental",
    ],
)
def test_non_anthropic_and_lookalikes_unaffected(model):
    assert _is_anthropic_thinking_model(model) is False


def test_existing_contracts_unchanged():
    """The new rule must not disturb the Kimi or Arcee per-model contracts."""
    assert _fixed_temperature_for_model("moonshot/kimi-k2") is OMIT_TEMPERATURE
    assert _fixed_temperature_for_model("arcee-ai/trinity-large-thinking") == 0.5


def test_none_and_empty_model_are_safe():
    assert _is_anthropic_thinking_model(None) is False
    assert _is_anthropic_thinking_model("") is False
    assert _fixed_temperature_for_model(None) is None
