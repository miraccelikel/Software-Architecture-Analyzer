"""Tree-sitter front-end: Java, TypeScript, C#, C++ and C.

The rule engine only ever sees `ModuleInfo` / `ClassInfo` / `FunctionInfo`, so a
new language is a matter of filling those models from a different grammar. Every
language-specific node name lives in `SPECS` below; the traversal is shared.

Three traits need more than a node-name table, and `LanguageSpec` flags them:

* `declarator_style` — C and C++ put the function name inside a
  `function_declarator` rather than a `name` field, and a definition may carry a
  qualifier (`int OrderService::process()`) that names the class it belongs to.
* `preprocessor_includes` — C and C++ depend through `#include`, not `import`.
* `namespace_nodes` — Java packages and C# namespaces belong in the module name.
"""

from __future__ import annotations

import hashlib
import posixpath
from dataclasses import dataclass, field
from pathlib import Path

from .models import ClassInfo, FunctionInfo, ModuleInfo

ALLOWED_NUMBERS = {"0", "1", "2", "-1", "10", "100", "1000", "0L", "1L", "0.0", "1.0",
                   "0u", "1u", "0x0", "0xFF"}


class TreeSitterUnavailable(RuntimeError):
    """Raised when the grammar packages are not installed."""


@dataclass
class LanguageSpec:
    name: str
    extensions: tuple[str, ...]
    classes: set[str]
    interfaces: set[str]
    methods: set[str]
    functions: set[str]
    decisions: set[str]
    nesting: set[str]
    boolean_operators: set[str]
    imports: set[str]
    construction: set[str]
    type_checks: set[str]
    fields: set[str]
    namespace_nodes: set[str] = field(default_factory=set)
    abstract_keywords: set[str] = field(default_factory=lambda: {"abstract"})
    not_implemented: tuple[str, ...] = ()
    declarator_style: bool = False
    preprocessor_includes: bool = False
    member_functions: bool = True   # structs in C have no methods


C_DECISIONS = {"if_statement", "for_statement", "while_statement", "do_statement",
               "case_statement", "conditional_expression"}
C_NESTING = {"if_statement", "for_statement", "while_statement", "do_statement",
             "switch_statement"}

SPECS: dict[str, LanguageSpec] = {
    "java": LanguageSpec(
        name="java",
        extensions=(".java",),
        classes={"class_declaration", "record_declaration", "enum_declaration"},
        interfaces={"interface_declaration"},
        methods={"method_declaration", "constructor_declaration",
                 "compact_constructor_declaration"},
        functions=set(),
        decisions={"if_statement", "for_statement", "enhanced_for_statement",
                   "while_statement", "do_statement", "catch_clause",
                   "switch_block_statement_group", "switch_rule", "ternary_expression",
                   "assert_statement"},
        nesting={"if_statement", "for_statement", "enhanced_for_statement",
                 "while_statement", "do_statement", "try_statement", "switch_expression",
                 "synchronized_statement"},
        boolean_operators={"&&", "||"},
        imports={"import_declaration"},
        construction={"object_creation_expression"},
        type_checks={"instanceof_expression"},
        fields={"field_declaration"},
        namespace_nodes={"package_declaration"},
        not_implemented=("UnsupportedOperationException", "NotImplementedException"),
    ),
    "typescript": LanguageSpec(
        name="typescript",
        extensions=(".ts", ".tsx"),
        classes={"class_declaration", "abstract_class_declaration", "class"},
        interfaces={"interface_declaration"},
        methods={"method_definition", "method_signature", "abstract_method_signature"},
        functions={"function_declaration", "function_signature",
                   "generator_function_declaration", "arrow_function", "function_expression"},
        decisions={"if_statement", "for_statement", "for_in_statement", "while_statement",
                   "do_statement", "catch_clause", "switch_case", "ternary_expression"},
        nesting={"if_statement", "for_statement", "for_in_statement", "while_statement",
                 "do_statement", "try_statement", "switch_statement"},
        boolean_operators={"&&", "||", "??"},
        imports={"import_statement"},
        construction={"new_expression"},
        type_checks={"instanceof_expression"},
        fields={"public_field_definition", "property_signature", "field_definition"},
        not_implemented=("Error(\"not implemented", "NotImplementedError"),
    ),
    "csharp": LanguageSpec(
        name="csharp",
        extensions=(".cs",),
        classes={"class_declaration", "record_declaration", "struct_declaration",
                 "enum_declaration"},
        interfaces={"interface_declaration"},
        methods={"method_declaration", "constructor_declaration", "destructor_declaration",
                 "operator_declaration"},
        functions=set(),
        decisions={"if_statement", "for_statement", "for_each_statement", "while_statement",
                   "do_statement", "catch_clause", "switch_section", "switch_expression_arm",
                   "conditional_expression", "conditional_access_expression"},
        nesting={"if_statement", "for_statement", "for_each_statement", "while_statement",
                 "do_statement", "try_statement", "switch_statement", "lock_statement",
                 "using_statement"},
        boolean_operators={"&&", "||", "??"},
        imports={"using_directive"},
        construction={"object_creation_expression"},
        type_checks={"is_expression", "is_pattern_expression", "as_expression",
                     "type_of_expression"},
        fields={"field_declaration", "property_declaration"},
        namespace_nodes={"namespace_declaration", "file_scoped_namespace_declaration"},
        not_implemented=("NotImplementedException", "NotSupportedException"),
    ),
    "cpp": LanguageSpec(
        name="cpp",
        extensions=(".cpp", ".cc", ".cxx", ".hpp", ".hh", ".h"),
        classes={"class_specifier", "struct_specifier"},
        interfaces=set(),
        methods={"function_definition"},
        functions={"function_definition"},
        decisions=C_DECISIONS | {"catch_clause", "for_range_loop"},
        nesting=C_NESTING | {"for_range_loop", "try_statement"},
        boolean_operators={"&&", "||", "and", "or"},
        imports={"preproc_include"},
        construction={"new_expression"},
        type_checks={"dynamic_cast_expression", "typeid_expression"},
        fields={"field_declaration"},
        namespace_nodes={"namespace_definition"},
        abstract_keywords={"virtual"},
        not_implemented=("logic_error", "not_implemented", "NotImplemented"),
        declarator_style=True,
        preprocessor_includes=True,
    ),
    "c": LanguageSpec(
        name="c",
        extensions=(".c", ".h"),
        classes={"struct_specifier", "union_specifier"},
        interfaces=set(),
        methods=set(),
        functions={"function_definition"},
        decisions=C_DECISIONS,
        nesting=C_NESTING,
        boolean_operators={"&&", "||"},
        imports={"preproc_include"},
        construction=set(),
        type_checks=set(),
        fields={"field_declaration"},
        declarator_style=True,
        preprocessor_includes=True,
        member_functions=False,
    ),
}

EXTENSION_TO_LANGUAGE = {ext: spec.name for spec in SPECS.values() for ext in spec.extensions}
GRAMMAR_MODULES = {
    "java": ("tree_sitter_java", "language"),
    "typescript": ("tree_sitter_typescript", "language_typescript"),
    "tsx": ("tree_sitter_typescript", "language_tsx"),
    "csharp": ("tree_sitter_c_sharp", "language"),
    "cpp": ("tree_sitter_cpp", "language"),
    "c": ("tree_sitter_c", "language"),
}
PACKAGE_HINT = {
    "java": "tree-sitter-java", "typescript": "tree-sitter-typescript",
    "tsx": "tree-sitter-typescript", "csharp": "tree-sitter-c-sharp",
    "cpp": "tree-sitter-cpp", "c": "tree-sitter-c",
}


def _load_parser(language: str):
    entry = GRAMMAR_MODULES.get(language)
    if entry is None:
        raise TreeSitterUnavailable(f"No Tree-sitter front-end for language: {language}")
    try:
        from importlib import import_module

        from tree_sitter import Language, Parser
        module = import_module(entry[0])
    except ImportError as exc:
        raise TreeSitterUnavailable(
            f"To analyse {language}:  pip install tree-sitter {PACKAGE_HINT[language]}"
        ) from exc
    return Parser(Language(getattr(module, entry[1])()))


class TreeSitterModuleParser:
    """Fill the shared models from a Tree-sitter tree."""

    def __init__(self, path: Path, rel_path: str, spec: LanguageSpec, parser) -> None:
        self.path = path
        self.rel_path = rel_path
        self.spec = spec
        self.parser = parser
        self.source = b""
        self.module_name = ""

    # -- helpers ---------------------------------------------------------- #
    def text(self, node) -> str:
        return self.source[node.start_byte:node.end_byte].decode("utf-8", "replace")

    def child_text(self, node, field_name: str) -> str:
        child = node.child_by_field_name(field_name)
        return self.text(child) if child is not None else ""

    def descendants(self, node, skip: set[str]):
        """Depth-first walk that does not enter nested declarations."""
        stack = [(child, 0) for child in reversed(node.named_children)]
        while stack:
            current, depth = stack.pop()
            yield current, depth
            if current.type in skip:
                continue
            next_depth = depth + 1 if current.type in self.spec.nesting else depth
            stack.extend((child, next_depth) for child in reversed(current.named_children))

    # -- entry point ------------------------------------------------------ #
    def parse(self) -> ModuleInfo:
        self.source = self.path.read_bytes()
        lines = self.source.decode("utf-8", "replace").splitlines()
        sloc = sum(1 for line in lines
                   if line.strip() and not line.strip().startswith(("//", "*", "/*")))
        tree = self.parser.parse(self.source)
        root = tree.root_node

        self.module_name = self._module_name(root)
        module = ModuleInfo(path=self.rel_path, module=self.module_name,
                            loc=len(lines), sloc=sloc, source_lines=lines)

        declarations = self.spec.classes | self.spec.interfaces
        skip = declarations | self.spec.functions
        bound_bodies: set[int] = set()
        for node, _depth in self.descendants(root, skip=skip):
            if node.type in declarations:
                declared = self._class(node)
                if declared is not None:
                    module.classes.append(declared)
            elif node.type in ("variable_declarator", "public_field_definition"):
                bound = self._bound_function(node)
                if bound is not None:
                    module.functions.append(bound)
                    bound_bodies.add(node.child_by_field_name("value").id)
            elif node.type in self.spec.functions:
                # the arrow of `const f = () => {}` was already counted as `f`,
                # and an anonymous callback is not a declaration at all
                if node.id in bound_bodies:
                    continue
                if node.type in ("arrow_function", "function_expression"):
                    continue
                module.functions.append(self._function(node, class_name="", fields=set()))
            elif node.type in self.spec.imports:
                imported = self._import(node)
                if imported:
                    module.imports.append(imported)

        if self.spec.declarator_style:
            self._reattach_out_of_line_methods(module)
        if root.has_error and not (module.classes or module.functions):
            module.parse_error = "the grammar could not parse this file"
        return module

    def _reattach_out_of_line_methods(self, module: ModuleInfo) -> None:
        attach_definitions(module)

    def _module_name(self, root) -> str:
        stem = self.rel_path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        if self.spec.name in ("java", "csharp"):
            scope = self._namespace_of(root)
            return f"{scope}.{stem}" if scope else stem
        # C/C++: a.h and a.cpp are two faces of one translation unit
        return self.rel_path.rsplit(".", 1)[0].replace("/", ".")

    def _namespace_of(self, root) -> str:
        for child in root.named_children:
            if child.type in self.spec.namespace_nodes:
                if self.spec.name == "java":
                    return self.text(child).replace("package", "").strip(" ;\n")
                return self.child_text(child, "name")
        return ""

    def _import(self, node) -> dict:
        line = node.start_point[0] + 1
        if self.spec.preprocessor_includes:
            return self._include(node, line)
        if self.spec.name in ("java", "csharp"):
            raw = self.text(node)
            for keyword in ("import", "using", "static", "global"):
                if raw.startswith(keyword):
                    raw = raw[len(keyword):]
            return {"module": raw.strip(" ;\n").removesuffix(".*"),
                    "names": [], "level": 0, "line": line}

        source_node = node.child_by_field_name("source")
        target = self.text(source_node).strip("\"'") if source_node else ""
        names = [self.text(child) for child in node.named_children
                 if child.type == "import_clause"]
        if target.startswith("."):
            base = posixpath.dirname(self.rel_path)
            target = posixpath.normpath(posixpath.join(base, target))
        for suffix in (".ts", ".tsx", ".js", ".jsx", "/index"):
            target = target.removesuffix(suffix)
        return {"module": target.replace("/", "."), "names": names[:1], "level": 0, "line": line}

    def _include(self, node, line: int) -> dict:
        """`#include "order.h"` is a dependency; `<vector>` is not."""
        target = ""
        for child in node.named_children:
            if child.type == "system_lib_string":
                return {}
            if child.type == "string_literal":
                target = self.text(child).strip('"')
        if not target:
            return {}
        base = posixpath.dirname(self.rel_path)
        resolved = posixpath.normpath(posixpath.join(base, target)).rsplit(".", 1)[0]
        return {"module": resolved.replace("/", "."), "names": [], "level": 0, "line": line}

    # -- declarations ----------------------------------------------------- #
    def _class(self, node) -> ClassInfo | None:
        name = self.child_text(node, "name") or self._typedef_name(node)
        body = node.child_by_field_name("body")
        if not name or body is None:
            return None  # forward declaration or anonymous struct

        start, end = node.start_point[0] + 1, node.end_point[0] + 1
        modifiers = self._modifiers(node)
        is_interface = node.type in self.spec.interfaces

        info = ClassInfo(
            name=name, qualname=f"{self.module_name}.{name}", file=self.rel_path,
            module=self.module_name, line=start, end_line=end, loc=end - start + 1,
            bases=self._bases(node), decorators=sorted(modifiers),
            is_abstract=is_interface or bool(modifiers & self.spec.abstract_keywords),
        )
        info.is_exception = any(base.endswith(("Exception", "Error")) for base in info.bases)
        info.class_attrs = self._fields(body)
        fields = set(info.class_attrs)

        for child in body.named_children:
            if child.type in self.spec.methods:
                info.methods.append(self._function(child, name, fields))
            elif (self.spec.declarator_style and self.spec.member_functions
                    and child.type in ("field_declaration", "declaration")):
                stub = self._declared_method(child, name)
                if stub is not None:
                    info.methods.append(stub)
            elif child.type in ("public_field_definition", "field_definition"):
                bound = self._bound_function(child, name, fields)
                if bound is not None:
                    info.methods.append(bound)
            elif child.type == "field_declaration" and not self.spec.declarator_style:
                bound = self._bound_function(child, name, fields)
                if bound is not None:
                    info.methods.append(bound)

        for method in info.methods:
            info.instance_attrs |= method.self_attrs
        if not info.is_abstract and info.abstract_methods:
            info.is_abstract = True
        return info

    @staticmethod
    def _typedef_name(node) -> str:
        """`typedef struct { ... } order_t;` — the name lives on the typedef."""
        parent = node.parent
        if parent is None or parent.type != "type_definition":
            return ""
        for child in parent.named_children:
            if child.type == "type_identifier" and child.start_byte > node.start_byte:
                return child.text.decode("utf-8", "replace")
        return ""

    def _modifiers(self, node) -> set[str]:
        collected: set[str] = set()
        for child in node.children:
            if child.type == "modifiers":
                collected |= set(self.text(child).split())
            elif child.type in ("modifier", "virtual", "abstract", "static", "readonly",
                                "accessibility_modifier", "virtual_function_specifier",
                                "storage_class_specifier"):
                collected.add(self.text(child).strip())
        return collected

    def _bases(self, node) -> list[str]:
        bases: list[str] = []
        for child in node.children:
            if child.type in ("superclass", "super_interfaces", "extends_type_clause",
                              "implements_clause", "extends_clause", "class_heritage",
                              "base_list", "base_class_clause"):
                text = self.text(child)
                for keyword in ("extends", "implements", "public", "private", "protected",
                                "virtual", ":"):
                    text = text.replace(keyword, " ")
                bases.extend(part.strip() for part in text.split(",") if part.strip())
        return [b for b in bases if b]

    def _fields(self, body) -> dict[str, str]:
        """Field declarations nest differently in every language; flatten them."""
        fields: dict[str, str] = {}
        for child in body.named_children:
            if child.type not in self.spec.fields:
                continue
            declared_type = self.child_text(child, "type")
            if not declared_type:
                for inner in child.named_children:
                    if inner.type == "variable_declaration":
                        declared_type = self.child_text(inner, "type")
                        break

            if child.type == "property_declaration":                       # C#
                fields[self.child_text(child, "name")] = declared_type
                continue
            if (self.spec.declarator_style and self.spec.member_functions
                    and self._declarator_parts(child) is not None):
                continue                                                   # method, not field
            if self.spec.declarator_style and not self.spec.member_functions:
                parts = self._declarator_parts(child)
                if parts is not None:              # in C, void (*render)(...) is a field
                    fields[parts[0]] = declared_type or "function pointer"
                    continue

            for node in self._flatten(child):
                if node.type in ("variable_declarator", "field_identifier", "identifier"):
                    label = (self.child_text(node, "name") or self.text(node)).split("=")[0]
                    label = label.strip().lstrip("*&")
                    if label and label != declared_type:
                        fields[label] = declared_type
        return {name: kind for name, kind in fields.items() if name}

    def _flatten(self, node):
        for child in node.named_children:
            if child.type in ("variable_declaration", "pointer_declarator",
                              "reference_declarator", "init_declarator", "array_declarator"):
                yield from self._flatten(child)
            elif child.type == "function_declarator":
                continue
            else:
                yield child

    def _declared_method(self, node, class_name: str) -> FunctionInfo | None:
        """A C++ header declaration: `virtual double pay(double amount) = 0;`"""
        parts = self._declarator_parts(node)
        if parts is None:
            return None
        name, scope, params_node = parts
        text = self.text(node)
        start = node.start_point[0] + 1
        parameter_names, parameter_types = self._parameter_info(params_node)
        return FunctionInfo(
            name=name, qualname=f"{self.module_name}.{class_name}.{name}",
            file=self.rel_path, line=start, end_line=node.end_point[0] + 1, loc=1,
            params=parameter_names, param_types=parameter_types, is_method=True,
            class_name=scope or class_name,
            is_abstract="=0" in text.replace(" ", ""),
            is_static=text.strip().startswith("static"),
        )

    # -- functions -------------------------------------------------------- #
    def _bound_function(self, node, class_name: str = "",
                        fields: set[str] | None = None) -> FunctionInfo | None:
        """`const handle = (x) => {...}` is a function, not a variable."""
        value = node.child_by_field_name("value")
        if value is None or value.type not in ("arrow_function", "function_expression"):
            return None
        info = self._function(value, class_name, fields or set())
        info.name = self.child_text(node, "name") or info.name
        prefix = f"{self.module_name}.{class_name}." if class_name else f"{self.module_name}."
        info.qualname = prefix + info.name
        info.line = node.start_point[0] + 1
        info.loc = info.end_line - info.line + 1
        return info

    def _declarator_parts(self, node):
        """Unwrap pointers and references to reach the function_declarator."""
        declarator = node.child_by_field_name("declarator")
        for _ in range(6):
            if declarator is None or declarator.type == "function_declarator":
                break
            declarator = declarator.child_by_field_name("declarator")
        if declarator is None or declarator.type != "function_declarator":
            return None
        name_node = declarator.child_by_field_name("declarator")
        if name_node is None:
            return None
        scope, _, simple = self.text(name_node).rpartition("::")
        return simple.strip(), scope.strip(), declarator.child_by_field_name("parameters")

    def _function(self, node, class_name: str, fields: set[str]) -> FunctionInfo:
        start, end = node.start_point[0] + 1, node.end_point[0] + 1
        modifiers = self._modifiers(node)
        params_node = node.child_by_field_name("parameters")
        name = self.child_text(node, "name")
        owner = class_name

        if self.spec.declarator_style:
            parts = self._declarator_parts(node)
            if parts is not None:
                name, scope, params_node = parts
                owner = scope or class_name
        if not name:
            name = class_name or "<anonim>"

        prefix = f"{self.module_name}.{owner}." if owner else f"{self.module_name}."
        parameter_names, parameter_types = self._parameter_info(params_node)
        info = FunctionInfo(
            name=name, qualname=prefix + name, file=self.rel_path,
            line=start, end_line=end, loc=end - start + 1,
            params=parameter_names, param_types=parameter_types, is_method=bool(owner),
            class_name=owner, decorators=sorted(modifiers),
            is_static="static" in modifiers,
            is_abstract="abstract" in modifiers
                        or node.type in ("method_signature", "abstract_method_signature")
                        or node.child_by_field_name("body") is None,
        )
        returns = self.child_text(node, "type") or self.child_text(node, "return_type")
        if returns:
            info.annotations["->"] = returns.lstrip(": ")

        self._scan_body(node, info, fields)
        return info

    def _parameters_from(self, params_node) -> list[str]:
        return self._parameter_info(params_node)[0]

    def _parameter_info(self, params_node) -> tuple[list[str], list[str]]:
        """Names and declared types.

        The types are what a cross-language contract is actually made of, so a
        pointer has to survive the trip: `const char *board` is `const char*`,
        not `char`.
        """
        if params_node is None:
            return [], []
        names: list[str] = []
        types: list[str] = []

        for child in params_node.named_children:
            if child.type in ("comment", "type_annotation"):
                continue

            declared = self.child_text(child, "type")
            declarator = child.child_by_field_name("declarator")
            stars = ""
            node = declarator
            for _ in range(4):
                if node is None or node.type not in ("pointer_declarator",
                                                     "reference_declarator",
                                                     "array_declarator"):
                    break
                stars += "*"
                node = node.child_by_field_name("declarator")

            label = self.child_text(child, "name")
            if not label and self.spec.declarator_style:
                label = self.text(node) if node is not None else self.text(child)
            raw = (label or self.text(child))
            if ":" in raw and not self.spec.declarator_style:
                head, _, annotation = raw.partition(":")
                label, declared = head, declared or annotation
            else:
                label = raw
            label = label.split("=")[0].strip().lstrip("*&").strip()

            if not declared and not self.spec.declarator_style:
                declared = self.child_text(child, "type")
            declared = (declared + stars).strip()

            if label in ("void", "...") or (label and "(" in label):
                continue
            if not label and not declared:
                continue
            if label:
                names.append(label)
                types.append(declared)
        return names, types

    def _scan_body(self, node, info: FunctionInfo, fields: set[str]) -> None:
        complexity = 1
        nesting = 0
        skip = self.spec.classes | self.spec.interfaces | self.spec.functions

        for child, depth in self.descendants(node, skip=skip):
            kind = child.type
            nesting = max(nesting, depth)

            if kind in self.spec.decisions:
                complexity += 1
            elif kind in ("binary_expression", "logical_expression"):
                if self.child_text(child, "operator") in self.spec.boolean_operators:
                    complexity += 1
                self._magic_number(child, info)
            elif kind in ("switch_statement", "switch_expression"):
                info.branch_chains.append((child.start_point[0] + 1, self._case_count(child)))

            if kind == "if_statement":
                chain = self._chain_length(child)
                if chain >= 3:
                    info.branch_chains.append((child.start_point[0] + 1, chain))

            if kind in self.spec.type_checks:
                info.type_checks.append((child.start_point[0] + 1, self.text(child)[:60]))
            elif kind in self.spec.construction:
                created = (self.child_text(child, "type")
                           or self.child_text(child, "constructor")).split("<")[0].strip()
                if created:
                    info.instantiations.append((created, child.start_point[0] + 1))
                    if any(marker.split("(")[0] in created
                           for marker in self.spec.not_implemented):
                        info.raises_not_implemented = True

            self._scan_self_usage(child, info, fields)
            self._scan_return(child, info)

        info.complexity = complexity
        info.max_nesting = nesting
        info.fingerprint, info.shape_size = self._fingerprint(node)

    def _fingerprint(self, node) -> tuple[str, int]:
        """Hash the shape of the body, ignoring identifiers and literal values."""
        shape: list[str] = []
        stack = [node]
        while stack:
            current = stack.pop()
            for child in reversed(current.named_children):
                kind = child.type
                if kind == "comment":
                    continue
                if kind in ("identifier", "field_identifier", "type_identifier",
                            "property_identifier", "primitive_type", "scoped_identifier"):
                    shape.append("Ref")
                elif kind.endswith("_literal") or kind in ("number", "string", "true", "false"):
                    shape.append("Const")
                else:
                    shape.append(kind)
                stack.append(child)
        digest = hashlib.blake2s("|".join(shape).encode(), digest_size=8).hexdigest()
        return digest, len(shape)

    def _scan_self_usage(self, node, info: FunctionInfo, fields: set[str]) -> None:
        """Which fields the method touches and which siblings it calls (LCOM4).

        Java and TypeScript spell it `this.x`; C++ and C# usually just write the
        member name, so a bare identifier that matches a declared field counts.
        """
        if node.type in ("field_access", "member_expression", "member_access_expression",
                         "field_expression"):
            owner = self.child_text(node, "object") or self.child_text(node, "argument")
            member = (self.child_text(node, "field") or self.child_text(node, "property")
                      or self.child_text(node, "name"))
            if owner in ("this", "self", "(*this)") and member:
                info.self_attrs.add(member)
            return

        if node.type in ("method_invocation", "call_expression", "invocation_expression"):
            function_node = node.child_by_field_name("function")
            called = self.child_text(node, "name")
            owner = self.child_text(node, "object")
            if function_node is not None:
                if function_node.type in ("identifier", "field_identifier"):
                    called = called or self.text(function_node)
                else:
                    called = (called or self.child_text(function_node, "field")
                              or self.child_text(function_node, "property")
                              or self.child_text(function_node, "name"))
                    owner = (owner or self.child_text(function_node, "object")
                             or self.child_text(function_node, "argument"))
            if called and owner in ("", "this", "self"):
                info.self_calls.add(called)
                info.self_attrs.discard(called)
            return

        if node.type in ("identifier", "field_identifier") and self.text(node) in fields:
            name = self.text(node)
            if name not in info.self_calls:
                info.self_attrs.add(name)

    def _scan_return(self, node, info: FunctionInfo) -> None:
        if node.type == "return_statement":
            body = self.text(node).replace("return", "").strip(" ;")
            if body in ("this", "*this", "self"):
                info.returns_self = True
        elif node.type in ("throw_statement", "throw_expression"):
            if any(marker in self.text(node) for marker in self.spec.not_implemented):
                info.raises_not_implemented = True

    def _chain_length(self, node) -> int:
        count, current = 1, node
        while True:
            alternative = current.child_by_field_name("alternative")
            if alternative is None:
                return count
            count += 1
            inner = alternative
            if inner.type != "if_statement":
                inner = next((c for c in inner.named_children if c.type == "if_statement"), None)
                if inner is None:
                    return count
            current = inner

    def _case_count(self, node) -> int:
        body = node.child_by_field_name("body") or node
        return sum(1 for child in body.named_children
                   if child.type in ("switch_block_statement_group", "switch_case",
                                     "switch_rule", "switch_default", "switch_section",
                                     "case_statement", "switch_expression_arm"))

    def _magic_number(self, node, info: FunctionInfo) -> None:
        if self.child_text(node, "operator") not in ("==", "!=", "<", ">", "<=", ">=", "==="):
            return
        for side in ("left", "right"):
            operand = node.child_by_field_name(side)
            if operand is None or operand.type not in (
                    "decimal_integer_literal", "number", "number_literal", "integer_literal",
                    "real_literal", "decimal_floating_point_literal"):
                continue
            value = self.text(operand)
            if value not in ALLOWED_NUMBERS:
                info.magic_numbers.append((operand.start_point[0] + 1, value))


# --------------------------------------------------------------------------- #
def parse_repository(root: Path, files: list[Path], language: str) -> list[ModuleInfo]:
    spec = SPECS.get(language)
    if spec is None:
        raise TreeSitterUnavailable(f"Unsupported language: {language}")

    parsers = {language: _load_parser(language)}
    if language == "typescript":
        parsers["tsx"] = _load_parser("tsx")

    modules: list[ModuleInfo] = []
    seen: dict[str, ModuleInfo] = {}
    for file in files:
        rel = str(file.relative_to(root)).replace("\\", "/")
        dialect = "tsx" if rel.endswith(".tsx") and "tsx" in parsers else language
        parsed = TreeSitterModuleParser(file, rel, spec, parsers[dialect]).parse()

        twin = seen.get(parsed.module)
        if twin is not None and spec.declarator_style:
            merge_translation_unit(twin, parsed)
            continue
        seen[parsed.module] = parsed
        modules.append(parsed)
    return modules


def attach_definitions(module: ModuleInfo) -> None:
    """`int OrderService::process()` belongs to OrderService, not to the file.

    A header declares the method and the implementation file defines it; the
    definition replaces the declaration stub so that size and complexity are
    measured on the real body.
    """
    by_name = {cls.name: cls for cls in module.classes}
    remaining: list[FunctionInfo] = []
    for func in module.functions:
        owner = by_name.get(func.class_name)
        if owner is None:
            remaining.append(func)
            continue
        owner.methods = [m for m in owner.methods if m.name != func.name] + [func]
        owner.instance_attrs |= func.self_attrs
    module.functions = remaining

    for cls in module.classes:
        # a C++ class is spread over two files: its real footprint is the
        # declaration plus every method body defined elsewhere
        bodies = sum(m.loc for m in cls.methods if m.loc > 1)
        cls.loc = max(cls.loc, bodies)


def merge_translation_unit(target: ModuleInfo, extra: ModuleInfo) -> None:
    """Fold `order.cpp` into the `order.h` it implements.

    A header and its implementation are one module architecturally: the class is
    declared in one file and its methods live in the other. Keeping them apart
    would report every C++ class as having empty methods and no dependencies.
    """
    by_name = {cls.name: cls for cls in target.classes}
    for cls in extra.classes:
        twin = by_name.get(cls.name)
        if twin is None:
            target.classes.append(cls)
            by_name[cls.name] = cls
            continue
        defined = {method.name for method in cls.methods}
        twin.methods = [m for m in twin.methods if m.name not in defined] + cls.methods
        twin.instance_attrs |= cls.instance_attrs
        twin.class_attrs.update(cls.class_attrs)
        twin.bases = twin.bases or cls.bases

    target.functions.extend(extra.functions)
    target.imports.extend(extra.imports)
    target.loc += extra.loc
    target.sloc += extra.sloc
    target.extra_sources[extra.path] = extra.source_lines
    for path, lines in extra.extra_sources.items():
        target.extra_sources[path] = lines
    attach_definitions(target)      # independent of which file was parsed first
