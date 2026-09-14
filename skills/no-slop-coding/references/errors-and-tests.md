# Errors and tests

The two places slop does real damage rather than merely wasting reading time. Swallowed
errors produce wrong answers silently; tests that cannot fail certify them.

## Error handling

### Catch what you can handle, where you can handle it

A `try` block earns its place when this handler, at this layer, can do something *specific*
about this *specific* failure: retry, fall back to a documented default, add context and
re-raise, clean up. If none of those apply, let it propagate — the layer that can decide is
higher up, and the traceback you did not swallow is what makes it debuggable.

```python
# No — hides everything including bugs in parse()
try:
    return parse(body)
except Exception:
    return None

# Yes — one expected failure, handled, with the cause kept
try:
    return parse(body)
except json.JSONDecodeError as e:
    raise InvalidPayload(f"{url} returned non-JSON ({len(body)} bytes)") from e
```

### Rules

1. **Never bare `except:` or `except Exception` with `pass`.** It catches the typo in the
   `try` block too.
2. **Narrow the exception type.** `except KeyError` documents what you expected to go
   wrong; `except Exception` documents nothing.
3. **Keep the cause.** `raise X from e` in Python; wrap rather than replace elsewhere.
   Losing the original traceback turns a five-minute debug into an hour.
4. **Never log-and-continue as the default.** `log.error(...)` followed by carrying on with
   partial state means the program now computes a wrong answer *and* reports success. Log
   and re-raise, or handle it properly.
5. **A default return value is a design decision, not a safety net.** `return []` on failure
   is fine when "nothing found" and "lookup failed" are genuinely the same to every caller.
   They usually are not.
6. **Narrow the `try` body.** Wrap the one call that can fail, not the twenty lines around
   it, or the handler catches failures it was never written for.
7. **`finally` or a context manager for cleanup** — not a handler that re-raises just to
   close a file.
8. **Do not validate the same thing at every layer.** Validate at the boundary; inside,
   assert an invariant if you must document it, and let it break loudly if violated.
9. **Error messages name the input.** `f"invalid port {port!r} in {path}"` beats
   `"invalid configuration"` by the length of the debugging session.

### Where defensive code *is* right

At trust boundaries, and be thorough there: user input, request payloads, CLI arguments,
file contents, environment variables, responses from other services, deserialised data, and
anything crossing a security boundary. Validate once, convert to a trusted type, and trust
it from then on.

## Tests

### A test must be able to fail

Break the implementation on purpose — return a constant, flip a comparison, delete a line —
and watch the test go red. If it stays green, it tests nothing. This takes fifteen seconds
and is the only way to know.

### The empty-assertion family

```python
assert result is not None            # passes for the wrong object
assert len(out) > 0                  # passes for garbage
process(x)                           # "it doesn't raise"
assert mock_save.called              # passes when it saves the wrong row
assert isinstance(r, dict)           # passes for {}
```

Each is a real assertion only when the *absence* is the behaviour under test (a function
documented to return `None`, an empty-result case). Otherwise assert the value:

```python
assert result == Invoice(id=7, cents=1250, currency="usd")
assert [r.id for r in out] == [3, 1, 2]        # and the order is the behaviour
assert saved_row.status == "settled"
```

### Mock only what you must

Mock the network, the clock, randomness, the filesystem when it is slow, and paid APIs.
Do not mock the thing under test or the objects it computes with — a test whose assertions
are all about how mocks were called is a test of your implementation's call graph, and it
will fail on every correct refactor while passing on wrong answers.

```python
# Tests the call graph
def test_checkout():
    with patch("shop.tax") as tax, patch("shop.save") as save:
        checkout(cart)
        tax.assert_called_once_with(cart)
        save.assert_called_once()

# Tests the behaviour
def test_checkout_adds_tax_and_persists_total():
    order = checkout(cart_with(cents=1000), tax_rate=0.08, store=FakeStore())
    assert order.total_cents == 1080
    assert store.last_saved is order
```

### What to test

Pick cases by where the code can plausibly break, not by chasing a coverage number:

- the boundary — 0, 1, the limit, the limit + 1, empty, a single element;
- the error path — does it raise the documented exception, with the context;
- the case from the bug report, as a regression test that fails before your fix;
- the invariant — round-trip (`parse(render(x)) == x`), idempotency, ordering,
  conservation (totals match), and where inputs are wide, a property-based test beats
  twenty examples;
- concurrency and time, if the code touches either.

Skip: a happy-path test per getter, tests of the language or the framework, snapshot tests
that nobody reads and everybody regenerates.

### Test hygiene

- **One behaviour per test**, named for that behaviour —
  `test_retry_gives_up_after_three_attempts` tells you what broke from the failure line
  alone.
- **No logic in tests.** A loop or `if` in a test means either several tests or a
  parametrised one; branching tests hide which case failed.
- **Deterministic.** Fixed seeds, injected clock, no reliance on dict ordering across
  versions or on test execution order.
- **No sleeps.** Wait on the condition, or inject the clock.
- **Fixtures only for what the test needs.** A shared mega-fixture makes every failure
  require reading the whole file.
- **Never** skip, `xfail`, loosen or delete a failing test to get green without
  understanding it. The failure is information; a test you weakened is a bug you shipped.
