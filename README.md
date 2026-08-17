# ArchRay

**Software Architecture Analyzer** · [miraccelikel/software-architecture-analyzer](https://github.com/miraccelikel/software-architecture-analyzer)

[![CI](https://github.com/miraccelikel/software-architecture-analyzer/actions/workflows/archray.yml/badge.svg)](https://github.com/miraccelikel/software-architecture-analyzer/actions/workflows/archray.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![Languages](https://img.shields.io/badge/analyses-Python%20%7C%20Java%20%7C%20TypeScript%20%7C%20C%23%20%7C%20C%2B%2B%20%7C%20C-informational)](https://github.com/miraccelikel/software-architecture-analyzer#the-pipeline)
[![Tests](https://img.shields.io/badge/tests-152%20passing-brightgreen)](https://github.com/miraccelikel/software-architecture-analyzer/tree/main/tests)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](https://github.com/miraccelikel/software-architecture-analyzer/blob/main/LICENSE)

Clones a repository, parses it into ASTs and puts its architectural health into one report:
**SOLID violations, code smells, cyclomatic complexity, design patterns, duplication and the
dependency graph** — plus what changed since the last revision.

**Python, Java, TypeScript, C#, C++ and C** are supported, and a project may use several of
them at once: `auto` detection analyses every language that carries a meaningful share of the
code and merges them into a single report.

```
repository ─► detect languages ─► filter ─► AST ─► symbol table ─► rules ─► JSON ─► dashboard
```

---

## Quick start

```bash
git clone https://github.com/miraccelikel/software-architecture-analyzer.git
cd software-architecture-analyzer
pip install -e ".[all]"          # or ".[java,csharp]" for just those grammars

# check the toolchain; it prints the exact command for whatever is missing
archray --doctor

# analyse anything; languages are detected automatically
archray https://github.com/pallets/click
archray https://github.com/google/gson
archray ./my-project

# pin a single language when you want one
archray ./my-project --lang typescript

# what did the last change actually do to the architecture?
# (the HTML report then opens changed files in a VS-style side-by-side diff)
archray . --changes HEAD --format html,changes

# git history: complex code that people keep touching
archray . --history 400

# CI: SARIF annotations, PR comment, quality gate
archray . --compare baseline.json --format sarif,pr --fail-on-new
```

Two commands are installed, `archray` and `software-architecture-analyzer`; they are the same
program. Outputs land next to each other: `archray-report.json`, `.html`, `.sarif`,
`-tour.md`, `-changes.md`, `-pr.md`.

### Web service

```bash
python -m uvicorn archray.server:app --reload
```

| Route | Purpose |
|---|---|
| `GET /` | Paste a repository URL |
| `GET /report?source=...` | The dashboard as HTML |
| `POST /api/analyze` | `{"source": "...", "language": "auto"}` → JSON report |
| `GET /docs` | OpenAPI explorer |


## Installation across toolchains

Analysing Python needs nothing beyond the standard library. Every other language needs a
Tree-sitter grammar, and that is where cross-platform installs actually go wrong: the PyPI
packages ship wheels for CPython on Windows, macOS and Linux, but an interpreter that is not
one of those — **MSYS2/UCRT64**, MinGW, Cygwin, musl, PyPy — matches no wheel and falls back
to compiling the grammar from C source.

Three things follow from that, and all three are implemented rather than documented away:

**Grammars are optional, individually.** `pip install "archray[java]"` is a valid install.
An environment that can only build some grammars installs only those.

```toml
[project.optional-dependencies]
java = ["tree-sitter>=0.23", "tree-sitter-java>=0.23"]
csharp = ["tree-sitter>=0.23", "tree-sitter-c-sharp>=0.23"]
# … one per language, plus `parsers` for all of them and `all` for everything
```

**A missing grammar costs only its own language.** In `auto` mode an unavailable grammar is
skipped, reported in the output and in the JSON under `repository.unsupported`, and the
remaining languages are analysed normally. Asking for that language explicitly still fails
loudly — silently analysing nothing would be worse than an error.

```
  ! java skipped (7 files): grammar not installed
    run `archray --doctor` for the exact install command
```

**`archray --doctor` diagnoses the machine.** It reports the interpreter, the platform tag,
whether wheels are expected, whether a C compiler is present, and which grammars actually
*import* (rather than merely appear installed — a wheel can install and still fail to load).
When something is missing it prints the commands for that environment specifically:

```
pacman -S --needed mingw-w64-ucrt-x86_64-python-pip mingw-w64-ucrt-x86_64-gcc \
                   mingw-w64-ucrt-x86_64-python-setuptools
# no wheels match an MSYS2 interpreter, so the grammars are compiled:
pip install tree-sitter tree-sitter-cpp tree-sitter-java
```

`ci/github-action.yml` exercises this rather than assuming it: a matrix job over
Ubuntu/Windows/macOS × Python 3.10/3.12, plus a dedicated **MSYS2/UCRT64** job that first
runs with no grammars at all — proving the degraded path works — and then compiles them from
source.

---

## Where it sits among similar tools

> **A note on the name:** this project started out as `ArchLens`, but that name is taken —
> [archlens/ArchLens](https://github.com/archlens/ArchLens) is published on PyPI and builds
> architecture views from lightweight specifications. Hence **ArchRay**; the repository keeps
> the descriptive name for discoverability.

| Capability | ArchRay | ArchLens | CodeScene | SonarQube |
|---|:---:|:---:|:---:|:---:|
| Dependency visualisation | ✅ | ✅ | ✅ | partial |
| SOLID violation detection | ✅ | ✖ | partial | partial |
| Design pattern detection | ✅ | ✖ | ✖ | ✖ |
| Code smells + complexity | ✅ | ✖ | ✅ | ✅ |
| Duplicate code | ✅ | ✖ | ✅ | ✅ |
| Change frequency (git) | ✅ | ✖ | ✅ | ✖ |
| Change coupling | ✅ | ✖ | ✅ | ✖ |
| Knowledge islands | ✅ | ✖ | ✅ | ✖ |
| Structural diff of a change | ✅ | partial (view diff) | ✖ | ✖ |
| Mixed-language projects | ✅ | ✅ | ✅ | ✅ |
| SARIF / Code Scanning | ✅ | ✖ | partial | ✅ |
| Architecture rule engine | ✖ | ✅ | ✅ | ✖ |
| IDE extension | ✖ | ✅ | ✅ | ✅ |

The `ArchLens` column refers to the separate project mentioned above, not to this one.

---

## The pipeline

### 1. Ingestion — `ingest.py`

`git clone --depth 1 --single-branch` (deeper only when `--history` or `--changes` needs it).
Build output, dependency folders, generated code and test files are filtered out.

**Language planning.** Every source file is assigned to exactly one language. Unambiguous
extensions decide which languages are present; `.h` then goes to C++ if any `.cpp` exists and
to C otherwise. A language is analysed if it holds at least a few files or a few percent of
the code, so a stray build script does not turn a Java project into a "Java + Python" one —
but a real TypeScript front-end next to a Java back-end is reported as both.

### 2. Parsing — `parsing.py` (Python) and `treesitter_frontend.py` (the rest)

The rule engine is language independent: each front-end fills the same `ModuleInfo` /
`ClassInfo` / `FunctionInfo` models, and the rules only ever see those.

| Language | Front-end | Notes |
|---|---|---|
| Python | `ast` (standard library) | No dependency, exact |
| Java | Tree-sitter | Module name from the `package` declaration; `instanceof`, `switch`, `this.x` |
| TypeScript / TSX | Tree-sitter | Arrow functions (`const f = () => {}`), `typeof`/`instanceof`, relative imports |
| C# | Tree-sitter | `namespace` feeds the module name; `is`/`as`/`typeof`, properties, bare field access |
| C++ | Tree-sitter | `.h` and `.cpp` merge into one module; `int A::f()` replaces the header declaration; pure virtual means interface |
| C | Tree-sitter | No classes: `struct`s (including anonymous `typedef`s) are data, functions live at module level; `#include` builds the graph |

**Cyclomatic complexity.** Start at 1, then +1 per decision node:

| Node | Contribution |
|---|---|
| `if`, `for`, `while`, `catch`, `assert`, ternary | +1 |
| `and` / `or` | operands − 1 |
| comprehension | 1 + its conditions |
| each `case` of a `switch`/`match` | +1 |

**Structural fingerprint.** Every function body is reduced to the shape of its AST with names
and literal values erased, hashed with blake2s. This drives both duplicate detection and the
structural diff below.

### 3. Indexing — `graph.py`

All classes go into a symbol table; imports are resolved to project modules. The graph is
built at two levels — **modules** and **classes**, where edges are labelled *inherits*,
*creates* or *uses*.

Edges do not come from `import` statements alone: inheritance, field types and object creation
are dependencies too. In Java two classes in the same package need no import, so an
import-only tool produces an almost empty graph there.

Per node: **fan-in**, **fan-out**, distinct **dependents** and instability
(`I = fan_out / (fan_in + fan_out)`). Cycles come from Tarjan's SCC algorithm, reported once
per cycle and anchored on its most depended-upon member.

### 4. Rules

**Code smells — `smells.py`, `duplication.py`**

| Rule | Threshold |
|---|---|
| God class | > 500 lines **and** > 20 methods |
| Large class | > 300 lines **or** > 15 methods |
| Long method | > 50 lines (> 120 becomes major) |
| Too many parameters | > 5 (excluding `self`/`this`) |
| Magic number | unnamed constants in conditions |
| Deep nesting | > 4 levels |
| High complexity | > 10 (major), > 20 (critical) |
| Duplicate code | ≥ 2 functions with the same fingerprint (≥ 28 nodes, ≥ 6 lines) |
| Unused private method | private/`_` method no method of the class calls |

Duplicate detection finds real things: a second copy of ISO8601 date formatting in
`google/gson`, matching stream wrappers in `pallets/click`.

**SOLID — `solid.py`**

- **SRP** — LCOM4. Methods are nodes; two methods are linked when they touch a common field or
  one calls the other. Union-find counts the connected components. More than one component
  means the class carries unrelated jobs. Constructors are excluded: they touch every field by
  definition and would glue every component together.
- **OCP** — ≥ 2 type checks, or an `if/elif`/`match` chain with ≥ 4 branches.
- **LSP** — a subclass cancelling working inherited behaviour with `NotImplementedError`, or
  narrowing a signature.
- **ISP** — an abstract type forcing more than 5 abstract methods on its implementers.
- **DIP** — a class method constructing a project-defined **concrete** class directly.
  Factories, builders, `create_*` methods, composition roots, data classes and exceptions are
  exempt, because creating concrete things is exactly their job.

**Design patterns — `patterns.py`**

| Pattern | Structural fingerprint |
|---|---|
| Singleton | class-level instance field + `__new__` reusing it + static accessor |
| Factory | a producer returning ≥ 2 concrete types with a common base |
| Builder | ≥ 2 chainable methods returning self + a terminal `build()` |
| Strategy | abstract interface + ≥ 2 implementations + a context class holding that type |
| Command | Strategy shape whose abstract methods are `execute`/`run`/`handle`/`undo` |
| Template Method | a concrete method of an abstract class calling ≥ 2 of its own abstract methods |
| Observer | subscribe + notify + a listener collection |
| Decorator | a class that both derives from `B` and wraps a `B` |
| Adapter | `*Adapter`/`*Wrapper` naming + wrapping a foreign type + conforming to an interface |

Each match carries its evidence and a confidence score, because pattern detection is a
heuristic and should say so.

### 5. Suppression and configuration

```python
total = price * 1.18          # archray: ignore[magic_number]
def legacy_handler(...):      # archray: ignore
```

```toml
[thresholds]
long_method_loc = 80
ignore_rules = ["magic_number"]
exclude_paths = ["generated/*", "vendor/*"]
```

The number of suppressed findings appears in the report footer — nothing disappears silently.
An unknown config key is an error rather than a typo nobody notices.

### 6. Structural change report — `changes.py`

```bash
archray . --changes HEAD          # working tree vs. last commit
archray . --changes main          # branch vs. main
```

Reviewing code you did not write is hard for a specific reason, and it has become the common
case now that assistants write so much of it: a text diff shows every line that moved and
buries the two or three facts that matter.

This compares two revisions **structurally**. Functions and classes are matched by qualified
name and compared by their structural fingerprint, so renaming a local variable is not a
change while a rewritten body is. The output answers:

- which functions were **added, rewritten or removed** — and by how much their complexity moved
- which classes gained or lost methods, or changed their base classes
- which **dependency edges are new** — the change most likely to go unnoticed in a text diff
- which findings appeared or were resolved

The revision is materialised with `git archive` into a temporary directory, so analysing it
never touches the working copy someone is editing.

```
What changed since HEAD
  2 new functions, 1 removed, 1 new class, 1 new dependency — score +0.1.
  ! `report_builder.InvoiceBuilder.in_currency` was removed
  · New dependency: `payments` → `infrastructure`
```

### 7. Change history — `history.py`

`--history 400` reads `git log --numstat` and extracts three things:

- **Change frequency** — refactoring priority is `complexity × how often it changes`. Complex
  code nobody touches is not where the money goes.
- **Change coupling** — files that keep being committed together. When no import connects
  them, that is coupling the dependency graph cannot see. Commits touching more than 60 files
  couple nothing; links below 45% or fewer than 4 shared commits are noise.
- **Knowledge islands** — files where one author wrote over 90% of the changes.

On `pallets/click`: `src/click/core.py` changed 74 times with a complexity of 623 — the
refactoring target by a wide margin — and it changes together with `parser.py` in 100% of
commits.

### 8. Scoring — `scoring.py`

Penalties saturate, so the first violations cost the most and a large project is not punished
for being large. Densities are normalised per 1000 lines of code.

```
severe    = 38 · d_severe / (d_severe + 70)      # critical + major
minor     = 12 · d_minor  / (d_minor  + 35)
complexity= min(16, over_threshold_ratio · 45 + max(0, avg − 4) · 3)
cycles    = min(14, cycle_count · 6 / √KLOC + ring_pressure · 8)

score = 100 − severe − minor − complexity − cycles     →  A ≥ 90, B ≥ 80, C ≥ 70, D ≥ 55, F
```

Calibration against real repositories:

| Repository | Languages | Lines | Score | Findings | Patterns | Cycles |
|---|---|---:|:---:|---:|---:|---:|
| `pmndrs/zustand` | TypeScript | 1 268 | **93.2 / A** | 3 | 0 | 0 |
| `fmtlib/fmt` | C++ (+Python) | 14 747 | **85.8 / B** | 147 | 2 | 1 |
| `serilog/serilog` | C# | 7 057 | **75.0 / C** | 135 | 17 | 1 |
| `pallets/click` | Python | 10 389 | **74.1 / C** | 168 | 8 | 2 |
| `google/gson` | Java | 12 410 | **70.8 / C** | 266 | 33 | 3 |
| `commonmark/cmark` | C (+Python) | 15 970 | **61.6 / D** | 208 | 0 | 2 |

### 9. Readability layer — `tour.py`, `diagrams.py`

A report's real job is not counting violations; it is answering the question a new reader
actually has: **where do I start?** A file tree answers a different question.

**Codebase tour** (`--format md`) derives four signals from the graph: *entry points* (nothing
depends on them), *foundations* (everything does), *reading order* (dependency depth, layer 0
standing on its own) and *what holds the design together* (widely used abstractions and
detected patterns). Folder roles are inferred from naming — `repository/` is data access,
`adapters/` talks to external systems.

**Mermaid diagrams** — packages, modules (grouped by folder, cycles red, problem modules
yellow) and classes (inheritance, creation and usage arrows, abstract types marked). Text is
the right format three times over: GitHub renders it, a human can read the source, and an
agent can consume or rewrite it without an image pipeline. Diagrams are capped at the 22 most
connected classes and 28 most central modules, because a two-hundred-box diagram teaches
nobody anything.

The diagram source is validated against Mermaid's own parser in the test suite. That caught a
silent bug: `graph` is a reserved word in Mermaid, and a module named `graph.py` broke the
entire diagram.

### 10. Source viewer — `sources.py`, `codediff.py`

A finding that says "line 412 of `core.py`" only helps someone who already has the repository
open. The report embeds the code itself, so it can be read on its own:

- **Solution Explorer** — the folder tree, with a language icon per file, a badge counting
  findings (coloured by the worst one) and a `±` marker on files this revision touched.
- **Editor pane** — Visual Studio 2019's dark theme, down to the palette: `#1E1E1E` surface,
  teal line numbers, `#569CD6` keywords with control flow in `#D8A0DF`, `#D69D85` strings,
  `#57A64A` comments and `#4EC9B0` types. Findings get a red gutter dot and a wavy underline
  on the offending line, with a bar of jump-to-line chips above the code.
- Every `file:line` link elsewhere in the report opens that line here; ctrl-click still goes
  to GitHub.

Embedding is budgeted — up to 1500 lines per file and 26 000 in total, files with findings
first — because a report is a document, not a copy of the repository. Large files are opened
lazily so page load stays fast.

### 11. Diff view — Visual Studio 2019 style

When a revision is given (`--changes HEAD`), a changed file opens in a **side-by-side diff**
built to look like the one in Visual Studio 2019 dark: two panes with their own line-number
gutters, removed lines on `#4B1818`, added lines on `#153D15`, and — the part that makes a
diff readable — **the changed words within a line highlighted in a stronger shade**
(`#7A2323` / `#2C5C2C`) rather than the whole line being repainted.

The word-level marking comes from a second `SequenceMatcher` pass over the tokens of each
replaced line pair, so `total = price * 2` → `total = price * 3` marks the `2` and the `3`
and nothing else.

`Code` / `Compare` switches between reading the file and diffing it; `Side by side` /
`Inline` switches the layout, as the IDE does. The same diffs are written into the Markdown
review sheet as `diff` fenced blocks, so a pull request comment carries the code too.

### 12. Dashboard — `ui/dashboard.html`

One self-contained file, no CDN, no dependencies, in a technical-drawing style:

- Sticky navigation bar with the score and jump links that follow the section you are reading
- The IDE-style source browser and diff view described above
- Title block and grade stamp; per-language breakdown for mixed projects
- **What changed** panel: counters, the highlights to read first, and a table of rewritten
  functions with complexity deltas
- Force-directed dependency graph written from scratch on canvas: drag, zoom, isolate
  neighbours, switch between **module and class view**, cycles-only filter
- **Change history** panels: refactoring targets, files that change together, knowledge islands
- **Folder map**: a squarified treemap in SVG — area is lines of code, colour is finding
  density, a red border means a dependency cycle
- Codebase tour panels and copyable Mermaid source
- Findings filtered by severity, kind and free text, each showing the offending lines with
  the exact line highlighted; clicking one opens it in the source viewer
- **Save as PDF** through a print stylesheet that turns the dark theme white, including the
  editor and diff panes — dark backgrounds waste ink, so on paper the diff reverts to the
  familiar pale red and green

### 13. CI integration — `sarif.py`, `pr_comment.py`, `ci/github-action.yml`

| Format | Purpose |
|---|---|
| `--format sarif` | GitHub Code Scanning / IDE problem panel — findings become inline annotations |
| `--format pr` | A short Markdown comment: score, delta, new findings, architecture view |
| `--format changes` | The structural review sheet described in section 6 |
| `--fail-under`, `--fail-on-new` | Quality gate |

SARIF results carry `partialFingerprints` that exclude line numbers, so moving code within a
file does not reopen the same finding. Severity maps to `error` / `warning` / `note`.

`ci/github-action.yml` is a ready workflow: it builds a baseline from the target branch,
diffs the pull request against it structurally, uploads SARIF, posts a sticky comment and
keeps the HTML report as an artifact.

---

### 14. Cross-language contracts — `bindings.py`

A dependency graph stops at the language boundary. When a C++ engine is called from C#
through P/Invoke, or from Python through `ctypes`, the two sides are bound by nothing but a
symbol name and an agreement about types — an agreement **no compiler on either side can
check**. Add a parameter to the native function and the managed declaration still builds,
still links, and corrupts the stack at run time.

ArchRay reads both sides out of the ASTs it already has:

| Side | What is extracted |
|---|---|
| Native (C/C++) | exported functions — `extern "C"`, `__declspec(dllexport)`, or a plain header declaration — with their real parameter *types*, pointers included |
| C# | `[DllImport]` + `static extern` declarations, honouring `EntryPoint` when the managed name differs from the symbol |
| Python | `ctypes` `argtypes` / `restype` assignments |

Each managed declaration is matched to its native symbol and checked against a marshalling
table (`string` may stand for `const char*`, `bool` for `int`, `IntPtr` for `void*`, and so
on). Unknown types — a custom struct — are left alone, because a false alarm here costs more
than a missed one. Every binding ends up **satisfied**, **mismatched** or **dangling**:

```
mismatch   engine_evaluate    managed: int engine_evaluate(string, int, double)
                              native:  int engine_evaluate(char*, int, double, int)
                              → arity: the managed declaration passes 3, the native takes 4
dangling   engine_undo_move   managed: int Undo(int)   [EntryPoint = "engine_undo_move"]
satisfied  engine_reset       void engine_reset()
```

With `--changes`, contracts are diffed as well, which is the point of the whole thing: a
one-parameter edit in C++ shows up as **"Cross-language contract broken: `engine_evaluate`"**
at the top of the change report, before anything else. `examples/demo_interop` is a working
C++/C# pair kept deliberately out of sync so the tests can assert exactly that.

## Tests

```bash
pytest -q     # 152 tests
```

`test_analyzer.py` covers the Python core (metric correctness, every rule family, every
pattern, report shape); `test_features.py` the language front-ends, source excerpts, class
graph and configuration; `test_quality.py` duplicate detection, dead code, suppression and the
findings diff; `test_visuals.py` diagrams and the tour; `test_integrations.py` git history,
SARIF and the PR comment; `test_multilang_and_changes.py` mixed-language projects and the
structural diff; `test_sources_and_diff.py` the embedded source, the file tree and the
line/word level diff; `test_bindings.py` the cross-language contracts, including a native
signature change that breaks a C# declaration.

`examples/` holds a deliberately flawed sample project per language (`demo_shop`, `demo_java`,
`demo_csharp`, `demo_cpp`, `demo_c`); the tests assert that each rule and pattern fires in each
language. History tests build a real git repository and change two files together on purpose
to prove change coupling is detected without any import between them.


## Explorer (optional)

```bash
pip install "archray[explore]"
streamlit run tools/streamlit_app.py -- --reports ./reports
```

This is an addition to the HTML report, not a replacement for it, and the distinction is
worth being explicit about. The report is *one self-contained file*: it survives being
attached to a CI run, emailed, opened offline and printed to PDF, and it describes exactly
one analysis. That is the right shape for a deliverable, and a server-backed app would be a
downgrade for it.

What a single file cannot do is compare many analyses. The explorer reads a folder of JSON
reports — a CI artifact directory, a series of nightly runs, every service in an organisation
— and answers questions that span them: which project carries the most debt per thousand
lines, which rules fire everywhere (usually a house-style decision to configure away rather
than a discovery), how one project's score moved between runs. Per project it offers filtered
findings, the coupling scatter, history hotspots, cross-language contracts and the code diff.

## Known limits

- No type inference. Symbol resolution is name and import based; two classes with the same
  name resolve to the caller's module first. This can occasionally misattribute a DIP or
  Strategy match.
- Pattern detection is structural, not semantic: a class is a Singleton because it has the
  *shape* of one. The confidence score exists to make that uncertainty visible.
- Dynamic behaviour (`getattr`, `exec`, metaclass tricks, reflection) is invisible to the
  dependency graph.
- Cross-language edges are resolved only where a contract is declared in code — P/Invoke,
  `ctypes`. A TypeScript front-end calling a Java endpoint over HTTP still appears as two
  independent subgraphs; nothing in either source states that they are connected.
- Binding checks read declarations, not build output. If the native library is produced by a
  different repository, the symbol shows up as `dangling` and nothing here can verify it.

## Roadmap

- [x] Tree-sitter front-ends for Java, TypeScript, C#, C++ and C
- [x] Class-level dependency graph
- [x] Duplicate (type-2 clone) detection
- [x] Diff mode, inline suppression and configuration files
- [x] Mermaid diagrams and the generated codebase tour
- [x] Git history: change frequency, change coupling, knowledge islands
- [x] SARIF output, PR comment and a ready GitHub Action
- [x] Mixed-language projects in a single report
- [x] Structural change report for reviewing generated code
- [x] IDE-style source browser and a Visual Studio 2019 dark diff view inside the report
- [x] Optional per-language grammars, graceful degradation and `archray --doctor`
- [x] Cross-language contract checking for P/Invoke and ctypes
- [x] Streamlit explorer for comparing many reports
- [ ] Architecture rule engine: `layer A must not depend on layer B` (ArchUnit / import-linter style)
- [ ] Go and Rust front-ends (the grammars exist; they need an entry in `SPECS`)
- [ ] `archray serve` subcommand so the web UI does not need a separate uvicorn invocation
- [ ] JNI and WASM import boundaries alongside P/Invoke and ctypes


---

## Repository layout

```
software-architecture-analyzer/
├── archray/                 the package: pipeline, rules, front-ends, dashboard template
│   └── ui/dashboard.html    the self-contained report template
├── examples/                a deliberately flawed sample project per language
├── tests/                   152 tests, one module per capability
├── tools/streamlit_app.py   optional explorer for comparing many reports
├── ci/github-action.yml     reference copy of the workflow
└── .github/workflows/       what GitHub actually runs
```



The CI badge above turns green after the first push, once
`.github/workflows/archray.yml` has run. The workflow needs no secrets: SARIF upload and the
pull-request comment both use the built-in `GITHUB_TOKEN`, and the permissions it needs are
declared in the file.

Two things are worth doing in the repository settings afterwards:

- **Code scanning** — the SARIF upload populates the Security tab; findings then appear as
  inline annotations on pull requests.
- **Topics** — `static-analysis`, `solid`, `design-patterns`, `code-smells`, `tree-sitter`,
  `architecture` make the project findable, since the repository name is descriptive rather
  than distinctive.

## License

MIT — see [LICENSE](https://github.com/miraccelikel/software-architecture-analyzer/blob/main/LICENSE).
