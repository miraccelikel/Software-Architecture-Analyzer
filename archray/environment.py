"""Environment diagnosis for the parser toolchain.

Most of ArchRay needs nothing but the standard library. The Tree-sitter grammars
are the exception, and they are where cross-platform installs actually go wrong:
the PyPI packages ship binary wheels for CPython on Windows, macOS and Linux, but
an interpreter that is *not* one of those — MSYS2/UCRT64, MinGW, Cygwin, Alpine's
musl, a fresh PyPy — matches no wheel and falls back to building the grammar from
C source, which needs a compiler.

Rather than let that surface as an import error halfway through an analysis, this
module answers three questions up front: what interpreter is this, which grammars
are actually importable, and can this machine build the ones that are missing.
"""

from __future__ import annotations

import importlib
import os
import platform
import shutil
import sys
import sysconfig
from dataclasses import dataclass, field

from .treesitter_frontend import GRAMMAR_MODULES, PACKAGE_HINT, SPECS

COMPILERS = ("cc", "gcc", "clang", "cl", "x86_64-w64-mingw32-gcc")
MSYS_TOOLCHAIN = {
    "UCRT64": "mingw-w64-ucrt-x86_64",
    "MINGW64": "mingw-w64-x86_64",
    "MINGW32": "mingw-w64-i686",
    "CLANG64": "mingw-w64-clang-x86_64",
}


@dataclass
class Environment:
    python: str
    implementation: str
    platform_tag: str
    system: str
    msystem: str = ""
    compiler: str = ""
    grammars: dict[str, bool] = field(default_factory=dict)
    core_available: bool = False

    @property
    def is_msys(self) -> bool:
        return bool(self.msystem) or "mingw" in self.platform_tag.lower()

    @property
    def wheels_available(self) -> bool:
        """Whether pip is likely to find a prebuilt wheel for the grammars."""
        return (self.implementation == "CPython"
                and not self.is_msys
                and "musl" not in self.platform_tag.lower())

    @property
    def missing(self) -> list[str]:
        return sorted(name for name, ok in self.grammars.items() if not ok)

    def to_dict(self) -> dict:
        return {
            "python": self.python, "implementation": self.implementation,
            "platform": self.platform_tag, "system": self.system,
            "msystem": self.msystem, "compiler": self.compiler,
            "wheels_available": self.wheels_available,
            "core_available": self.core_available,
            "grammars": dict(sorted(self.grammars.items())),
            "missing": self.missing,
        }


def _module_available(name: str) -> bool:
    """Import rather than trust metadata: a wheel can install and still not load."""
    try:
        module = importlib.import_module(name)
    except Exception:            # ImportError, OSError from a broken shared object
        return False
    return module is not None


def detect() -> Environment:
    grammars: dict[str, bool] = {}
    for language in SPECS:
        module_name = GRAMMAR_MODULES[language][0]
        grammars[language] = _module_available(module_name)

    compiler = next((name for name in COMPILERS if shutil.which(name)), "")
    return Environment(
        python=platform.python_version(),
        implementation=platform.python_implementation(),
        platform_tag=sysconfig.get_platform(),
        system=platform.system(),
        msystem=os.environ.get("MSYSTEM", ""),
        compiler=compiler,
        grammars=grammars,
        core_available=_module_available("tree_sitter"),
    )


def install_commands(env: Environment, languages: list[str] | None = None) -> list[str]:
    """The exact commands that fix this machine, in the order to run them."""
    targets = languages or env.missing
    if not targets:
        return []

    packages = sorted({PACKAGE_HINT[name] for name in targets if name in PACKAGE_HINT})
    commands: list[str] = []

    if env.is_msys:
        prefix = MSYS_TOOLCHAIN.get(env.msystem, "mingw-w64-ucrt-x86_64")
        commands.append(
            f"pacman -S --needed {prefix}-python-pip {prefix}-gcc {prefix}-python-setuptools"
        )
        commands.append("# no wheels match an MSYS2 interpreter, so the grammars are compiled:")
        commands.append("pip install tree-sitter " + " ".join(packages))
        return commands

    if not env.wheels_available and not env.compiler:
        commands.append("# this interpreter has no matching wheels; install a C compiler first")
        commands.append("#   Debian/Ubuntu: apt install build-essential python3-dev")
        commands.append("#   Alpine:        apk add build-base python3-dev")

    commands.append("pip install tree-sitter " + " ".join(packages))
    return commands


def report(env: Environment | None = None, use_color: bool = False) -> str:
    """A readable summary for `archray --doctor`.

    Uses plain ASCII fallbacks when the output stream cannot be trusted to
    render Unicode — see `cli.py`'s `_ensure_utf8_streams()`, which reconfigures
    stdout to UTF-8 before this is ever printed, but a library caller printing
    this elsewhere (a legacy Windows console, a log file opened as cp1252) may
    not have done that, so this stays conservative rather than assuming it.
    """
    env = env or detect()
    tick, cross, rule = ("v", "x", "-")
    if use_color:
        tick, cross = ("\033[92mv\033[0m", "\033[91mx\033[0m")

    lines = [
        "",
        "  Environment",
        "  " + rule * 58,
        f"  Python           {env.python} ({env.implementation})",
        f"  Platform         {env.platform_tag} . {env.system}",
    ]
    if env.msystem:
        lines.append(f"  MSYS2            {env.msystem}"
                     f" -- toolchain prefix {MSYS_TOOLCHAIN.get(env.msystem, '?')}")
    lines.append(f"  C compiler       {env.compiler or 'not found'}")
    lines.append(f"  Prebuilt wheels  {'expected' if env.wheels_available else 'not available'}")

    lines += ["", "  Language support", "  " + rule * 58,
              f"  {tick if env.core_available else cross} tree-sitter core"
              "        (needed by every language except Python)"]
    lines.append(f"  {tick} python            built in, no dependency")
    for language in sorted(SPECS):
        available = env.grammars.get(language, False)
        lines.append(f"  {tick if available else cross} {language:<17} "
                     f"{PACKAGE_HINT.get(language, '')}")

    if env.missing:
        lines += ["", "  To enable the missing languages", "  " + rule * 58]
        lines += ["    " + command for command in install_commands(env)]
        lines += ["",
                  "  ArchRay works without them: unavailable languages are skipped and",
                  "  reported, the rest of the analysis runs normally."]
    else:
        lines += ["", "  Every supported language is available."]

    lines.append("")
    return "\n".join(lines)
 