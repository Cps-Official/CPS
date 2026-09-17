# ⚡ CP+* (C-Plus-Plus-Star)

[![CP+*](https://img.shields.io/badge/CP%2B*-beta-blue)](https://github.com/markzambrem/cpps-native)
[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Version](https://img.shields.io/badge/version-2.0.0-orange)](https://github.com/markzambrem/cpps-native)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen)](http://makeapullrequest.com)

**CP+*** là ngôn ngữ lập trình hoàn toàn mới, được thiết kế bởi **Cps-Official** với triết lý kết hợp sức mạnh của C++, sự thanh lịch của Python, và những ý tưởng hiện đại từ Rust, Go và Swift. Đây không phải bản sao của bất kỳ ngôn ngữ nào — CP+* có cú pháp, hệ thống kiểu và mô hình thực thi độc đáo của riêng mình.

---

## 🔥 Điểm nổi bật

- **Cú pháp độc đáo** — `:=`, `:: mut`, `++`, `??`, `<>`, `~>`, `<-`, `!!`, `?~`, `@`
- **Ownership System** — `own<T>`, `share<T>`, `borrow<T>` không cần GC
- **OOP đầy đủ** — `class`, `struct`, `trait`, `impl`, kế thừa, `@@override`
- **Concurrency** — Goroutines và Channels
- **Pattern Matching** — `?~ value { pattern => body }`
- **Macros & Reflection** — `@macro_tok`, `@macro_ast`, `@reflect`
- **Hỗ trợ Unicode** — Viết code bằng tiếng Việt, CJK, Ả Rập
- **Xử lý lỗi** — `try/catch/finally`, `Result<Ok, Err>`

---

## 📝 Cú pháp cơ bản

| Ký hiệu | Ý nghĩa | Ví dụ |
|---------|---------|-------|
| `:=` | Biến bất biến | `x := 42` |
| `:: mut` | Biến mutable | `y :: mut int = 0` |
| `++` | Định nghĩa hàm | `++ add <~ (a: int) -> int ** { ... }` |
| `??` | If | `?? x > 0 ** { ... }` |
| `<>` | For-each (kể cả trên range) | `<> i :: items ** { ... }` hoặc `<> i :: 0..5 ** { ... }` |
| `..` / `..=` | Range (loại trừ / bao gồm cận trên) | `0..5` (0..4), `0..=5` (0..5) |
| `loop { }` | Vòng lặp vô hạn (= `while true { }`) | `loop { ... !> }` |
| `while` | While loop | `while x < 10 ** { ... }` |
| `~>` | In ra / pipe | `~> io::println("Hello")` |
| `<-` | Return | `<- result` |
| `!!` | Panic | `!! "error"` |
| `?~` | Pattern match | `?~ value { 1 => { ... } }` |
| `@` | Self reference | `@.name = "Rex"` |

---

## 📦 Cài đặt

```bash
git clone https://github.com/Cps-Official/CPS.git
cd CPS
```

Yêu cầu: Python 3.8+

---

🚀 Sử dụng

```bash
# Chạy file CP+*
python cpps.py hello.cpps

# REPL (Read-Eval-Print Loop)
python cpps.py

# Chạy code inline
python cpps.py -e 'x := 42; ~> io::println("x = {}", x)'

# Xem AST
python cpps.py --ast hello.cpps

# Xem tokens
python cpps.py --tokens hello.cpps

# Chế độ verbose
python cpps.py hello.cpps --verbose
```

---

📝 Ví dụ chi tiết

Hello World

```cpp
++ main <~ () -> int ** {
    name := "CP+*"
    ~> io::println("Hello, {}!", name)
    <- 0
}
```

Biến và kiểu dữ liệu

```cpp
-- Immutable
x := 42
name := "CP+*"
pi := 3.14159
is_ok := true

-- Mutable
y :: mut int = 0
message :: mut string = "hello"

-- Ownership
own<int> a := 100
share<string> b := "shared"
borrow<int> c := a
```

Hàm và điều kiện

```cpp
++ factorial <~ (n: int) -> int ** {
    ?? n <= 1 ** {
        <- 1
    } -- else ** {
        <- n * factorial(n - 1)
    }
}

?? score >= 90 ** {
    ~> io::println("Xuất sắc!")
} -- elif score >= 70 ** {
    ~> io::println("Tốt")
} -- else ** {
    ~> io::println("Cần cố gắng")
}
```

Vòng lặp

```cpp
<> i :: [1, 2, 3, 4, 5] ** {
    ~> io::println("i = {}", i)
}

count := 0
while count < 10 ** {
    ~> io::println("count = {}", count)
    count += 1
}
```

Lớp và OOP

```cpp
class Animal -> {
    name :: mut string = ""
    age :: mut int = 0
    
    ++ new <~ (n: string, a: int) ** {
        @.name = n
        @.age = a
    }
    
    ++ speak <~ () -> void ** {
        ~> io::println("{} says: ...", @.name)
    }
}

class Dog : Animal -> {
    breed :: string = "Mixed"
    
    ++ new <~ (n: string, a: int, b: string) ** {
        super::new(n, a)
        @.breed = b
    }
    
    @@override
    ++ speak <~ () -> void ** {
        ~> io::println("{} says: Woof!", @.name)
    }
}

dog := Dog::new("Rex", 3, "German Shepherd")
dog:speak()  -- Rex says: Woof!
```

Pattern Matching

```cpp
?~ value {
    0 => { ~> io::println("zero") },
    1 | 2 | 3 => { ~> io::println("small: {}", value) },
    x if x > 100 => { ~> io::println("large: {}", x) },
    (a, b) => { ~> io::println("tuple: ({}, {})", a, b) },
    Ok(value) => { ~> io::println("Success: {}", value) },
    Err(msg) => { ~> io::println("Error: {}", msg) },
    _ => { ~> io::println("other") }
}
```

Goroutine và Channel

```cpp
ch := Channel(10)

-- Producer
go ** {
    <> i :: 0..10 ** {
        ch:send(i)
    }
    ch:close()
}

-- Consumer
loop {
    value := ch:recv()
    ?? value is none ** { !> }
    ~> io::println("Received: {}", value)
}
```

(Matches `examples/e5_goroutine.cpps`, verified to run end-to-end.)

Xử lý lỗi

```cpp
try ** {
    file := File::open("data.txt")
    content := file:read()
    process(content)
} catch (e) ** {
    ~> io::println("Error: {}", e)
} finally ** {
    ~> io::println("Cleanup")
}

-- Result<T, E>
result := divide(10, 2)
?~ result {
    Ok(value) => { ~> io::println("Result: {}", value) },
    Err(err) => { ~> io::println("Error: {}", err) }
}
```

Generic

```cpp
++ identity<T> <~ (x: T) -> T ** {
    <- x
}

class Stack<T> -> {
    data :: mut List<T> = []
    
    ++ push <~ (item: T) -> void ** {
        @.data:push(item)
    }
    
    ++ pop <~ () -> T ** {
        <- @.data:pop()
    }
}

s := Stack<int>::new()
s:push(1)
s:push(2)
value := s:pop()  -- 2
```

---

🧪 REPL Commands

Lệnh Mô tả
:help, :h Hiển thị trợ giúp
:quit, :q, :exit Thoát REPL
:clear, :c Xóa màn hình
:reset Reset interpreter
:env Hiển thị biến trong scope
:ast <code> Xem AST của code
:tokens <code> Xem danh sách token
:time <code> Đo thời gian thực thi
:type <expr> Hiển thị kiểu dữ liệu
:load <file> Load và chạy file .cpps

---

🏗️ Kiến trúc

Module Vai trò
cpps.py Entry point, CLI, REPL
lexer.py Tokenizer (Unicode, template strings, nested comments)
tokens.py 120+ Token types, precedence tables
parser.py Recursive descent parser → AST
interpreter.py Tree-walking interpreter, runtime

```
Source (.cpps) → Lexer → Tokens → Parser → AST → Interpreter → Kết quả
```

---

📚 Thư viện chuẩn

```cpp
-- I/O
io::println("Hello")
io::print("No newline")
input := io::read_line()

-- Toán học
math::sqrt(16)        -- 4.0
math::sin(pi/2)       -- 1.0
math::random()        -- 0.0..1.0
math::randint(1, 100) -- random integer

-- Chuỗi
"hello":to_upper()    -- "HELLO"
"  trim  ":trim()     -- "trim"
"a,b,c":split(",")    -- ["a", "b", "c"]

-- Collection
[1, 2, 3]:map(|x| x * 2)      -- [2, 4, 6]
[1, 2, 3]:filter(|x| x > 1)   -- [2, 3]
[1, 2, 3]:reduce(|a, b| a + b) -- 6

-- Thời gian
now := time::now()
time::sleep(1.0)
format := time::format("%Y-%m-%d")

-- File
content := file::read("data.txt")
file::write("output.txt", content)

-- JSON
data := json::parse('{"name": "Alice"}')
json::stringify(data)
```

---

## 🧪 Testing

```bash
python -m pytest -q
python cpps_native/cpps.py --test
python cpps_native/cpps.py examples/e1_hello.cpps --check
python cpps_native/cpps.py examples/e1_hello.cpps --ir
python cpps_native/cpps.py examples/e1_hello.cpps --build -o ./e1.native
```

The suite covers the lexer/interpreter self-checks, OOP inheritance
(including `super::method(...)`), parser fixes, typed IR verification,
optimizer passes, module cycle detection, and a real GCC-produced
native executable.

## ⚠️ Known Limitations

Found and tracked during audit passes (see `AUDIT_REPORT.md` for the
full writeup). Fixed so far: `super::method(...)` dispatch,
double-execution of void static/`super` calls, `Type::method(args)`
misparsed as a variable declaration, `1 | 2 | 3` OR-patterns, `is
none` comparisons, `|x| expr` lambda literals (closures now work,
including capture of enclosing variables), **`loop { ... }`**
(now a real keyword, desugaring to `while true { ... }`, so it gets
`!>`/`!>>` for free), and **range expressions** (`0..5`, `0..=5`) —
the interpreter already evaluated `RangeExpr` into a list of ints, but
the parser never actually built one outside of match patterns, so
`<> i :: 0..5 ** { ... }` was a silent no-op. It now works anywhere an
expression is valid, including with variable/expression bounds
(`<> i :: a+1..b-1 ** { ... }`). Also fixed: a **`main()`
double-execution bug** — a script that both defined `++ main <~ ...`
and explicitly called `main()` (the style `examples/e1_hello.cpps`
uses) ran the whole body of `main` twice, because the interpreter
unconditionally auto-called `main` again after top-level statements
finished. The auto-call now only fires when the script never called
`main` itself.

Current boundaries are explicit rather than silently advertised as complete:

- The semantic pass checks scalar declarations, assignments, function arity
  and scalar argument/return types. It also diagnoses the implemented
  ownership moves and borrow conflicts. Structured generic constraints and
  lifetime inference remain gradual.
- `break` and `continue` are accepted in both symbolic (`!>`, `!>>`) and
  English forms.
- The native backend currently covers scalar values, functions, conditions,
  arithmetic/comparisons and `io::println`. Collections, classes, goroutines
  and pattern matching use the reference interpreter until their runtime ABI
  is represented in IR; `--build` rejects those nodes instead of falling
  back to Python.
- `cp.toml` and `cpps_native/src/package.py` provide deterministic local path
  dependency resolution with content hashes. Registry/network fetching is
  intentionally outside this repository.
- Goroutines run on real Python threads with a real blocking queue
  (`Channel`) — this is genuine concurrency, not a simulation, but it
  hasn't been audited for race conditions beyond basic send/recv/close.

---

🤝 Đóng góp

1. Fork repository
2. Tạo branch mới (git checkout -b feature/AmazingFeature)
3. Commit thay đổi (git commit -m 'Add some AmazingFeature')
4. Push lên branch (git push origin feature/AmazingFeature)
5. Mở Pull Request

---

📄 Giấy phép

MIT License © 2026 Cps-Official

---

🌟 Tác giả

Cps-Official — Creator & Lead Developer
---
Built with ❤️ and Python-CPS
