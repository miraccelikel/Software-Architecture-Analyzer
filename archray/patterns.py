"""Pattern matcher — looks for the structural fingerprint of GoF patterns."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict

from .config import Thresholds
from .graph import SymbolTable
from .models import ClassInfo, Finding, FunctionInfo, ModuleInfo

COMMAND_VERBS = {"execute", "run", "handle", "undo", "redo", "perform", "call", "do"}
SUBSCRIBE_VERBS = ("subscribe", "attach", "register", "add_observer", "add_listener",
                   "add_subscriber", "on", "connect")
NOTIFY_VERBS = ("notify", "publish", "emit", "fire", "broadcast", "dispatch")
BUILD_VERBS = ("build", "get_result", "to_dict", "create", "compile", "assemble")
CREATION_PREFIXES = ("create", "make", "build", "new_", "from_", "get_", "of_", "produce")


@dataclass
class PatternMatch:
    pattern: str
    confidence: float
    file: str
    line: int
    participants: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data["confidence"] = round(self.confidence, 2)
        return data


def _init_of(cls: ClassInfo) -> FunctionInfo | None:
    for method in cls.methods:
        if method.name == "__init__":
            return method
    return None


def _method_named(cls: ClassInfo, names: tuple[str, ...]) -> FunctionInfo | None:
    for method in cls.methods:
        lowered = method.name.lower()
        if any(lowered == n or lowered.startswith(n) for n in names):
            return method
    return None


# --------------------------------------------------------------------------- #
# Creational
# --------------------------------------------------------------------------- #
def detect_singleton(cls: ClassInfo) -> PatternMatch | None:
    evidence: list[str] = []
    instance_attrs = [name for name in cls.class_attrs
                      if name.lower().lstrip("_").startswith("instance")
                      or name.lower().endswith("_instance")]
    if instance_attrs:
        evidence.append(f"class-level instance field: {instance_attrs[0]}")

    new_method = next((m for m in cls.methods if m.name == "__new__"), None)
    if new_method and any(a.lower().lstrip("_").startswith("instance")
                          for a in new_method.self_attrs | set(cls.class_attrs)):
        evidence.append("__new__ reuses the stored instance")
    elif new_method:
        evidence.append("custom __new__")

    accessor = next((m for m in cls.methods
                     if m.name.lower() in ("get_instance", "getinstance", "instance", "current")
                     and (m.is_classmethod or m.is_static)), None)
    if accessor:
        evidence.append(f"static accessor: {accessor.name}()")

    if any("singleton" in d.lower() for d in cls.decorators):
        evidence.append("singleton decorator")
    if "singleton" in cls.name.lower():
        evidence.append("naming: *Singleton")

    if len(evidence) < 2:
        return None
    return PatternMatch(
        pattern="Singleton", confidence=min(0.45 + 0.2 * len(evidence), 0.98),
        file=cls.file, line=cls.line, participants=[cls.name], evidence=evidence,
        note="A guaranteed single instance is global state, which makes tests harder to isolate.",
    )


def detect_factory(cls: ClassInfo | None, func: FunctionInfo,
                   symbols: SymbolTable, module: ModuleInfo) -> PatternMatch | None:
    created = {name.split(".")[-1] for name, _line in func.instantiations}
    project_created = [n for n in created if symbols.lookup(n, module.module)]
    if len(project_created) < 2:
        return None

    resolved = [symbols.lookup(n, module.module) for n in project_created]
    bases: dict[str, int] = {}
    for target in resolved:
        if target is None:
            continue
        for base in target.bases:
            simple = base.split("[")[0].split(".")[-1]
            bases[simple] = bases.get(simple, 0) + 1
    shared = [base for base, count in bases.items() if count >= 2]

    name_signal = (any(func.name.lower().startswith(p) for p in CREATION_PREFIXES)
                   or "factory" in func.name.lower()
                   or (cls is not None and "factory" in cls.name.lower()))
    if not shared and not name_signal:
        return None

    confidence = 0.5 + (0.25 if shared else 0.0) + (0.2 if name_signal else 0.0)
    evidence = [f"creates {len(project_created)} different concrete types: "
                f"{', '.join(sorted(project_created)[:5])}"]
    if shared:
        evidence.append(f"shared base type: {shared[0]}")
    if func.branch_chains:
        evidence.append("creation branches on a parameter")

    owner = f"{cls.name}.{func.name}" if cls else func.name
    return PatternMatch(
        pattern="Factory" if shared else "Factory (likely)",
        confidence=min(confidence, 0.95), file=func.file, line=func.line,
        participants=[owner, *sorted(project_created)[:5]], evidence=evidence,
        note="Object creation is centralised in one place, which helps with DIP.",
    )


def detect_builder(cls: ClassInfo) -> PatternMatch | None:
    fluent = [m.name for m in cls.methods if m.returns_self and m.name != "__init__"]
    terminal = _method_named(cls, BUILD_VERBS)
    if len(fluent) < 2 or terminal is None:
        return None
    confidence = 0.6 + (0.25 if "builder" in cls.name.lower() else 0.0) + min(len(fluent), 4) * 0.03
    return PatternMatch(
        pattern="Builder", confidence=min(confidence, 0.95), file=cls.file, line=cls.line,
        participants=[cls.name],
        evidence=[f"{len(fluent)} chainable methods returning self: "
                  f"{', '.join(fluent[:4])}", f"terminal step: {terminal.name}()"],
    )


# --------------------------------------------------------------------------- #
# Behavioural / structural
# --------------------------------------------------------------------------- #
def detect_strategy_family(base: ClassInfo, symbols: SymbolTable,
                           modules: list[ModuleInfo],
                           thresholds: Thresholds) -> PatternMatch | None:
    if not base.is_abstract:
        return None
    abstract_names = [m.name for m in base.abstract_methods]
    if not abstract_names or len(abstract_names) > 4:
        return None
    implementations = symbols.implementations_of(base.name)
    if len(implementations) < thresholds.strategy_min_implementations:
        return None

    holders = _holders_of(base.name, modules)
    is_command = bool({n.lower() for n in abstract_names} & COMMAND_VERBS)
    is_template = any(not m.is_abstract and
                      len(m.self_calls & {a.name for a in base.abstract_methods}) >= 2
                      for m in base.methods)

    if is_template:
        pattern = "Template Method"
        note = "The base class owns the skeleton; subclasses fill in the steps."
    elif is_command:
        pattern = "Command"
        note = "Operations are objects, which suits queueing and undo."
    else:
        pattern = "Strategy" if holders else "Strategy (likely)"
        note = ("A family of algorithms behind one interface: adding behaviour does not "
                "require changing existing code (OCP).")

    confidence = 0.55 + min(len(implementations), 4) * 0.06 + (0.18 if holders else 0.0)
    evidence = [f"abstract interface: {base.name}({', '.join(abstract_names[:3])})",
                f"{len(implementations)} concrete implementations: "
                f"{', '.join(c.name for c in implementations[:5])}"]
    if holders:
        evidence.append(f"context class: {', '.join(holders[:3])}")

    return PatternMatch(
        pattern=pattern, confidence=min(confidence, 0.96), file=base.file, line=base.line,
        participants=[base.name, *[c.name for c in implementations[:6]]],
        evidence=evidence, note=note,
    )


def _holders_of(base_name: str, modules: list[ModuleInfo]) -> list[str]:
    """Classes that keep a reference typed as the abstract base."""
    holders: list[str] = []
    for module in modules:
        for cls in module.classes:
            if cls.name == base_name:
                continue
            annotations = {v for m in cls.methods for v in m.annotations.values()}
            annotations |= set(cls.class_attrs.values())
            if any(base_name == a.split("[")[-1].strip("] ").split(".")[-1] or base_name in a
                   for a in annotations):
                holders.append(cls.name)
    return holders


def detect_observer(cls: ClassInfo) -> PatternMatch | None:
    subscribe = _method_named(cls, SUBSCRIBE_VERBS)
    notify = _method_named(cls, NOTIFY_VERBS)
    if not subscribe or not notify:
        return None
    collections = [a for a in cls.instance_attrs
                   if any(k in a.lower() for k in ("observer", "listener", "subscriber",
                                                   "handler", "callback", "_s"))]
    confidence = 0.55 + (0.2 if collections else 0.0)
    return PatternMatch(
        pattern="Observer", confidence=min(confidence + 0.1, 0.95), file=cls.file, line=cls.line,
        participants=[cls.name],
        evidence=[f"registration: {subscribe.name}()", f"broadcast: {notify.name}()",
                  *([f"listener collection: {collections[0]}"] if collections else [])],
    )


def detect_decorator(cls: ClassInfo, symbols: SymbolTable) -> PatternMatch | None:
    init = _init_of(cls)
    if init is None or not cls.bases:
        return None
    base_names = {b.split("[")[0].split(".")[-1] for b in cls.bases}
    wrapped = [value.split("[")[0].split(".")[-1] for key, value in init.annotations.items()
               if key != "->"]
    shared = base_names & set(wrapped)
    if not shared:
        return None
    base = symbols.lookup(next(iter(shared)), cls.module)
    confidence = 0.7 + (0.15 if base and base.is_abstract else 0.0)
    return PatternMatch(
        pattern="Decorator", confidence=min(confidence, 0.95), file=cls.file, line=cls.line,
        participants=[cls.name, next(iter(shared))],
        evidence=[f"`{cls.name}` both derives from `{next(iter(shared))}` and wraps an "
                  f"object of that same type"],
        note="Behaviour is added at runtime by wrapping rather than by inheritance.",
    )


def detect_adapter(cls: ClassInfo, symbols: SymbolTable) -> PatternMatch | None:
    name = cls.name.lower()
    if not (name.endswith("adapter") or name.endswith("wrapper")):
        return None
    init = _init_of(cls)
    wrapped = [v for k, v in (init.annotations.items() if init else []) if k != "->"]
    confidence = 0.55 + (0.2 if cls.bases else 0.0) + (0.15 if wrapped else 0.0)
    return PatternMatch(
        pattern="Adapter", confidence=min(confidence, 0.9), file=cls.file, line=cls.line,
        participants=[cls.name, *wrapped[:2]],
        evidence=["naming convention: *Adapter/*Wrapper",
                  *([f"wrapped type: {wrapped[0]}"] if wrapped else []),
                  *([f"target interface: {cls.bases[0]}"] if cls.bases else [])],
    )


# --------------------------------------------------------------------------- #
def run(modules: list[ModuleInfo], symbols: SymbolTable,
        thresholds: Thresholds) -> tuple[list[PatternMatch], list[Finding]]:
    matches: list[PatternMatch] = []
    findings: list[Finding] = []

    for module in modules:
        for func in module.functions:
            match = detect_factory(None, func, symbols, module)
            if match:
                matches.append(match)

        for cls in module.classes:
            for detector in (detect_singleton, detect_builder, detect_observer):
                match = detector(cls)
                if match:
                    matches.append(match)
            for detector in (detect_decorator, detect_adapter):
                match = detector(cls, symbols)
                if match:
                    matches.append(match)
            family = detect_strategy_family(cls, symbols, modules, thresholds)
            if family:
                matches.append(family)
            for method in cls.methods:
                match = detect_factory(cls, method, symbols, module)
                if match:
                    matches.append(match)

    for match in matches:
        if match.pattern == "Singleton" and match.confidence >= 0.7:
            findings.append(Finding(
                kind="pattern", rule="singleton_global_state", severity="info",
                title="Singleton in use",
                message=("A Singleton was detected. Even when implemented correctly it is "
                         "global state, which is harder to test than an injected dependency "
                         "— make sure it is a deliberate choice."),
                file=match.file, line=match.line, symbol=match.participants[0],
                metrics={"confidence": round(match.confidence, 2)},
            ))

    matches.sort(key=lambda m: (-m.confidence, m.pattern))
    return matches, findings
