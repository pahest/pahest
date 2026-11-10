"""Templates: the HTML, CSS and JavaScript of the pages and reports are files in templates/.

A small subset of Mustache (https://mustache.github.io), enough for these files and nothing more:

  {{name}}            a value, HTML-escaped
  {{{name}}}          a value as it is (HTML made elsewhere, CSS, JSON for a script)
  {{#name}}…{{/name}} a section: once per item of a list (the item's fields can be used inside, the
                      item itself is {{.}}), or once if the value is true (a dict's fields can be used)
  {{^name}}…{{/name}} shown when the value is missing, empty or false
  {{> file}}          another template file, with the same values
  {{! note}}          a comment, left out

A name is looked up in the innermost section first, then outwards. A section, partial or comment tag
alone on a line leaves no empty line behind.
"""
from __future__ import annotations

import functools
import html
import re
from pathlib import Path
from typing import List, Tuple

FOLDER = Path(__file__).resolve().parent / "templates"
_ALONE = re.compile(r"^[ \t]*(\{\{[#^/!>][^{}]*\}\})[ \t]*\n", re.M)
_TAG = re.compile(r"\{\{\{\s*([\w.]+)\s*\}\}\}|\{\{([#^/!>]?)\s*(.*?)\s*\}\}", re.S)


class TemplateError(ValueError):
    pass


def source(name: str) -> str:
    """The text of a template file."""
    return (FOLDER / name).read_text(encoding="utf-8")


def _parse(text: str, name: str) -> list:
    """The template as a tree: text, ("var", name, raw), ("section", name, inverted, children),
    ("partial", file)."""
    text = _ALONE.sub(r"\1", text)
    root: list = []
    stack: List[Tuple[str, list]] = [("", root)]
    pos = 0
    for m in _TAG.finditer(text):
        out = stack[-1][1]
        if m.start() > pos:
            out.append(text[pos:m.start()])
        pos = m.end()
        raw, kind, key = m.group(1), m.group(2), m.group(3)
        if raw:
            out.append(("var", raw, True))
        elif kind == "":
            out.append(("var", key, False))
        elif kind in "#^":
            children: list = []
            out.append(("section", key, kind == "^", children))
            stack.append((key, children))
        elif kind == "/":
            if len(stack) == 1 or stack[-1][0] != key:
                raise TemplateError(f"{name}: {{{{/{key}}}}} does not close {{{{#{stack[-1][0]}}}}}")
            stack.pop()
        elif kind == ">":
            out.append(("partial", key))
    if len(stack) > 1:
        raise TemplateError(f"{name}: {{{{#{stack[-1][0]}}}}} is never closed")
    if pos < len(text):
        root.append(text[pos:])
    return root


@functools.lru_cache(maxsize=None)
def _tree(name: str) -> list:
    return _parse(source(name), name)


def _find(key: str, scopes: list):
    if key == ".":
        return scopes[-1]
    for scope in reversed(scopes):
        if isinstance(scope, dict) and key in scope:
            return scope[key]
    return None


def _render(tree: list, scopes: list, out: List[str]) -> None:
    for node in tree:
        if isinstance(node, str):
            out.append(node)
        elif node[0] == "var":
            v = _find(node[1], scopes)
            if v is not None and v is not False:
                out.append(str(v) if node[2] else html.escape(str(v)))
        elif node[0] == "partial":
            _render(_tree(node[1]), scopes, out)
        else:
            _, key, inverted, children = node
            v = _find(key, scopes)
            if inverted:
                if not v:
                    _render(children, scopes, out)
            elif isinstance(v, (list, tuple)):
                for item in v:
                    _render(children, scopes + [item], out)
            elif v:
                _render(children, scopes + [v] if isinstance(v, dict) else scopes, out)


def render(name: str, values: dict) -> str:
    """The template file `name`, filled in with `values`."""
    out: List[str] = []
    _render(_tree(name), [values], out)
    return "".join(out)
