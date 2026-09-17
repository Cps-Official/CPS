# CP+* toolchain

The repository has two execution paths:

1. **Interpreter** — the compatibility/reference runtime for the complete
   tree-walking language (`cpps_native/cpps.py file.cpps`).
2. **Native compiler** — a strict scalar backend (`--build` or
   `--run-native`) that lowers supported AST to C11 and invokes GCC. It never
   calls the interpreter. Unsupported AST nodes fail with a source location so
   that a backend extension cannot silently change program semantics.

The shared compiler pipeline is:

```
source -> Lexer -> Parser/AST -> semantic checker -> typed IR -> optimizer
       -> interpreter OR native C11 backend -> runtime
```

## CLI

```text
cpps file.cpps                 # interpreter
cpps file.cpps --check         # types, arity, ownership
cpps file.cpps --ast            # AST tree
cpps file.cpps --tokens         # token stream with spans
cpps file.cpps --ir             # verified optimized IR
cpps file.cpps --build -o app  # native executable
cpps file.cpps --run-native    # build and execute native executable
cpps file.cpps --format        # conservative whitespace formatter
cpps --test                    # project test suite
```

`--check` is also available as `--type`; diagnostics can be consumed through
the `AnalysisResult.to_json()` API. Package metadata lives in `cp.toml` and
path dependencies resolve into a deterministic content-hashed lock file.

## Native support boundary

The first backend slice supports scalar `int`, `float`, `bool`, `string`,
arithmetic/comparison expressions, typed functions, `if`, returns, variables,
function calls and `io::println`. Collections, classes, goroutines and
pattern matching continue to use the interpreter until their ownership and
runtime ABI are represented in the IR.
