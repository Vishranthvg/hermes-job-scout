"""YAML loader: PyYAML when available, otherwise a small indent-based subset."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def _strip_yaml_comment(line: str) -> str:
    in_quote = None
    escaped = False
    for i, ch in enumerate(line):
        if in_quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == in_quote:
                in_quote = None
            continue
        if ch in ("'", '"'):
            in_quote = ch
        elif ch == "#":
            return line[:i].rstrip()
    return line.rstrip()


def _parse_yaml_scalar(raw: str) -> Any:
    s = raw.strip()
    if s == "" or s in ("null", "Null", "NULL", "~"):
        return None
    if s in ("true", "True", "TRUE", "yes", "Yes"):
        return True
    if s in ("false", "False", "FALSE", "no", "No"):
        return False
    if (len(s) >= 2) and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")):
        return s[1:-1]
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if re.fullmatch(r"-?\d+\.\d+", s):
        return float(s)
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        return [_parse_yaml_scalar(p.strip()) for p in inner.split(",") if p.strip()]
    return s


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def parse_yaml_text(text: str) -> Any:
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text)
    except ImportError:
        pass
    body = [_strip_yaml_comment(line) for line in text.splitlines()]
    if not any(ln.strip() for ln in body):
        return {}
    value, _idx = _parse_block(body, 0, 0)
    return {} if value is None else value


def load_yaml_file(path: Path) -> Any:
    return parse_yaml_text(path.read_text(encoding="utf-8"))


def _parse_block(lines: list[str], start: int, min_indent: int) -> tuple[Any, int]:
    i = start
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines):
        return None, i
    indent = _indent(lines[i])
    if indent < min_indent:
        return None, i
    if lines[i].lstrip().startswith("- "):
        return _parse_list(lines, i, indent)
    return _parse_map(lines, i, indent)


def _parse_list(lines: list[str], start: int, indent: int) -> tuple[list[Any], int]:
    items: list[Any] = []
    i = start
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        ind = _indent(lines[i])
        if ind < indent:
            break
        stripped = lines[i].lstrip()
        if not stripped.startswith("- "):
            break
        rest = stripped[2:].strip()
        if not rest:
            value, i = _parse_block(lines, i + 1, indent + 1)
            items.append(value)
            continue
        if ":" in rest and not rest.startswith(("'", '"')):
            key, _, raw = rest.partition(":")
            node: dict[str, Any] = {}
            if raw.strip():
                node[key.strip()] = _parse_yaml_scalar(raw.strip())
                i += 1
            else:
                value, i = _parse_block(lines, i + 1, indent + 1)
                node[key.strip()] = value
            if i < len(lines) and lines[i].strip() and not lines[i].lstrip().startswith("- "):
                if _indent(lines[i]) > indent:
                    child, i = _parse_map(lines, i, _indent(lines[i]))
                    node.update(child)
            items.append(node)
        else:
            items.append(_parse_yaml_scalar(rest))
            i += 1
    return items, i


def _parse_map(lines: list[str], start: int, indent: int) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    i = start
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        ind = _indent(lines[i])
        if ind < indent:
            break
        if ind > indent:
            raise ValueError(f"YAML indent error on line {i + 1}: {lines[i]!r}")
        stripped = lines[i].lstrip()
        if stripped.startswith("- "):
            break
        if ":" not in stripped:
            raise ValueError(f"YAML expected a key: value on line {i + 1}: {lines[i]!r}")
        key, _, raw = stripped.partition(":")
        raw = raw.strip()
        if raw:
            result[key.strip()] = _parse_yaml_scalar(raw)
            i += 1
        else:
            value, i = _parse_block(lines, i + 1, indent + 1)
            result[key.strip()] = {} if value is None else value
    return result, i
