"""Cross-language call contracts: C++/C# P/Invoke and Python ctypes."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from archray import analyze_source
from archray.bindings import compatible
from archray.changes import compare as compare_structure
from archray.changes import materialise

ROOT = Path(__file__).resolve().parents[1]
INTEROP = ROOT / "examples" / "demo_interop"


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture(scope="module")
def report() -> dict:
    return analyze_source(str(INTEROP))


def bindings_by_symbol(report: dict) -> dict[str, dict]:
    return {item["symbol"]: item for item in report["bindings"]["bindings"]}


# ------------------------------------------------------------- marshalling -- #
@pytest.mark.parametrize("managed,native", [
    ("string", "const char*"),
    ("int", "int32_t"),
    ("double", "double"),
    ("bool", "int"),
    ("IntPtr", "void*"),
    ("byte", "unsigned char"),
])
def test_types_that_may_marshal(managed: str, native: str) -> None:
    assert compatible(managed, native)


@pytest.mark.parametrize("managed,native", [
    ("int", "double"),
    ("float", "int"),
    ("string", "int"),
])
def test_types_that_may_not(managed: str, native: str) -> None:
    assert not compatible(managed, native)


def test_unknown_types_are_not_guessed_at() -> None:
    """A custom struct means nothing to the table; silence beats a false alarm."""
    assert compatible("MyOptions", "options_t")


# ------------------------------------------------------------- resolution -- #
def test_matching_declaration_is_satisfied(report: dict) -> None:
    binding = bindings_by_symbol(report)["engine_evaluate"]
    assert binding["status"] == "satisfied"
    assert binding["native"]["signature"] == "int engine_evaluate(char*, int, double)"


def test_wrong_arity_is_a_mismatch(report: dict) -> None:
    binding = bindings_by_symbol(report)["engine_best_move"]
    assert binding["status"] == "mismatch"
    assert any("arity" in problem for problem in binding["problems"])


def test_missing_native_symbol_is_dangling(report: dict) -> None:
    binding = bindings_by_symbol(report)["engine_undo_move"]
    assert binding["status"] == "dangling"
    assert binding["managed"]["name"] == "Undo"      # EntryPoint, not the method name


def test_findings_are_raised_for_broken_contracts(report: dict) -> None:
    rules = {f["rule"] for f in report["findings"] if f["kind"] == "binding"}
    assert rules == {"binding_signature_mismatch", "unresolved_native_symbol"}
    mismatch = next(f for f in report["findings"]
                    if f["rule"] == "binding_signature_mismatch")
    assert mismatch["severity"] == "critical"
    assert mismatch["file"].endswith(".cs")


def test_ctypes_declarations_are_read(tmp_path: Path) -> None:
    (tmp_path / "engine.h").write_text(
        'extern "C" __declspec(dllexport) int add(int a, int b);\n')
    (tmp_path / "engine.c").write_text("int add(int a, int b) { return a + b; }\n")
    (tmp_path / "wrapper.py").write_text(
        "import ctypes\n"
        "lib = ctypes.CDLL('engine')\n"
        "lib.add.argtypes = [ctypes.c_int, ctypes.c_int]\n"
        "lib.add.restype = ctypes.c_int\n"
        "lib.scale.argtypes = [ctypes.c_double]\n"
    )
    result = analyze_source(str(tmp_path))
    bindings = bindings_by_symbol(result)
    assert bindings["add"]["status"] == "satisfied"
    assert bindings["scale"]["status"] == "dangling"


# --------------------------------------------------- breaking across a diff -- #
def test_a_native_signature_change_breaks_the_managed_contract(tmp_path: Path) -> None:
    """The scenario the whole feature exists for."""
    repo = tmp_path / "interop"
    repo.mkdir()
    for source in INTEROP.rglob("*.*"):
        target = repo / source.relative_to(INTEROP)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    # start from an agreeing pair
    managed = repo / "managed" / "EngineInterop.cs"
    managed.write_text(managed.read_text(encoding="utf-8").replace(
        "int engine_best_move(string board);", "int engine_best_move(string board, int depth);"))
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "a@b.c")
    git(repo, "config", "user.name", "Dev")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "contracts agree")

    # the native side gains a parameter; nobody told the C# side
    for name in ("native/engine.h", "native/engine.cpp"):
        path = repo / name
        path.write_text(path.read_text(encoding="utf-8").replace(
            "int engine_evaluate(const char* board, int depth, double weight)",
            "int engine_evaluate(const char* board, int depth, double weight, int seed)"))

    snapshot = materialise(repo, "HEAD")
    baseline = analyze_source(str(snapshot))
    current = analyze_source(str(repo))
    diff = compare_structure(baseline, current, "HEAD", snapshot, repo)

    broken = diff["bindings"]["broken"]
    assert [item["symbol"] for item in broken] == ["engine_evaluate"]
    assert "arity" in broken[0]["problems"][0]
    assert "engine_evaluate" in diff["bindings"]["verdict"]

    kinds = [note["kind"] for note in diff["highlights"]]
    assert kinds[0] == "broken_binding", "a broken contract is the first thing to read"
