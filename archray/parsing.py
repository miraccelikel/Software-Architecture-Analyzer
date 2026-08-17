"""Parsing phase: turn source files into ModuleInfo / ClassInfo / FunctionInfo.

The Python front-end uses the standard library `ast` module, which gives an
exact syntax tree without any external grammar. The rest of the pipeline only
talks to the models in `archray.models`, so a Tree-sitter front-end for other
languages can be plugged in here without touching the rule engine.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Iterator

from .models import ClassInfo, FunctionInfo, ModuleInfo

NESTING_NODES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try)
SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
ALLOWED_NUMBERS = {0, 1, 2, -1, -2, 10, 100, 1000, 0.0, 1.0, 0.5}
ABSTRACT_BASES = {"ABC", "ABCMeta", "Protocol", "abc.ABC", "typing.Protocol", "Generic"}


def _walk_scope(node: ast.AST, depth: int = 0) -> Iterator[tuple[ast.AST, int]]:
    """Walk a scope without descending into nested functions/classes."""
    for child in ast.iter_child_nodes(node):
        yield child, depth
        if isinstance(child, SCOPE_NODES):
            continue
        next_depth = depth + 1 if isinstance(child, NESTING_NODES) else depth
        yield from _walk_scope(child, next_depth)


def structural_fingerprint(node: ast.AST) -> tuple[str, int]:
    """Hash the *shape* of a function body, ignoring names and literal values.

    Two functions that differ only in identifiers and constants — the classic
    copy-paste-and-rename — produce the same fingerprint.
    """
    shape: list[str] = []
    for child in ast.walk(node):
        if child is node:
            continue
        name = type(child).__name__
        if name in ("Load", "Store", "Del", "arguments", "alias", "keyword"):
            continue
        if name == "Constant":
            shape.append(type(child.value).__name__)   # 3 == 7, but 3 != "x"
        elif name in ("Name", "Attribute", "arg"):
            shape.append("Ref")
        else:
            shape.append(name)
    digest = hashlib.blake2s("|".join(shape).encode(), digest_size=8).hexdigest()
    return digest, len(shape)


def _name_of(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - unparse is total on valid trees
        return ""


def _decorator_names(node: ast.AST) -> list[str]:
    return [_name_of(d) for d in getattr(node, "decorator_list", [])]


def _elif_chain_length(node: ast.If) -> int:
    """Number of branches in an if/elif/.../else chain."""
    count = 1
    current = node
    while current.orelse:
        if len(current.orelse) == 1 and isinstance(current.orelse[0], ast.If):
            count += 1
            current = current.orelse[0]
        else:
            count += 1
            break
    return count


class FunctionParser:
    """Collect every metric we need from a single function body."""

    def __init__(self, node: ast.AST, file: str, class_name: str = "",
                 qual_prefix: str = "") -> None:
        self.node = node
        self.file = file
        self.class_name = class_name
        self.qual_prefix = qual_prefix

    def parse(self) -> FunctionInfo:
        node = self.node
        args = node.args
        params = [a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)]
        if args.vararg:
            params.append("*" + args.vararg.arg)
        if args.kwarg:
            params.append("**" + args.kwarg.arg)

        decorators = _decorator_names(node)
        is_method = bool(self.class_name)
        visible_params = [p for p in params if p not in ("self", "cls")]

        end_line = getattr(node, "end_lineno", node.lineno) or node.lineno
        qualname = f"{self.qual_prefix}{node.name}" if self.qual_prefix else node.name

        info = FunctionInfo(
            name=node.name,
            qualname=qualname,
            file=self.file,
            line=node.lineno,
            end_line=end_line,
            loc=end_line - node.lineno + 1,
            params=visible_params,
            is_method=is_method,
            class_name=self.class_name,
            decorators=decorators,
            is_abstract=any("abstractmethod" in d for d in decorators),
            is_static=any(d.endswith("staticmethod") for d in decorators),
            is_classmethod=any(d.endswith("classmethod") for d in decorators),
            is_property=any(d.endswith("property") for d in decorators),
        )

        for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
            if arg.annotation is not None:
                info.annotations[arg.arg] = _name_of(arg.annotation)
        if node.returns is not None:
            info.annotations["->"] = _name_of(node.returns)

        complexity = 1
        max_nesting = 0
        scanners = (self._scan_branching, self._scan_calls, self._scan_self_usage,
                    self._scan_exits)

        for child, depth in _walk_scope(node):
            if isinstance(child, ast.stmt):
                max_nesting = max(max_nesting, depth)
            complexity += self._complexity_delta(child)
            for scan in scanners:
                scan(child, info)

        info.complexity = complexity
        info.max_nesting = max_nesting
        info.fingerprint, info.shape_size = structural_fingerprint(node)
        return info

    # -- one concern per scanner ------------------------------------------ #
    @staticmethod
    def _complexity_delta(node: ast.AST) -> int:
        """How many independent execution paths this node introduces."""
        if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While,
                             ast.ExceptHandler, ast.Assert, ast.IfExp)):
            return 1
        if isinstance(node, ast.BoolOp):
            return len(node.values) - 1
        if isinstance(node, ast.comprehension):
            return 1 + len(node.ifs)
        if hasattr(ast, "match_case") and isinstance(node, ast.match_case):
            return 1
        return 0

    def _scan_branching(self, node: ast.AST, info: FunctionInfo) -> None:
        """if/elif chains, match blocks and the magic numbers inside them."""
        if isinstance(node, ast.If):
            branches = _elif_chain_length(node)
            if branches >= 3:
                info.branch_chains.append((node.lineno, branches))
            info.magic_numbers.extend(self._magic_numbers(node.test))
        elif hasattr(ast, "Match") and isinstance(node, ast.Match):
            info.branch_chains.append((node.lineno, len(node.cases)))
        elif isinstance(node, ast.Compare):
            for operand in (node.left, *node.comparators):
                if isinstance(operand, ast.Call) and _name_of(operand.func) == "type":
                    info.type_checks.append((node.lineno, _name_of(node)[:60]))
                    break

    @staticmethod
    def _scan_calls(node: ast.AST, info: FunctionInfo) -> None:
        """Type interrogation and object construction."""
        if not isinstance(node, ast.Call):
            return
        func_name = _name_of(node.func)
        if func_name in ("isinstance", "issubclass"):
            target = _name_of(node.args[1]) if len(node.args) > 1 else func_name
            info.type_checks.append((node.lineno, target))
        elif func_name and func_name.rsplit(".", 1)[-1][:1].isupper():
            info.instantiations.append((func_name, node.lineno))

    @staticmethod
    def _scan_self_usage(node: ast.AST, info: FunctionInfo) -> None:
        """Which fields the method touches and which siblings it calls (LCOM4)."""
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            owner = node.func.value
            if isinstance(owner, ast.Name) and owner.id == "self":
                info.self_calls.add(node.func.attr)
                info.self_attrs.discard(node.func.attr)
                return
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "self" and node.attr not in info.self_calls:
                info.self_attrs.add(node.attr)

    @staticmethod
    def _scan_exits(node: ast.AST, info: FunctionInfo) -> None:
        """Fluent returns and refused contracts."""
        if isinstance(node, ast.Return):
            if isinstance(node.value, ast.Name) and node.value.id == "self":
                info.returns_self = True
            elif isinstance(node.value, ast.Call):
                called = _name_of(node.value.func).rsplit(".", 1)[-1]
                if called[:1].isupper():
                    info.returns_types.add(called)
        elif isinstance(node, ast.Raise) and node.exc is not None:
            if "NotImplementedError" in _name_of(node.exc):
                info.raises_not_implemented = True

    @staticmethod
    def _magic_numbers(test: ast.AST) -> list[tuple[int, object]]:
        """Unnamed numeric literals used inside a condition."""
        found: list[tuple[int, object]] = []
        for node in ast.walk(test):
            if isinstance(node, ast.Compare):
                operands = [node.left, *node.comparators]
                for operand in operands:
                    if isinstance(operand, ast.Constant) and isinstance(operand.value, (int, float)):
                        if isinstance(operand.value, bool):
                            continue
                        if operand.value in ALLOWED_NUMBERS:
                            continue
                        found.append((operand.lineno, operand.value))
        return found


class ModuleParser:
    def __init__(self, path: Path, rel_path: str, module_name: str) -> None:
        self.path = path
        self.rel_path = rel_path
        self.module_name = module_name

    def parse(self) -> ModuleInfo:
        source = self.path.read_text(encoding="utf-8", errors="replace")
        lines = source.splitlines()
        sloc = sum(1 for line in lines if line.strip() and not line.strip().startswith("#"))
        module = ModuleInfo(path=self.rel_path, module=self.module_name,
                            loc=len(lines), sloc=sloc, source_lines=lines)
        try:
            tree = ast.parse(source, filename=str(self.path))
        except SyntaxError as exc:
            module.parse_error = f"{exc.msg} (line {exc.lineno})"
            return module

        for node in tree.body:
            self._visit_top_level(node, module)
        self._collect_imports(tree, module)
        return module

    def _collect_imports(self, tree: ast.Module, module: ModuleInfo) -> None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module.imports.append({
                        "module": alias.name, "names": [], "level": 0, "line": node.lineno,
                    })
            elif isinstance(node, ast.ImportFrom):
                module.imports.append({
                    "module": node.module or "",
                    "names": [a.name for a in node.names],
                    "level": node.level or 0,
                    "line": node.lineno,
                })

    def _visit_top_level(self, node: ast.AST, module: ModuleInfo) -> None:
        if isinstance(node, ast.ClassDef):
            module.classes.append(self._parse_class(node))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            module.functions.append(
                FunctionParser(node, self.rel_path, qual_prefix=f"{self.module_name}.").parse()
            )

    def _parse_class(self, node: ast.ClassDef) -> ClassInfo:
        end_line = getattr(node, "end_lineno", node.lineno) or node.lineno
        bases = [_name_of(b) for b in node.bases]
        keywords = {kw.arg: _name_of(kw.value) for kw in node.keywords if kw.arg}
        decorators = _decorator_names(node)

        info = ClassInfo(
            name=node.name,
            qualname=f"{self.module_name}.{node.name}",
            file=self.rel_path,
            module=self.module_name,
            line=node.lineno,
            end_line=end_line,
            loc=end_line - node.lineno + 1,
            bases=bases,
            decorators=decorators,
            is_dataclass=any("dataclass" in d for d in decorators),
        )
        info.is_exception = any(b.endswith("Error") or b.endswith("Exception") for b in bases)

        prefix = f"{self.module_name}.{node.name}."
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                info.methods.append(
                    FunctionParser(child, self.rel_path, class_name=node.name,
                                   qual_prefix=prefix).parse()
                )
            elif isinstance(child, ast.Assign):
                for target in child.targets:
                    if isinstance(target, ast.Name):
                        info.class_attrs[target.id] = _name_of(child.value)
            elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                info.class_attrs[child.target.id] = _name_of(child.annotation)

        for method in info.methods:
            info.instance_attrs |= method.self_attrs

        metaclass = keywords.get("metaclass", "")
        info.is_abstract = (
            any(base in ABSTRACT_BASES or base.split(".")[-1] in ABSTRACT_BASES for base in bases)
            or "ABCMeta" in metaclass
            or bool(info.abstract_methods)
        )
        return info


def module_name_for(rel_path: str) -> str:
    name = rel_path[:-3] if rel_path.endswith(".py") else rel_path
    name = name.replace("/", ".")
    if name.endswith(".__init__"):
        name = name[: -len(".__init__")]
    return name or "__root__"


def parse_repository(root: Path, files: list[Path]) -> list[ModuleInfo]:
    modules: list[ModuleInfo] = []
    for file in files:
        rel = str(file.relative_to(root)).replace("\\", "/")
        modules.append(ModuleParser(file, rel, module_name_for(rel)).parse())
    return modules
