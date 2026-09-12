"""Build a small, auditable RTL module hierarchy for model context.

This is deliberately not a Verilog compiler. Yosys remains the authority for
elaboration. The scanner only extracts module spans, port directions, and
named module instantiations from the already validated source files. Unknown
or positional connections are marked incomplete instead of being guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

from orchestrator.config import ProjectConfiguration
from orchestrator.schemas.ai import ModuleConnection, PortConnection

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
_MODULE = re.compile(r"\bmodule\s+([A-Za-z_][A-Za-z0-9_$]*)\b")
_ENDMODULE = re.compile(r"\bendmodule\b")
_DIRECTION = re.compile(r"\b(input|output|inout)\b")
_DECL = re.compile(r"\b(input|output|inout)\b([^;]*);", re.DOTALL)
_DECL_KEYWORDS = {
    "wire", "reg", "logic", "signed", "unsigned", "tri", "wand", "wor",
    "supply0", "supply1", "integer", "time", "var",
}


@dataclass
class RTLModule:
    name: str
    file: str
    line_start: int
    line_end: int
    ports: dict[str, str] = field(default_factory=dict)


@dataclass
class RTLHierarchy:
    modules: dict[str, RTLModule]
    connections: list[ModuleConnection]

    def module_at(self, file: str, line: int | None) -> RTLModule | None:
        normal = Path(file).as_posix()
        candidates = [
            module for module in self.modules.values()
            if Path(module.file).as_posix() == normal
        ]
        if line is not None:
            for module in candidates:
                if module.line_start <= line <= module.line_end:
                    return module
        return candidates[0] if len(candidates) == 1 else None


def _strip_comments(text: str) -> str:
    """Remove comments while preserving offsets and line numbers."""
    def block(match: re.Match[str]) -> str:
        value = match.group(0)
        return "".join("\n" if char == "\n" else " " for char in value)

    text = re.sub(r"/\*.*?\*/", block, text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", lambda m: " " * len(m.group(0)), text)


def _balanced_end(text: str, start: int) -> int | None:
    if start >= len(text) or text[start] != "(":
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
    return None


def _names_from_declaration(fragment: str) -> list[str]:
    fragment = re.sub(r"\[[^\]]*\]", " ", fragment)
    names: list[str] = []
    for piece in fragment.split(","):
        piece = piece.split("=")[0]
        tokens = [
            token for token in _IDENT.findall(piece)
            if token not in _DECL_KEYWORDS
        ]
        if tokens:
            names.append(tokens[-1])
    return names


def _parse_ports(module_text: str, header_end: int) -> dict[str, str]:
    ports: dict[str, str] = {}
    header = module_text[:header_end]
    # For non-ANSI modules, body declarations are ports only when their names
    # appeared in the module header. This prevents an ``input`` declaration in
    # a nested function/task from being mistaken for a module port.
    port_list_start = header.rfind("(")
    declared_header_names = set(
        _IDENT.findall(header[port_list_start + 1:])
        if port_list_start >= 0 else []
    )
    direction_matches = list(_DIRECTION.finditer(header))
    for index, match in enumerate(direction_matches):
        end = (
            direction_matches[index + 1].start()
            if index + 1 < len(direction_matches)
            else len(header)
        )
        for name in _names_from_declaration(header[match.end():end]):
            ports[name] = match.group(1)

    for match in _DECL.finditer(module_text[header_end:]):
        for name in _names_from_declaration(match.group(2)):
            if name in declared_header_names:
                ports[name] = match.group(1)
    return ports


def _module_spans(file: str, text: str) -> list[tuple[RTLModule, int, int, str]]:
    clean = _strip_comments(text)
    result: list[tuple[RTLModule, int, int, str]] = []
    cursor = 0
    while match := _MODULE.search(clean, cursor):
        end_match = _ENDMODULE.search(clean, match.end())
        if end_match is None:
            break
        start, end = match.start(), end_match.end()
        module_text = clean[start:end]
        header_end = module_text.find(";")
        if header_end < 0:
            cursor = end
            continue
        module = RTLModule(
            name=match.group(1),
            file=file,
            line_start=clean.count("\n", 0, start) + 1,
            line_end=clean.count("\n", 0, end) + 1,
            ports=_parse_ports(module_text, header_end),
        )
        result.append((module, start, end, module_text))
        cursor = end
    return result


def _skip_space(text: str, index: int) -> int:
    while index < len(text) and text[index].isspace():
        index += 1
    return index


def _named_ports(arguments: str) -> tuple[dict[str, str], bool]:
    mapping: dict[str, str] = {}
    index = 0
    named_only = True
    while index < len(arguments):
        index = _skip_space(arguments, index)
        if index < len(arguments) and arguments[index] == ",":
            index += 1
            continue
        match = re.match(r"\.\s*([A-Za-z_][A-Za-z0-9_$]*)\s*", arguments[index:])
        if match is None:
            if arguments[index:].strip():
                named_only = False
            break
        port = match.group(1)
        index += match.end()
        if index >= len(arguments) or arguments[index] != "(":
            named_only = False
            break
        end = _balanced_end(arguments, index)
        if end is None:
            named_only = False
            break
        mapping[port] = " ".join(arguments[index + 1:end].split())
        index = end + 1
    return mapping, named_only


def _find_instances(
    parent: RTLModule,
    module_text: str,
    known: dict[str, RTLModule],
) -> list[ModuleConnection]:
    connections: list[ModuleConnection] = []
    header_end = module_text.find(";") + 1
    body = module_text[header_end:]
    for child_name, child in known.items():
        if child_name == parent.name:
            continue
        pattern = re.compile(rf"\b{re.escape(child_name)}\b")
        cursor = 0
        while match := pattern.search(body, cursor):
            index = _skip_space(body, match.end())
            if index < len(body) and body[index] == "#":
                index = _skip_space(body, index + 1)
                param_end = _balanced_end(body, index)
                if param_end is None:
                    cursor = match.end()
                    continue
                index = _skip_space(body, param_end + 1)
            instance_match = _IDENT.match(body, index)
            if instance_match is None:
                cursor = match.end()
                continue
            instance = instance_match.group(0)
            index = _skip_space(body, instance_match.end())
            args_end = _balanced_end(body, index)
            if args_end is None:
                cursor = match.end()
                continue
            after = _skip_space(body, args_end + 1)
            if after >= len(body) or body[after] != ";":
                cursor = args_end + 1
                continue

            mapping, named_only = _named_ports(body[index + 1:args_end])
            missing = sorted(
                port for port in child.ports
                if port not in mapping or not mapping[port]
            )
            ports = []
            for port, signal in mapping.items():
                direction = child.ports.get(port)
                flow = {
                    "input": "parent_to_child",
                    "output": "child_to_parent",
                    "inout": "inout",
                }.get(direction, "unknown")
                ports.append(PortConnection(port=port, signal=signal, direction=flow))
            line = parent.line_start + module_text.count(
                "\n", 0, header_end + match.start()
            )
            connections.append(ModuleConnection(
                parent_module=parent.name,
                parent_file=parent.file,
                child_module=child.name,
                child_file=child.file,
                instance=instance,
                line=line,
                ports=ports,
                unconnected_ports=missing,
                complete=named_only and not missing and bool(mapping),
            ))
            cursor = after + 1
    return connections


def build_rtl_hierarchy(config: ProjectConfiguration) -> RTLHierarchy:
    """Scan every declared RTL file and return modules plus hierarchy edges."""
    spans: list[tuple[RTLModule, int, int, str]] = []
    for entry in config.design.file_list:
        path = config.resolve(entry.path)
        if not path.exists():
            continue
        spans.extend(_module_spans(
            Path(entry.path).as_posix(),
            path.read_text(encoding="utf-8", errors="replace"),
        ))
    modules = {module.name: module for module, *_ in spans}
    connections: list[ModuleConnection] = []
    for parent, _start, _end, module_text in spans:
        connections.extend(_find_instances(parent, module_text, modules))
    return RTLHierarchy(modules=modules, connections=connections)
