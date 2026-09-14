# The slop catalog

Each entry: what it looks like, why it is generated, and what to do instead. Diffs are
Python for brevity; every pattern here appears in every language.

---

## 1. The parallel implementation

```
+ src/parser_v2.py        (280 lines)
  src/parser.py           (unchanged)
```

**Why it happens:** editing existing code risks breaking it; writing beside it does not.
**Cost:** every future reader must determine which file runs, and both drift.
**Instead:** change `parser.py`. If the rewrite is large enough to want a clean slate, still
land it *as* `parser.py` and delete the old body in the same commit. One name, one
behaviour.

Same pattern, smaller: `handle_request_new()`, `ConfigManagerImpl`, `process_data_final()`.

---

## 2. Speculative generality

```python
# Slop
class Notifier(ABC):
    @abstractmethod
    def send(self, msg: str) -> None: ...

class EmailNotifier(Notifier):
    def send(self, msg: str) -> None:
        smtp_send(self.addr, msg)

NOTIFIERS: dict[str, type[Notifier]] = {"email": EmailNotifier}

def notify(kind: str, msg: str) -> None:
    NOTIFIERS[kind]().send(msg)
```

```python
# Not slop — there is one notifier
def notify(msg: str) -> None:
    smtp_send(ALERT_ADDR, msg)
```

The abstract base, the registry and the string dispatch exist for the Slack notifier nobody
has asked for. When it arrives, extracting an interface from two concrete implementations
takes ten minutes and you will know what the interface should be — which you do not now.

**The test:** how many callers/implementations exist *today*? One means write the concrete
thing. This is also the answer to a `**kwargs` passthrough, a `config: dict` nobody
populates, and an `options` object with one field.

---

## 3. The one-caller wrapper

```python
# Slop
def get_user_by_id(user_id: int) -> User:
    return db.query(User).filter(User.id == user_id).one()

def fetch_user(user_id: int) -> User:
    return get_user_by_id(user_id)
```

Forwarding arguments unchanged is renaming, not abstraction. Inline it. Keep a thin wrapper
only when it hides something genuinely ugly (a vendor API's argument order), gives a test a
seam it actually needs, or is the public name of an internal function.

---

## 4. Defensive swallowing

```python
# Slop
def load_config(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}
```

The caller now runs with empty config and no idea why. A typo'd path becomes a mysterious
behaviour change two subsystems away, at a timestamp nobody can correlate.

```python
# Fine — the error reaches someone
def load_config(path: str) -> dict:
    with open(path) as f:
        return json.load(f)
```

```python
# Also fine — a default is the documented behaviour, and only for the one expected case
def load_config(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return DEFAULTS          # first run has no config file
```

The difference is a *specific* exception, a *deliberate* fallback, and a note saying why.
`except Exception` with a shrug is never that.

---

## 5. Guard rails for impossible states

```python
# Slop
def area(rect: Rectangle) -> float:
    if rect is None:
        return 0.0
    if not hasattr(rect, "width"):
        return 0.0
    if rect.width < 0 or rect.height < 0:
        return 0.0
    return rect.width * rect.height
```

Three branches no test exercises and no caller reaches, and `0.0` for a negative width is a
wrong answer dressed as safety. Validate when the value crosses a trust boundary; inside,
trust your types.

---

## 6. Narration

```python
# Slop
# Initialize the results list
results = []
# Loop through each item in the input
for item in items:
    # Check if the item is valid
    if item.valid:
        # Append the item to the results
        results.append(item)
# Return the results
return results
```

Every comment restates its line. They are pure cost: they go stale, they hide the one
comment that would have mattered, and they triple the reading length. Delete all of them;
see `comments-docs-naming.md` for the ones worth keeping.

---

## 7. Docstring as signature echo

```python
# Slop
def resize(img: Image, width: int, height: int) -> Image:
    """Resize an image.

    Args:
        img: The image.
        width: The width.
        height: The height.

    Returns:
        The resized image.
    """
```

Eleven lines that say what the four-token signature already said. Either state a real
contract or write nothing:

```python
def resize(img: Image, width: int, height: int) -> Image:
    """Resize to exactly width x height, ignoring aspect ratio. Raises ValueError on 0."""
```

---

## 8. Compatibility shims nobody asked for

```python
# Slop
def compute_total(items, *, tax_rate=0.0):
    ...

# Backwards compatibility
calculate_total = compute_total           # old name
def compute_total_legacy(items):
    return compute_total(items, tax_rate=0.0)
```

Inside a codebase you control, you have all the callers — rename them and delete the old
name in the same commit. A shim is justified only for a published API with callers you
cannot see, and then it is deliberate: deprecation warning, documented removal version, and
an entry wherever the repo tracks that.

Same shape: `if os.getenv("USE_NEW_PATH")`, a `legacy=True` default, keeping a dead branch
"in case we need to roll back" — that is what version control is.

---

## 9. Duplication by generation

The second helper is written because searching for the first one is slower than writing it.

```
src/api/format.py:   def to_snake(s): ...
src/jobs/naming.py:  def snake_case(s): ...
src/utils.py:        def camel_to_snake(s): ...
```

Three subtly different implementations, one of which is wrong on `HTTPResponse`. Search
before writing: grep the plausible names, and the plausible *bodies* (`re.sub`, `lower()`).
When you find the duplicate mid-change, consolidate it rather than adding the fourth.

---

## 10. The `utils.py` dumping ground

A file named for what it is *not* attracts everything that does not have a home, and then
nobody can tell what depends on it. Put the function next to what it serves — the one-caller
helper goes in the caller's module, and `retry_with_backoff` goes in `http.py` if HTTP is
what retries.

---

## 11. Tests that cannot fail

```python
# Slop
def test_process():
    result = process(SAMPLE)
    assert result is not None

def test_calls_backend():
    with patch("mod.backend") as m:
        process(SAMPLE)
        assert m.called
```

Both pass when `process` returns the wrong answer. Assert the value:

```python
def test_process_splits_on_semicolons():
    assert process("a;b") == ["a", "b"]
```

The check on any test you are about to keep: break the implementation deliberately, and
watch the test go red. See `errors-and-tests.md`.

---

## 12. Change artifacts committed as files

```
+ SUMMARY.md
+ IMPLEMENTATION_NOTES.md
+ CHANGES_MADE.md
+ test_manual.py
```

Notes describing what a diff did belong in the commit message and the PR body, where they
sit next to the diff forever. As files they are stale within a week and nobody deletes them.
Exception: a document the repo's convention actually calls for — an ADR directory, a
`CHANGELOG.md` the project maintains, docs the change genuinely invalidates.

---

## 13. Decoration

Emoji in log lines, banner comments (`# ==== HELPERS ====`), boxed headers, `print("✅
Done!")` in library code. It reads as enthusiasm rather than engineering, it breaks
log-parsing and terminals, and it is the single most recognisable tell of generated code.
Plain text, standard logging.

---

## 14. The commented-out alternative

```python
# result = old_method(x)
# result = another_attempt(x)
result = current_method(x)
```

Dead code in comments is dead code with worse tooling: no linting, no tests, no refactoring,
and it makes every reader wonder whether it is the fallback. Delete it; git has it.

---

## 15. The too-large diff

Not a pattern but the aggregate symptom, and the one reviewers feel. A 400-line diff for a
20-line change hides the 20 lines. If the change needed genuine refactoring, land the
refactor as its own commit with no behaviour change, then the fix — two reviewable diffs
beat one unreviewable one.
