"""Compact, deterministic retrieval over a live MCP tool catalog."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from langchain_core.tools import BaseTool


_WORD = re.compile(r"[a-z0-9]+")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_SERVER_PREFIX = re.compile(r"^MCP server:\s*([^.]+)\.\s*", re.IGNORECASE)
_STOP_WORDS = frozenset(
    {
        # English
        "a",
        "an",
        "and",
        "are",
        "for",
        "from",
        "in",
        "is",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
        # French
        "au",
        "aux",
        "avec",
        "dans",
        "de",
        "des",
        "du",
        "en",
        "et",
        "la",
        "le",
        "les",
        "ou",
        "par",
        "pour",
        "sur",
        "un",
        "une",
    }
)
_FIELD_WEIGHTS = {
    "server": 8.0,
    "name": 6.0,
    "arguments": 3.0,
    "description": 1.0,
}
_BM25_K1 = 1.2
_BM25_B = 0.75


def search_tokens(value: str) -> tuple[str, ...]:
    """Normalize prose and identifiers into stable FR/EN search terms."""
    split_camel = _CAMEL_BOUNDARY.sub(" ", value.replace("_", " ").replace("-", " "))
    folded = unicodedata.normalize("NFKD", split_camel.casefold())
    ascii_value = "".join(char for char in folded if not unicodedata.combining(char))
    return tuple(
        token
        for token in _WORD.findall(ascii_value)
        if len(token) > 1 and token not in _STOP_WORDS
    )


def _tool_schema(tool: BaseTool) -> dict[str, Any]:
    try:
        schema = tool.get_input_jsonschema()
    except AttributeError, TypeError, ValueError:
        return {}
    return schema if isinstance(schema, dict) else {}


def _schema_terms(schema: dict[str, Any]) -> tuple[tuple[str, ...], str]:
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return (), ""
    required = set(schema.get("required") or [])
    tokens: list[str] = []
    signatures: list[str] = []
    for name, raw in properties.items():
        field = raw if isinstance(raw, dict) else {}
        kind = field.get("type")
        if isinstance(kind, list):
            kind = "|".join(str(item) for item in kind)
        if not isinstance(kind, str):
            kind = "value"
        enum = field.get("enum")
        enum_suffix = ""
        if isinstance(enum, list) and enum:
            compact_enum = "|".join(str(item)[:24] for item in enum[:4])
            enum_suffix = f"={compact_enum}"
        signatures.append(
            f"{name}:{kind}{'!' if name in required else ''}{enum_suffix}"
        )
        tokens.extend(search_tokens(name))
        description = field.get("description")
        if isinstance(description, str):
            tokens.extend(search_tokens(description[:240]))
        if isinstance(enum, list):
            tokens.extend(
                token for item in enum[:12] for token in search_tokens(str(item)[:80])
            )
    return tuple(tokens), ", ".join(signatures[:8])


def tool_server_name(tool: BaseTool) -> str:
    """The MCP server a bound tool came from (`Toolset.open` stamps it)."""
    metadata = tool.metadata if isinstance(tool.metadata, dict) else {}
    server = metadata.get("auxilia_mcp_server")
    if isinstance(server, str) and server:
        return server
    match = _SERVER_PREFIX.match(" ".join((tool.description or "").split()))
    return match.group(1).strip() if match else tool.name.split("_", 1)[0]


def _server_description(tool: BaseTool) -> tuple[str, str, str]:
    server = tool_server_name(tool)
    description = " ".join((tool.description or "").split())
    match = _SERVER_PREFIX.match(description)
    if match:
        description = description[match.end() :]
    return server, description[:300], description[:2000]


@dataclass(frozen=True)
class ToolDocument:
    name: str
    server: str
    summary: str
    argument_signature: str
    position: int
    fields: dict[str, tuple[str, ...]]

    @property
    def compact_signature(self) -> str:
        detail = f" — {self.summary}" if self.summary else ""
        arguments = (
            f" | args: {self.argument_signature}" if self.argument_signature else ""
        )
        return f"{self.name} [{self.server}]{detail}{arguments}"


@dataclass(frozen=True)
class SearchHit:
    document: ToolDocument
    score: float
    coverage: float
    exact: bool


@dataclass(frozen=True)
class SearchResult:
    hits: tuple[SearchHit, ...]
    confident: bool
    margin: float
    total_hits: int


class ToolCatalog:
    """An immutable BM25F index whose records never contain full JSON schemas."""

    def __init__(self, tools: list[BaseTool]) -> None:
        documents: list[ToolDocument] = []
        for position, tool in enumerate(tools):
            server, summary, description = _server_description(tool)
            argument_terms, argument_signature = _schema_terms(_tool_schema(tool))
            documents.append(
                ToolDocument(
                    name=tool.name,
                    server=server,
                    summary=summary,
                    argument_signature=argument_signature,
                    position=position,
                    fields={
                        "server": search_tokens(server),
                        "name": search_tokens(tool.name),
                        "arguments": argument_terms,
                        "description": search_tokens(description),
                    },
                )
            )
        self.documents = tuple(documents)
        self.by_name = {document.name: document for document in documents}
        grouped: dict[str, list[ToolDocument]] = defaultdict(list)
        for document in documents:
            grouped[document.server].append(document)
        self.by_server = {
            server: tuple(server_documents)
            for server, server_documents in grouped.items()
        }
        self._field_lengths = {
            field: tuple(len(document.fields[field]) for document in documents)
            for field in _FIELD_WEIGHTS
        }
        self._average_lengths = {
            field: (
                sum(lengths) / len(lengths) if lengths and sum(lengths) > 0 else 1.0
            )
            for field, lengths in self._field_lengths.items()
        }
        document_frequency: Counter[str] = Counter()
        for document in documents:
            terms = {
                term for field_terms in document.fields.values() for term in field_terms
            }
            document_frequency.update(terms)
        self._document_frequency = document_frequency

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self.by_name)

    def server_index(self) -> str:
        lines = []
        for server, documents in self.by_server.items():
            summaries = [document.summary for document in documents if document.summary]
            sample = "; ".join(dict.fromkeys(summaries[:2]))
            detail = f": {sample[:220]}" if sample else ""
            lines.append(f"- {server} ({len(documents)} tools){detail}")
        return "\n".join(lines)

    def compact_signatures(
        self, names: list[str] | tuple[str, ...], *, limit: int
    ) -> str:
        documents = (
            self.by_name[name] for name in dict.fromkeys(names) if name in self.by_name
        )
        return "\n".join(
            f"- {document.compact_signature}"
            for document in list(documents)[: max(1, limit)]
        )

    def search(
        self,
        query: str,
        *,
        limit: int = 12,
        servers: set[str] | None = None,
    ) -> SearchResult:
        query_terms = tuple(dict.fromkeys(search_tokens(query[:1000])))
        if not query_terms or not self.documents:
            return SearchResult(
                hits=(),
                confident=False,
                margin=0.0,
                total_hits=0,
            )

        normalized_query = " ".join(query_terms)
        hits: list[SearchHit] = []
        total_documents = len(self.documents)
        for document in self.documents:
            if servers is not None and document.server not in servers:
                continue
            score = 0.0
            matched: set[str] = set()
            for field, weight in _FIELD_WEIGHTS.items():
                terms = document.fields[field]
                if not terms:
                    continue
                frequencies = Counter(terms)
                average_length = self._average_lengths[field]
                length_norm = 1 - _BM25_B + _BM25_B * len(terms) / average_length
                for term in query_terms:
                    frequency = frequencies.get(term, 0)
                    if not frequency:
                        continue
                    matched.add(term)
                    document_frequency = self._document_frequency[term]
                    inverse_frequency = math.log(
                        1
                        + (total_documents - document_frequency + 0.5)
                        / (document_frequency + 0.5)
                    )
                    score += (
                        weight
                        * inverse_frequency
                        * frequency
                        * (_BM25_K1 + 1)
                        / (frequency + _BM25_K1 * length_norm)
                    )

            normalized_name = " ".join(document.fields["name"])
            normalized_server = " ".join(document.fields["server"])
            exact = normalized_query in {normalized_name, normalized_server}
            if normalized_query and normalized_query in normalized_name:
                score += 18.0
                exact = True
            elif normalized_query and normalized_query in normalized_server:
                score += 12.0
                exact = True
            if score <= 0:
                continue
            hits.append(
                SearchHit(
                    document=document,
                    score=score,
                    coverage=len(matched) / len(query_terms),
                    exact=exact,
                )
            )

        hits.sort(key=lambda hit: (-hit.score, hit.document.position))
        bounded = tuple(hits[: max(1, limit)])
        top = bounded[0] if bounded else None
        runner_up = bounded[1] if len(bounded) > 1 else None
        margin = (
            1.0
            if top is not None and runner_up is None
            else (top.score - runner_up.score) / top.score
            if top is not None and runner_up is not None and top.score > 0
            else 0.0
        )
        confident = bool(
            top
            and (
                top.exact
                or top.coverage >= 0.6
                or (top.coverage >= 0.4 and margin >= 0.25)
            )
        )
        return SearchResult(
            hits=bounded,
            confident=confident,
            margin=margin,
            total_hits=len(hits),
        )

    def browse(
        self,
        *,
        server: str | None,
        offset: int,
        limit: int,
    ) -> tuple[ToolDocument, ...]:
        if server is None:
            documents = self.documents
        else:
            resolved = next(
                (
                    name
                    for name in self.by_server
                    if name.casefold() == server.strip().casefold()
                ),
                None,
            )
            documents = self.by_server.get(resolved, ()) if resolved else ()
        start = max(0, offset)
        return tuple(documents[start : start + max(1, limit)])

    @staticmethod
    def diversify(hits: tuple[SearchHit, ...], limit: int) -> tuple[SearchHit, ...]:
        """Keep several intents without letting one server consume the budget."""
        selected: list[SearchHit] = []
        deferred: list[SearchHit] = []
        per_server: Counter[str] = Counter()
        for hit in hits:
            if per_server[hit.document.server] < 2:
                selected.append(hit)
                per_server[hit.document.server] += 1
            else:
                deferred.append(hit)
            if len(selected) == limit:
                return tuple(selected)
        selected.extend(deferred[: max(0, limit - len(selected))])
        return tuple(selected)
