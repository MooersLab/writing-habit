"""Read an argparse parser into widget-ready descriptors.

The command forms of the interface are generated from the parsers the command
line already defines, so a new subcommand or a new flag reaches the interface
without a second, hand-maintained catalog that would drift.

The walk touches three private argparse attributes, namely ``_actions``,
``_SubParsersAction``, and the ``choices`` map of a subparsers action. That is
the price of the guarantee, and it is confined to this module so a change in a
future Python breaks one file with one clear test.

This module imports no Qt, which lets its tests run wherever the package runs.
"""

from __future__ import annotations

import argparse
import shlex
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class OptionSpec:
    """One positional argument or one option of a subcommand."""

    dest: str
    flags: Tuple[str, ...]          # empty for a positional
    help: str = ""
    choices: Optional[Tuple[str, ...]] = None
    is_flag: bool = False           # store_true
    is_int: bool = False
    required: bool = False
    metavar: Optional[str] = None

    @property
    def positional(self) -> bool:
        return not self.flags

    @property
    def flag(self) -> str:
        """The primary flag, for example ``--week``, or the dest for a positional."""
        return self.flags[0] if self.flags else self.dest

    @property
    def label(self) -> str:
        return self.flag.lstrip("-") if self.flags else self.dest


@dataclass(frozen=True)
class CommandSpec:
    """One runnable subcommand, named by the path of words that selects it."""

    path: Tuple[str, ...]           # ("plan", "import")
    help: str = ""
    options: Tuple[OptionSpec, ...] = field(default_factory=tuple)

    @property
    def name(self) -> str:
        return " ".join(self.path)

    def option(self, flag: str) -> Optional[OptionSpec]:
        for opt in self.options:
            if opt.flag == flag or opt.dest == flag:
                return opt
        return None


def _is_subparsers(action) -> bool:
    return isinstance(action, argparse._SubParsersAction)


def _skip(action) -> bool:
    return isinstance(action, (argparse._HelpAction, argparse._VersionAction))


def _option(action) -> OptionSpec:
    choices = tuple(action.choices) if action.choices else None
    return OptionSpec(
        dest=action.dest,
        flags=tuple(action.option_strings),
        help=action.help or "",
        choices=choices,
        is_flag=action.nargs == 0,
        is_int=action.type is int,
        required=bool(action.required),
        metavar=action.metavar,
    )


def walk(parser: argparse.ArgumentParser, path: Sequence[str] = ()) -> List[CommandSpec]:
    """Return one :class:`CommandSpec` for every runnable subcommand.

    A parser whose subcommands themselves take subcommands, such as ``plan``
    and ``track``, contributes only its leaves, because only a leaf runs.
    """
    inherited = [
        _option(a) for a in parser._actions
        if not _skip(a) and not _is_subparsers(a)
    ]
    leaves: List[CommandSpec] = []
    found_sub = False
    for action in parser._actions:
        if not _is_subparsers(action):
            continue
        found_sub = True
        for name, sub in action.choices.items():
            leaves += walk(sub, tuple(path) + (name,))
    if found_sub:
        return leaves
    return [CommandSpec(path=tuple(path), help=parser.description or "",
                        options=tuple(inherited))]


def commands(parser: argparse.ArgumentParser) -> Dict[str, CommandSpec]:
    """Return the subcommands of ``parser`` keyed by their space-joined name."""
    return {spec.name: spec for spec in walk(parser)}


def table_dest(spec: CommandSpec) -> Optional[str]:
    """Return the dest of the option naming a weekly org table, or ``None``.

    A dest called ``table`` always names one. A positional called ``path``
    sometimes does, and the parser's own help says which, so ``plan import``
    ("the weekly org table") is told apart from ``track import`` ("the actuals
    file") without keeping a second list of command names in step by hand.
    """
    for option in spec.options:
        if option.dest == "table":
            return option.dest
    for option in spec.options:
        if option.dest == "path" and "org table" in (option.help or "").lower():
            return option.dest
    return None


def to_argv(spec: CommandSpec, values: Dict[str, object]) -> List[str]:
    """Build the argument list for ``spec`` from ``values``, keyed by dest.

    A value of ``None`` omits the option, and a false flag omits it too, which
    matches the defaults of the command line. An empty string is a value rather
    than an omission, because ``writing-schedule --tz ""`` asks for floating
    calendar times. A field that means "leave this out" returns ``None``.
    Positionals come first, in the order the parser declares them, so the
    result parses.
    """
    argv: List[str] = list(spec.path)
    for opt in spec.options:
        if not opt.positional:
            continue
        value = values.get(opt.dest)
        if value is not None:
            argv.append(str(value))
    for opt in spec.options:
        if opt.positional:
            continue
        value = values.get(opt.dest)
        if opt.is_flag:
            if value:
                argv.append(opt.flag)
            continue
        if value is None or value is False:
            continue
        argv += [opt.flag, str(value)]
    return argv


def command_string(prog: str, argv: Sequence[str]) -> str:
    """Return the shell command a user could paste, with quoting where needed."""
    return " ".join(shlex.quote(word) for word in [prog, *argv])


def missing_required(spec: CommandSpec, values: Dict[str, object]) -> List[str]:
    """Return the labels of the required arguments that carry no value."""
    missing = []
    for opt in spec.options:
        if not opt.required and not opt.positional:
            continue
        if opt.is_flag:
            continue
        if values.get(opt.dest) in (None, "", False):
            missing.append(opt.flag)
    return missing
