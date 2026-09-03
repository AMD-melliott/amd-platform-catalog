"""Extract list-table data out of ROCm/LLVM RST docs via docutils.

Uses a real RST parse (not line-based indentation matching) so inline markup
(``literal``, line-block continuations, etc.) inside cells doesn't break
extraction. ROCm's docs use two sphinx-design directives docutils doesn't
know natively -- ``tab-set`` / ``tab-item`` -- so we register minimal stub
directives that just parse their content as a plain container and stash the
tab title, which lets nested ``list-table``\\ s parse normally.
"""

from __future__ import annotations

import dataclasses
import io
from typing import ClassVar

from docutils import nodes
from docutils.frontend import get_default_settings
from docutils.parsers.rst import Directive, Parser, directives
from docutils.utils import new_document


class _TabSet(Directive):
    has_content = True

    def run(self) -> list[nodes.Node]:
        node = nodes.container()
        self.state.nested_parse(self.content, self.content_offset, node)
        return [node]


class _TabItem(Directive):
    has_content = True
    required_arguments = 1
    optional_arguments = 0
    final_argument_whitespace = True
    option_spec: ClassVar = {"sync": directives.unchanged, "name": directives.unchanged}

    def run(self) -> list[nodes.Node]:
        node = nodes.container()
        node["tab_item_title"] = self.arguments[0].strip()
        self.state.nested_parse(self.content, self.content_offset, node)
        return [node]


_directives_registered = False


def _register_stub_directives() -> None:
    global _directives_registered
    if _directives_registered:
        return
    directives.register_directive("tab-set", _TabSet)
    directives.register_directive("tab-item", _TabItem)
    _directives_registered = True


@dataclasses.dataclass
class Table:
    """One parsed ``list-table``."""

    names: list[str]
    tab_item_title: str | None
    header: list[str]
    rows: list[list[str]]


def parse_rst(text: str) -> nodes.document:
    _register_stub_directives()
    settings = get_default_settings(Parser)
    # ROCm/Sphinx-only roles (:doc:, :ref:) are unknown to plain docutils;
    # they land as system_message/problematic nodes rather than raising, so
    # silence the report stream instead of letting it spam stderr.
    settings.report_level = 5
    settings.halt_level = 5
    settings.warning_stream = io.StringIO()
    document = new_document("<rst>", settings=settings)
    Parser().parse(text, document)
    return document


def _enclosing_tab_item_title(table_node: nodes.Element) -> str | None:
    parent = table_node.parent
    while parent is not None:
        if isinstance(parent, nodes.container) and "tab_item_title" in parent.attributes:
            return parent["tab_item_title"]
        parent = parent.parent
    return None


def _clean_cell_text(text: str) -> str:
    # RST source uses U+00A0 (non-breaking space) for typographic line-break
    # avoidance (e.g. "2\xa0CUs"); normalize it so catalog data doesn't carry
    # invisible-diff characters.
    return " ".join(text.replace("\xa0", " ").split())


def _entry_text(entry: nodes.Element) -> str:
    # An unknown directive/role failing *inside* a cell (e.g. LLVM's docs
    # use ".. TODO::") embeds a multi-line system_message with the parser's
    # error text right there in the doctree, which astext() would otherwise
    # include verbatim in the extracted cell. Strip those nodes first.
    for system_message in list(entry.findall(nodes.system_message)):
        system_message.parent.remove(system_message)
    return entry.astext()


def _row_cells(row: nodes.Element) -> list[str]:
    return [_clean_cell_text(_entry_text(entry)) for entry in row.findall(nodes.entry)]


def extract_list_tables(text: str) -> list[Table]:
    document = parse_rst(text)
    tables: list[Table] = []
    for table_node in document.findall(nodes.table):
        tgroup = next(table_node.findall(nodes.tgroup))
        thead = next(tgroup.findall(nodes.thead), None)
        tbody = next(tgroup.findall(nodes.tbody))
        header = _row_cells(next(thead.findall(nodes.row))) if thead is not None else []
        rows = [_row_cells(row) for row in tbody.findall(nodes.row)]
        tables.append(
            Table(
                names=list(table_node.get("names", [])),
                tab_item_title=_enclosing_tab_item_title(table_node),
                header=header,
                rows=rows,
            )
        )
    return tables
