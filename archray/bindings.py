"""Cross-language call contracts.

A dependency graph stops at the language boundary. When a C++ engine is called
from C# through P/Invoke, or from Python through ctypes, the two sides are bound
by nothing but a symbol name and an agreement about types — an agreement the
compiler on neither side can check. Change a parameter in the native function and
the managed declaration still builds, still links, and corrupts the stack at run
time.

This module reads both sides out of the ASTs we already have and checks that they
still agree:

* the **native side** — exported C/C++ functions (`extern "C"`, `__declspec(dllexport)`,
  or a plain function in a header),
* the **managed side** — C# `[DllImport] static extern` declarations and Python
  `ctypes` `argtypes`/`restype` assignments,
* a **marshalling table** that says which native type a managed type may stand for.

The result is a set of bindings, each either satisfied, mismatched, or dangling.
Comparing two revisions then answers the question that matters during review: did
this change break a contract that crosses a language boundary?
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import Finding, ModuleInfo

# --------------------------------------------------------------------------- #
# What a managed type is allowed to mean on the native side. Deliberately
# permissive: the goal is to catch changes that are certainly wrong, not to
# adjudicate every marshalling subtlety.
MARSHALLING: dict[str, set[str]] = {
    "int": {"int", "int32_t", "long", "signed int"},
    "uint": {"unsigned int", "uint32_t", "unsigned"},
    "long": {"int64_t", "long long", "long"},
    "ulong": {"uint64_t", "unsigned long long", "unsigned long"},
    "short": {"short", "int16_t"},
    "byte": {"unsigned char", "uint8_t", "char"},
    "sbyte": {"signed char", "int8_t", "char"},
    "bool": {"bool", "int", "_Bool", "BOOL"},
    "char": {"char", "wchar_t"},
    "float": {"float"},
    "double": {"double"},
    "void": {"void"},
    "string": {"const char*", "char*", "const wchar_t*", "wchar_t*", "LPCSTR", "LPCWSTR"},
    "intptr": {"void*", "handle", "int*", "size_t"},
    "stringbuilder": {"char*", "wchar_t*"},
}
CSHARP_ALIASES = {
    "int32": "int", "uint32": "uint", "int64": "long", "uint64": "ulong",
    "int16": "short", "uint16": "ushort", "single": "float", "boolean": "bool",
    "intptr": "intptr", "uintptr": "intptr", "safehandle": "intptr",
}
CTYPES_MAP = {
    "c_int": "int", "c_uint": "uint", "c_long": "long", "c_ulong": "ulong",
    "c_short": "short", "c_byte": "sbyte", "c_ubyte": "byte", "c_bool": "bool",
    "c_float": "float", "c_double": "double", "c_char_p": "string",
    "c_wchar_p": "string", "c_void_p": "intptr", "c_size_t": "intptr",
    "c_char": "char", "c_int32": "int", "c_int64": "long", "c_uint32": "uint",
    "c_uint64": "ulong", "none": "void",
}

DLLIMPORT = re.compile(
    r"\[\s*DllImport\s*\(\s*(?P<library>[^)]*?)\s*\)\s*\]\s*"
    r"(?P<modifiers>(?:public|private|internal|protected|static|extern|unsafe|\s)+)"
    r"(?P<returns>[\w\.\<\>\[\]]+)\s+(?P<name>\w+)\s*\((?P<params>[^)]*)\)",
    re.DOTALL,
)
ENTRY_POINT = re.compile(r"EntryPoint\s*=\s*\"(?P<entry>[^\"]+)\"")
LIBRARY_NAME = re.compile(r"^\s*\"?(?P<library>[^\",]+)\"?")
CTYPES_ARGTYPES = re.compile(
    r"(?P<handle>\w+)\.(?P<symbol>\w+)\.argtypes\s*=\s*\[(?P<args>[^\]]*)\]")
CTYPES_RESTYPE = re.compile(r"(?P<handle>\w+)\.(?P<symbol>\w+)\.restype\s*=\s*(?P<value>[\w\.]+)")
EXPORT_MARKERS = ("extern \"c\"", "__declspec(dllexport)", "dllexport", "extern_c",
                  "api_export", "public_api")


@dataclass
class NativeExport:
    symbol: str
    returns: str
    params: list[str]
    file: str
    line: int
    explicit: bool = False          # marked exported rather than merely public

    def signature(self) -> str:
        return f"{self.returns} {self.symbol}({', '.join(self.params) or 'void'})"


@dataclass
class ManagedImport:
    symbol: str                     # the native symbol it expects to find
    name: str                       # the name on the managed side
    library: str
    returns: str
    params: list[str]
    file: str
    line: int
    language: str

    def signature(self) -> str:
        return f"{self.returns} {self.name}({', '.join(self.params)})"


@dataclass
class Binding:
    managed: ManagedImport
    native: NativeExport | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.native is None:
            return "dangling"
        return "mismatch" if self.problems else "satisfied"

    def to_dict(self) -> dict:
        return {
            "symbol": self.managed.symbol,
            "status": self.status,
            "library": self.managed.library,
            "managed": {"language": self.managed.language, "name": self.managed.name,
                        "file": self.managed.file, "line": self.managed.line,
                        "signature": self.managed.signature()},
            "native": ({"file": self.native.file, "line": self.native.line,
                        "signature": self.native.signature()} if self.native else None),
            "problems": self.problems,
        }


# --------------------------------------------------------------------------- #
def _normalise_native(text: str) -> str:
    text = re.sub(r"\b(const|volatile|struct|unsigned\s+char\b)", lambda m: m.group(0), text)
    text = text.replace("const ", "").strip()
    text = re.sub(r"\s*\*\s*", "*", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def _normalise_managed(text: str) -> str:
    text = re.sub(r"\[\s*(In|Out|MarshalAs)[^\]]*\]", " ", text)
    text = re.sub(r"\b(ref|out|in|params|readonly)\b", " ", text)
    text = text.replace("[]", "*").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return CSHARP_ALIASES.get(text, text)


def compatible(managed_type: str, native_type: str) -> bool:
    """Whether a managed declaration may stand for this native type."""
    managed = _normalise_managed(managed_type)
    native = _normalise_native(native_type)
    if not managed or not native:
        return True                                   # nothing to disagree about

    if managed.endswith("*") or native.endswith("*"):
        # a pointer on either side is satisfied by a pointer or a handle
        return (managed.endswith("*") or managed in ("intptr", "string", "stringbuilder")
                or native.endswith("*"))
    allowed = MARSHALLING.get(managed)
    if allowed is None:
        return True                                   # unknown type: do not guess
    return any(_normalise_native(option) == native for option in allowed)


# --------------------------------------------------------------------------- #
def native_exports(modules: list[ModuleInfo]) -> dict[str, NativeExport]:
    """Functions a C or C++ translation unit offers to the outside world."""
    exports: dict[str, NativeExport] = {}
    for module in modules:
        if module.language not in ("c", "cpp"):
            continue
        sources = {module.path: module.source_lines, **module.extra_sources}

        for func in module.all_functions:
            lines = sources.get(func.file) or module.source_lines
            context = " ".join(lines[max(func.line - 4, 0):func.line]).lower()
            explicit = any(marker in context for marker in EXPORT_MARKERS)
            declaration = lines[func.line - 1] if 0 < func.line <= len(lines) else ""
            explicit = explicit or any(marker in declaration.lower()
                                       for marker in EXPORT_MARKERS)

            existing = exports.get(func.name)
            if existing is not None and existing.explicit and not explicit:
                continue
            exports[func.name] = NativeExport(
                symbol=func.name,
                returns=func.annotations.get("->", ""),
                params=func.param_types or ([""] * len(func.params)),
                file=func.file, line=func.line, explicit=explicit,
            )
    return exports


def managed_imports(modules: list[ModuleInfo]) -> list[ManagedImport]:
    """Declarations that reach across to a native library."""
    found: list[ManagedImport] = []
    for module in modules:
        sources = {module.path: module.source_lines, **module.extra_sources}
        for path, lines in sources.items():
            text = "\n".join(lines)
            if module.language == "csharp":
                found.extend(_csharp_imports(text, path))
            elif module.language == "python":
                found.extend(_ctypes_imports(text, path))
    return found


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _csharp_imports(text: str, path: str) -> list[ManagedImport]:
    out: list[ManagedImport] = []
    for match in DLLIMPORT.finditer(text):
        attribute = match.group("library")
        library = LIBRARY_NAME.match(attribute)
        entry = ENTRY_POINT.search(attribute)
        name = match.group("name")
        params = [part.strip() for part in match.group("params").split(",") if part.strip()]
        out.append(ManagedImport(
            symbol=entry.group("entry") if entry else name,
            name=name,
            library=(library.group("library").strip() if library else "").strip('"'),
            returns=match.group("returns"),
            params=[re.sub(r"\s+\w+$", "", part).strip() for part in params],
            file=path, line=_line_of(text, match.start()), language="csharp",
        ))
    return out


def _ctypes_imports(text: str, path: str) -> list[ManagedImport]:
    signatures: dict[str, dict] = {}
    for match in CTYPES_ARGTYPES.finditer(text):
        symbol = match.group("symbol")
        args = [a.strip() for a in match.group("args").split(",") if a.strip()]
        signatures.setdefault(symbol, {}).update({
            "params": [CTYPES_MAP.get(a.split(".")[-1].lower(), a.split(".")[-1])
                       for a in args],
            "line": _line_of(text, match.start()),
            "handle": match.group("handle"),
        })
    for match in CTYPES_RESTYPE.finditer(text):
        symbol = match.group("symbol")
        value = match.group("value").split(".")[-1].lower()
        signatures.setdefault(symbol, {}).setdefault("line", _line_of(text, match.start()))
        signatures[symbol]["returns"] = CTYPES_MAP.get(value, value)

    return [
        ManagedImport(symbol=symbol, name=symbol,
                      library=data.get("handle", ""),
                      returns=data.get("returns", ""),
                      params=data.get("params", []),
                      file=path, line=data.get("line", 1), language="python")
        for symbol, data in signatures.items()
        if "params" in data or "returns" in data
    ]


# --------------------------------------------------------------------------- #
def resolve(modules: list[ModuleInfo]) -> list[Binding]:
    """Match every managed declaration to the native symbol it expects."""
    exports = native_exports(modules)
    bindings: list[Binding] = []

    for managed in managed_imports(modules):
        native = exports.get(managed.symbol)
        binding = Binding(managed=managed, native=native)
        if native is not None:
            binding.problems = _disagreements(managed, native)
        bindings.append(binding)

    bindings.sort(key=lambda b: (b.status == "satisfied", b.managed.file, b.managed.line))
    return bindings


def _disagreements(managed: ManagedImport, native: NativeExport) -> list[str]:
    problems: list[str] = []
    if len(managed.params) != len(native.params):
        problems.append(
            f"arity: the managed declaration passes {len(managed.params)} arguments, "
            f"the native function takes {len(native.params)}")

    for index, (left, right) in enumerate(zip(managed.params, native.params), start=1):
        if not compatible(left, right):
            problems.append(
                f"parameter {index}: `{left.strip()}` cannot marshal to `{right.strip()}`")

    if managed.returns and native.returns and not compatible(managed.returns, native.returns):
        problems.append(
            f"return type: `{managed.returns}` cannot marshal to `{native.returns}`")
    return problems


def findings(bindings: list[Binding]) -> list[Finding]:
    """One finding per broken contract; satisfied bindings stay quiet."""
    out: list[Finding] = []
    for binding in bindings:
        if binding.status == "satisfied":
            continue
        managed = binding.managed

        if binding.status == "dangling":
            out.append(Finding(
                kind="binding", rule="unresolved_native_symbol", severity="major",
                title="Native symbol not found in this repository",
                message=(f"`{managed.name}` binds to the native symbol `{managed.symbol}` in "
                         f"`{managed.library or 'an external library'}`, but no exported "
                         f"function with that name exists in the analysed sources. Either the "
                         f"library is built elsewhere — in which case nothing here can verify "
                         f"the contract — or the symbol was renamed and this call will fail "
                         f"at load time, not at compile time."),
                file=managed.file, line=managed.line, symbol=managed.name,
                metrics={"symbol": managed.symbol, "library": managed.library,
                         "language": managed.language},
            ))
            continue

        out.append(Finding(
            kind="binding", rule="binding_signature_mismatch", severity="critical",
            title="Cross-language signature mismatch",
            message=(f"`{managed.name}` ({managed.language}) declares "
                     f"`{managed.signature()}` but the native side defines "
                     f"`{binding.native.signature()}` "
                     f"({binding.native.file}:{binding.native.line}). "
                     + " · ".join(binding.problems)
                     + " Neither compiler can see this: the mismatch surfaces as memory "
                       "corruption or a wrong result at run time."),
            file=managed.file, line=managed.line, symbol=managed.name,
            metrics={"symbol": managed.symbol,
                     "native": f"{binding.native.file}:{binding.native.line}",
                     "problems": binding.problems},
        ))
    return out


def summarise(bindings: list[Binding]) -> dict:
    if not bindings:
        return {}
    counts = {"satisfied": 0, "mismatch": 0, "dangling": 0}
    for binding in bindings:
        counts[binding.status] += 1
    languages = sorted({b.managed.language for b in bindings})
    return {
        "total": len(bindings),
        "counts": counts,
        "languages": languages,
        "bindings": [b.to_dict() for b in bindings[:40]],
    }


# --------------------------------------------------------------------------- #
def compare(previous: dict, current: dict) -> dict:
    """Which contracts this revision broke, fixed or introduced."""
    def index(report: dict) -> dict[str, dict]:
        payload = (report.get("bindings") or {}).get("bindings") or []
        return {item["symbol"] + "|" + item["managed"]["name"]: item for item in payload}

    before, after = index(previous), index(current)
    broken, fixed, added, removed = [], [], [], []

    for key, item in after.items():
        was = before.get(key)
        if was is None:
            added.append(item)
        elif was["status"] == "satisfied" and item["status"] != "satisfied":
            broken.append(item)
        elif was["status"] != "satisfied" and item["status"] == "satisfied":
            fixed.append(item)

    for key, item in before.items():
        if key not in after:
            removed.append(item)

    return {
        "broken": broken, "fixed": fixed, "added": added, "removed": removed,
        "verdict": _binding_verdict(broken, fixed, added, removed),
    }


def _binding_verdict(broken, fixed, added, removed) -> str:
    if broken:
        first = broken[0]
        return (f"{len(broken)} cross-language contract"
                f"{'s' if len(broken) > 1 else ''} broken by this change — "
                f"starting with `{first['symbol']}`.")
    if fixed and not added and not removed:
        return f"{len(fixed)} cross-language contracts repaired."
    if added or removed:
        return (f"Bindings changed: {len(added)} added, {len(removed)} removed, "
                f"none broken.")
    return "No cross-language contract changed."
