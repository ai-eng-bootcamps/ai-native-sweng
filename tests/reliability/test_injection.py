"""The raise-channel injection wrapper (Lesson 7.6).

The wrapper counts its OWN calls and raises BEFORE consulting the inner adapter,
so one declarative spec produces the identical failure over a scripted adapter
(recording) and over a replay adapter (replaying) without desynchronizing the
inner position. These fail against the scaffolding stubs and pass once Module 7
is implemented.
"""

import pytest

from anse_harness.models import ModelResponse, ScriptedAdapter, ScriptStep
from anse_harness.models.errors import ModelTimeoutError, ProviderError
from anse_harness.models.types import ModelRequest, Usage
from anse_harness.reliability import FailureInjectionAdapter, InjectionSpec

pytestmark = pytest.mark.student_impl


def _script(*texts: str) -> ScriptedAdapter:
    return ScriptedAdapter(
        [ScriptStep(response=ModelResponse(text=text, usage=Usage(10, 5))) for text in texts]
    )


def _request() -> ModelRequest:
    return ModelRequest(messages=[])


def test_wrapper_is_transparent_without_a_spec() -> None:
    adapter = FailureInjectionAdapter(_script("one", "two"), None)
    assert adapter.complete(_request()).text == "one"
    assert adapter.complete(_request()).text == "two"
    assert adapter.calls == 2


def test_wrapper_raises_at_the_configured_call_without_consuming_the_inner_step() -> None:
    inner = _script("one", "two")
    adapter = FailureInjectionAdapter(inner, InjectionSpec(at_call=2, failure="model_timeout"))
    assert adapter.complete(_request()).text == "one"
    with pytest.raises(ModelTimeoutError):
        adapter.complete(_request())
    # The injected raise counted as the wrapper's call 2 but consumed NOTHING
    # from the inner script: the next call still gets step two.
    assert adapter.complete(_request()).text == "two"
    assert adapter.calls == 3


def test_injected_error_kind_controls_the_raised_type() -> None:
    permanent = FailureInjectionAdapter(
        _script("one"), InjectionSpec(at_call=1, failure="provider_error_permanent")
    )
    with pytest.raises(ProviderError) as info:
        permanent.complete(_request())
    assert info.value.retryable is False
    assert info.value.provider == "injected"
    retryable = FailureInjectionAdapter(
        _script("one"), InjectionSpec(at_call=1, failure="provider_error_retryable")
    )
    with pytest.raises(ProviderError) as info:
        retryable.complete(_request())
    assert info.value.retryable is True


def test_first_call_injection_never_touches_the_inner_adapter() -> None:
    inner = _script("one")
    adapter = FailureInjectionAdapter(inner, InjectionSpec(at_call=1, failure="model_timeout"))
    with pytest.raises(ModelTimeoutError):
        adapter.complete(_request())
    # The whole script is still unconsumed.
    assert adapter.complete(_request()).text == "one"
