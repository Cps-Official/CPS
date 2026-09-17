# CP+* Audit Report

Scope of this pass: audit the repository, find real bugs (not just
gaps), fix a bounded set of them with verified tests, and be explicit
about what's still missing. This was **not** a full production-grade
overhaul (static type checker, ownership/borrow enforcement, a full
concurrency/module-system audit, benchmarking, and a formatter are all
still open — see "What's still unfinished" below).

## 1. Architecture, as found

CP+* is a single-person, tree-walking interpreter for a custom
language, written in ~9,600 lines of Python across four files:

- `cpps_native/src/tokens.py` — `TokenType` enum, keyword table,
  operator precedence table.
- `cpps_native/src/lexer.py` — hand-written lexer, Unicode-aware
  (accepts Vietnamese/CJK/Arabic identifiers), has its own
  `_run_tests()` self-check.
- `cpps_native/src/parser.py` — hand-written recursive-descent parser
  (+ precedence-climbing for binary expressions) producing a dataclass
  AST; also has `ASTPrinter`.
- `cpps_native/src/interpreter.py` — tree-walking evaluator: `Env`
  (lexical scopes), `CPPSInstance`/`CPPSClosure`/`CPPSChannel` runtime
  objects, and an `Interpreter` class with `exec`/`eval`. Also has its
  own `_run_tests()`.
- `cpps_native/cpps.py` — CLI/REPL entry point. Adds `src/` to
  `sys.path` and imports the above as flat modules (`from tokens
  import ...`, not `from .tokens import ...` or `from src.tokens
  import ...`) — meaning the package only really runs via this one
  entry point's path hack, not as a normal installable package.

There was **no test suite, no examples directory, and no way to run
the project with a standard test runner** before this session — only
the two `_run_tests()` self-checks embedded in `lexer.py` and
`interpreter.py`, run manually.

Concurrency is real: goroutines run on actual Python `threading.Thread`
objects, and `Channel` is a real `queue.Queue`-backed blocking queue
with a `_closed` flag — not a simulation.

## 2. Issues found

All of these were confirmed by actually running code, not inferred
from reading:

1. **`super::method(...)` was completely inert.** `super` was
   tokenized (`KW_SUPER`) but never handled anywhere in the parser, so
   `super::new(n, a)` silently parsed as `::new(n, a)` (empty class
   name) and did nothing. Any subclass constructor that called
   `super::new(...)` got none of the inherited field initialization.
2. **The inheritance model separately double-constructed parents.**
   `_instantiate` called the parent's own constructor with an *empty*
   argument list before the child constructor ever ran, corrupting
   fields regardless of `super`.
3. **Any void namespaced call executed its body twice.**
   `_exec_fn_call` re-ran `_exec_namespaced_call` a second time
   whenever the first call returned `None` (using `result is not
   None` as a "was this handled?" proxy). This silently double-fired
   any void static method — and, once `super` was fixed, any void
   `super::` call too. This bug predates this session; `super` calls
   just happened to be what exposed it.
4. **`ClassName::method(args)` used as a bare statement (no
   assignment) was misparsed as a variable declaration** —
   `Logger::warn("x")` parsed as `Logger :: warn = "x"` — because the
   statement dispatcher assumed any `IDENTIFIER ::` prefix meant a var
   decl, with no lookahead for the call case.
5. **OR-patterns (`1 | 2 | 3 => ...`) were documented but never
   parsed.** The interpreter's `_match_pattern` already had working
   `OrPattern` handling; the parser simply never constructed one.
6. **`is`/`is none` comparisons, used in the README, weren't a
   recognized token at all** — `is` parsed as a plain identifier
   (undefined variable), always falsy/`None`.
7. **Lambda literals (`|x| expr`) had no working parser syntax at
   all**, despite `LambdaExpr` and `CPPSClosure` being fully
   implemented in the interpreter and the README documenting
   `:map(|x| ...)`/`:filter(...)`/`:reduce(...)` throughout. This made
   real closures (capturing an enclosing scope) unreachable from any
   CP+* source — the one existing "Closure" self-test didn't actually
   capture anything, it just aliased a named function.
8. **`loop { ... }`**, used in the README's own goroutine example, is
   not a keyword or statement anywhere in the codebase. It parses as
   an undefined-variable reference followed by a block that runs
   exactly once, not a loop.
9. **The word `break`**, also used in that same README example, isn't
   a keyword — only the `!>` symbol works. Documented code using
   `break` never actually exits its loop.
10. **`for i in 0..10 { ... }`** (Rust-style for-loop), used in the
    same README example, doesn't exist either — only `<>` for-each
    over a collection works.
11. **No type enforcement anywhere.** `-> int`, `: string`, etc. parse
    and are stored on `FnDef`/`VarDecl` but are never checked. `/`
    always does Python float division regardless of operand types or
    declared return type (`divide(10, 2) -> int` still returns `5.0`).
12. No test suite, no examples, package only runs via `cpps.py`'s
    `sys.path` hack (see Architecture above).

## 3. What was fixed (with tests)

| # | Issue | Fix |
|---|-------|-----|
| 1, 2, 3 | `super::` broken + double-construction + double-execution | Added `KW_SUPER` parsing; new `_class_context_stack` + `_find_method_in_chain` + `_exec_super_call` in the interpreter, dispatching to the parent bound to the *same* `self`; rewrote `_instantiate` to merge parent fields/methods via a new `_collect_class_members` (no eager constructor calls) and run only the resolved constructor once; introduced an `_NAMESPACE_UNHANDLED` sentinel so `_exec_fn_call` can tell "resolved but void" apart from "not found" instead of retrying on `None` |
| 4 | Static call statement misparsed | Added `_looks_like_static_call_stmt()` lookahead before the var-decl branch |
| 5 | OR-patterns not parsed | `parse_pattern` now wraps `\|`-separated alternatives in `OrPattern` (interpreter side was already correct) |
| 6 | `is`/`is none` not recognized | Added `KW_IS` token; `parse_compare` maps `is` onto the same runtime equality as `==` |
| 7 | Lambda literals unreachable | Added `\|params\| expr` / `\|params\| ** { block }` parsing in `parse_primary`, producing the existing `LambdaExpr` node |

Issues 8, 9, 10, 11 were **not** fixed — they're recorded as `xfail`
tests in `tests/test_known_gaps.py` and called out in the README
instead, since implementing an infinite-loop statement, a `break`
keyword, a `for..in` range loop, and any form of type checking are
each non-trivial, separately-scoped features I didn't have budget to
implement and verify properly in this pass. I fixed the one README
example that used all three (`examples/e5_goroutine.cpps` and the
corresponding README snippet) to use the syntax that actually works
(`while true` + `!>`) rather than leave a documented example broken.

## 4. Files changed

- `cpps_native/src/tokens.py` — added `KW_SUPER`... (already existed)
  and new `KW_IS` token + keyword entry.
- `cpps_native/src/parser.py` — `super::` parsing, lambda literal
  parsing, OR-pattern parsing, `is` comparison, static-call-statement
  lookahead.
- `cpps_native/src/interpreter.py` — `_class_context_stack`,
  `_find_method_in_chain`, `_exec_super_call`, `_collect_class_members`,
  rewritten `_instantiate`, `_NAMESPACE_UNHANDLED` sentinel and the
  `_exec_fn_call`/`_exec_namespaced_call` changes around it, class
  context push/pop added to every method/constructor dispatch site.
- `README.md` — fixed the goroutine/channel example to use working
  syntax; added **Testing** and **Known Limitations** sections.
- New: `tests/` (5 files), `examples/` (8 `.cpps` programs),
  `pytest.ini`, `requirements-dev.txt`, this report.

## 5. Tests added

25 tests across 4 files (`tests/test_core_self_tests.py`,
`tests/test_oop_inheritance.py`, `tests/test_parser_fixes.py`,
`tests/test_known_gaps.py`), plus `tests/conftest.py` (mirrors
`cpps.py`'s `sys.path` setup so tests import the real modules the CLI
uses) and `tests/helpers.py` (`run_capture()` — parses + runs CP+*
source through a fresh `Interpreter` and captures stdout).

Coverage: lexer/interpreter self-test wrapping, basic
expressions/functions/recursion/closures, five OOP-inheritance
scenarios (single-level `super::new`, constructor inheritance,
double-execution regression, three-level inheritance chain, field
defaults from parent), the five parser fixes above, and three
`xfail`-pinned known gaps.

Plus 8 example `.cpps` programs in `examples/` exercising hello-world,
ownership annotations, OOP/inheritance, pattern matching (including
OR-patterns), goroutines/channels, generics, `Result`/error handling,
and `try/catch/finally`.

## 6. Test results

This sandbox has no network access, so real `pytest` couldn't be
installed to run the suite in its final form here. I verified every
test with a small stdlib-only harness that faithfully reproduces the
`pytest.mark.xfail`/`parametrize` semantics used (not shipped —
`pytest.ini` + `requirements-dev.txt` are shipped instead for a normal
`pip install -r requirements-dev.txt && pytest tests/` run):

```
PASS=22  XFAIL=3  FAIL=0  XPASS=0
```

All 22 real assertions pass; all 3 `xfail`-marked known-gap tests
correctly fail (confirming those gaps are real and still open, not
accidentally fixed along the way). Also re-ran the pre-existing
`lexer._run_tests()` (all passing) and `interpreter._run_tests()`
(19/19 passing) after every group of changes — no regressions.

## 7. Features still incomplete / unimplemented

- Static or runtime type checking (item 2 of the original request) —
  not started.
- Ownership/borrow enforcement (item 3) — `own`/`share`/`borrow`
  parse but nothing checks move-after-use, conflicting borrows, or
  lifetimes. Not started.
- Error system standardization / source-span-on-every-error (item 4) —
  not audited this pass.
- The word `break` (as opposed to the `!>` symbol) — confirmed
  missing, not implemented; this is a deliberate CP+* syntax choice
  more than a gap, so it's lower priority than it looks.
- Concurrency audit beyond what surfaced incidentally (item 6) — the
  goroutine/channel example now genuinely works end-to-end, but no
  systematic review for race conditions, deadlocks, or channel-closing
  edge cases was done.
- Module system audit (item 8), performance benchmarking (item 9),
  formatter/tooling (item 10) — not started.

## 8. Before / after (subjective, out of 10)

**Before (session 1): ~4/10.** A genuinely capable interpreter core
(lexer, parser, closures-at-the-VM-level, real threads/channels)
undermined by zero tests, several silently-broken core-OOP features,
and README examples that didn't actually run as written.

**After session 1: ~5.5/10.** The specific bugs found are fixed and
pinned down with tests; the project can now be regression-tested.

**After session 2: ~6/10.** `loop { }` and range expressions
(`0..5`, `0..=5`) are real now, and a second silent double-execution
bug (`main()` called explicitly + auto-called again) was found and
fixed with tests — see §10. Still no type checking, no ownership
enforcement, no systematic audits of concurrency/modules/performance.
Each of those is a substantial, multi-session project on its own, not
something to be checkbox-implemented on top of an existing 12k-line
interpreter without real design work.

## 9. Suggested next steps, in priority order

1. A minimal static type checker: start with function argument/return
   type mismatches only (the highest-value, lowest-risk subset), with
   file:line:col errors, before attempting generics/trait constraints.
2. Ownership audit: at minimum, detect and error on use-after-move for
   `own<T>` values, since that's the headline feature of the language
   and currently isn't enforced at all.
3. A systematic concurrency audit (deadlock scenarios, channel double
   close, send-after-close) now that the basic path is verified
   working.
4. Wire up CI to run `pytest tests/` on every change so the
   regressions found across both sessions (double-execution bugs,
   silent parse mis-fires) get caught automatically going forward.
5. The word `break`/`continue` as keyword aliases for `!>`/`!>>`, if
   the project wants English-word syntax as an alternative rather
   than a deliberate design choice to keep `!>`/`!>>`.

## 10. Session 2 — follow-up fixes

Continuing from session 1's own "suggested next steps," this pass:

**Fixed, with tests:**

- **`loop { }`** — was not a keyword at all; parsed as an
  undefined-variable reference followed by a block that ran exactly
  once. Added `KW_LOOP`, desugaring at parse time to
  `WhileStmt(Literal(True), body)`, so it gets `!>`/`!>>` and
  interpreter support for free. The corresponding `xfail` test in
  `tests/test_known_gaps.py` was converted to a real, passing
  assertion (not deleted — turned into what it was tracking).
- **Range expressions (`0..5`, `0..=5`)** — the interpreter already
  had a working `RangeExpr` evaluator (materializes a list of ints),
  but the parser only ever built one inside match patterns, never in
  general expression position. Added a `parse_range()` precedence
  level (binds looser than `+`/`-`, tighter than comparisons), so
  `<> i :: 0..5 ** { ... }` and `<> i :: a+1..b-1 ** { ... }` both now
  work as documented usage would expect.
- **`main()` silently ran twice** — a real, previously-undetected
  semantic bug (not from session 1's list): `Program` execution
  unconditionally auto-called `main()` after running top-level
  statements, *even when the script had already called `main()`
  explicitly* — which is exactly the idiomatic style the repo's own
  `examples/e1_hello.cpps` used (`++ main <~ ... { ... }` followed by
  a bare `main()`). Every side effect inside `main` ran twice. Fixed
  by scanning top-level statements for an explicit `main()` call and
  skipping the auto-call only when one is present; auto-run-if-never-
  called is preserved as a separate, intentional convenience. Found
  by writing an end-to-end test for the `loop`/range fixes above and
  noticing "Hello, CP+*!" printed twice from an unrelated example.
- Updated `examples/e5_goroutine.cpps` and the matching README snippet
  to use `loop { }` + `0..10` now that both work, removing the stale
  "neither of these is implemented" comment.

**Verification run this session** (no network access, so `pytest`
itself wasn't installable — verified with the lexer/interpreter's own
`_run_tests()` self-checks, plus a small stdlib-only pytest-compatible
shim that executes the real `tests/*.py` files unmodified, including
`@pytest.mark.parametrize` and `@pytest.mark.xfail(strict=True)`):

- Lexer self-test: pass.
- Interpreter self-test: 19/19 pass.
- Full `tests/` suite via the shim: **32 passed, 0 failed, 2 xfail**
  (the two remaining xfails — the word `break`, and static
  return-type enforcement — are intentional known gaps, not
  regressions; both still correctly fail).
- All 8 files in `examples/` run end-to-end via the real CLI
  (`cpps_native/cpps.py`) with exit code 0 and correct output,
  including the corrected `e1_hello.cpps` (now prints once) and
  `e5_goroutine.cpps` (now using `loop`/range).

**Files changed this session:** `cpps_native/src/tokens.py` (KW_LOOP),
`cpps_native/src/parser.py` (loop parsing, parse_range),
`cpps_native/src/interpreter.py` (main() double-call fix),
`tests/test_known_gaps.py` (xfail → real test),
`tests/test_loops_and_ranges.py` (new),
`tests/test_main_auto_call.py` (new), `examples/e5_goroutine.cpps`,
`README.md`.

**Still not started this session, unchanged from §9 above:** static
type checking, ownership/borrow enforcement, systematic concurrency
audit, module-system audit, benchmarking, formatter/tooling. These
remain the honest, current priority order for anyone continuing this
work — each is a substantial project, not a quick patch.

