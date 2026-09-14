# Comments, docstrings, names

## The comment rule

A comment earns its place when it holds information the code cannot: **why**, not what. The
code already says what it does, and says it more reliably, because it cannot go stale.

### Delete

| Comment | Why it goes |
|---|---|
| `# increment i` above `i += 1` | Restates the line |
| `# Step 1: parse the input` | Narrates structure the reader can see |
| `# helper function` above a function | Says nothing |
| `# returns the user` above `return user` | Restates the line |
| `# TODO: improve this` | No owner, no next step — noise forever |
| `# ==== SECTION ====` | Use a function or a module |
| `# Author: ..., Date: ...` | Version control has it, and it is wrong within a month |
| A comment block restating the docstring | Pick one |

### Keep

```python
# The vendor's API returns 200 with an error body, so the status code is not enough.
if "error" in payload:
    raise VendorError(payload["error"])
```

```python
# Sorted by (priority, arrival) because the scheduler assumes FIFO within a priority band.
queue.sort(key=lambda t: (t.priority, t.arrival))
```

```python
# Timeout is 35s, not 30s: the upstream gateway itself times out at 30s and we want
# their error message rather than ours. See incident 4412.
TIMEOUT = 35
```

```python
# Empirically the copy is faster than the in-place version below ~10k rows; measured
# in bench/sort_bench.py.
```

The pattern: a non-obvious reason, a constraint from outside the file, a measurement, a
reference to an incident or issue, a deliberate deviation from the local convention, or an
invariant the type system cannot express.

### The workaround comment is mandatory

Any line that looks wrong but is right needs one, or the next person "fixes" it:

```python
# Dropping the index before the bulk insert is 40x faster; re-created below.
```

Without that, the deletion looks like a bug and gets reverted.

## Docstrings

Write one when there is a contract to state. Skip it when the signature already says
everything.

**Skip:**

```python
def user_count(self) -> int:
    return len(self._users)
```

**Write:**

```python
def charge(self, account: Account, cents: int) -> ChargeId:
    """Charge in the account's own currency; `cents` is minor units, never a float.

    Idempotent per (account, cents) within 60s — a retry returns the original ChargeId.
    Raises InsufficientFunds (no charge made) or GatewayTimeout (charge state unknown,
    reconcile with `poll_charge`).
    """
```

What made the second one worth writing: units, idempotency window, which errors leave which
state. None of it is in the signature, and all of it is what a caller gets wrong.

Checklist for a docstring you are about to keep:

- [ ] Does it say anything the signature and type hints do not?
- [ ] Does it state units, ranges, or ownership where those matter?
- [ ] Does it name the exceptions raised, and what state they leave behind?
- [ ] Does it document edge cases (empty input, zero, concurrent calls)?
- [ ] Is it free of `Args:`/`Returns:` blocks that only repeat parameter names?

None ticked → delete it. Follow the repo's existing docstring convention when it has one;
consistency matters more than which format is better.

## Names

A name is the most-read documentation in the codebase, and the cheapest to get right.

| Avoid | Prefer | Reason |
|---|---|---|
| `data`, `info`, `obj`, `item2` | `invoice`, `raw_rows`, `retry_count` | Says what it is |
| `process()`, `handle()`, `do_work()` | `validate_invoice()`, `retry_failed_jobs()` | Says what happens |
| `Manager`, `Helper`, `Service`, `Util` | `ConnectionPool`, `PriceIndex` | Names the thing, not its vagueness |
| `flag`, `check`, `tmp` | `is_expired`, `has_quota` | Booleans read as predicates |
| `get_data_from_db_as_list()` | `fetch_orders()` | Type is in the signature |
| `n`, `x`, `i` as function parameters | `retries`, `offset` | Single letters only as loop indices or in maths that mirrors a formula |
| `utils.py`, `misc.py`, `common.py` | `text.py`, `retry.py`, `pricing.py` | Files named for content have an obvious home |

Further rules that survive contact with real code:

- **Units in the name when a unit is ambiguous:** `timeout_seconds`, `size_bytes`,
  `price_cents`. This prevents a class of bug that types do not.
- **Match the domain's vocabulary.** If the business says "settlement", the code says
  `settlement`, not `payment_finalization`.
- **Say the same thing the same way repo-wide.** Do not introduce `fetch_` next to an
  established `get_`; grep first and follow.
- **Length tracks scope.** A three-line comprehension can use `r`; a module-level constant
  cannot.
- **Do not encode the type.** `user_list`, `str_name`, `dict_config` — the signature says it
  and the name lies after a refactor. `users` is enough.
- **Negations are hard to read.** Prefer `is_enabled` to `is_not_disabled`, and never
  `if not is_not_disabled`.
