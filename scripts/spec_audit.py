#!/usr/bin/env python3
"""
Audit local field allowlists against the live Semantic Scholar API spec.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from semantic_scholar.config import (  # noqa: E402
    AuthorDetailFields,
    CitationReferenceFields,
    PaperFields,
)

SPEC_URLS = [
    "https://api.semanticscholar.org/graph/v1/swagger",
    "https://api.semanticscholar.org/graph/v1/openapi.json",
    "https://api.semanticscholar.org/graph/v1/swagger.json",
]
TIMEOUT_SECONDS = 20.0


class SpecFormatError(Exception):
    """Raised when the upstream spec shape is not recognized."""


def fetch_spec() -> dict[str, Any] | None:
    errors: list[str] = []
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True) as client:
            for url in SPEC_URLS:
                try:
                    response = client.get(url, headers={"Accept": "application/json"})
                    response.raise_for_status()
                    payload = response.json()
                    if not isinstance(payload, dict):
                        errors.append(f"{url}: expected JSON object, got {type(payload).__name__}")
                        continue
                    return payload
                except (httpx.HTTPError, ValueError) as exc:
                    errors.append(f"{url}: {exc}")
    except Exception as exc:  # pragma: no cover - final safety net for transient client issues
        print(f"Warning: unable to initialize HTTP client: {exc}")
        return None

    print("Warning: unable to fetch Semantic Scholar API spec.")
    for error in errors:
        print(f"  - {error}")
    return None


def build_registry(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    definitions = spec.get("definitions")
    if isinstance(definitions, dict):
        return {name: schema for name, schema in definitions.items() if isinstance(schema, dict)}

    components = spec.get("components")
    if isinstance(components, dict):
        schemas = components.get("schemas")
        if isinstance(schemas, dict):
            return {name: schema for name, schema in schemas.items() if isinstance(schema, dict)}

    raise SpecFormatError("spec does not contain Swagger definitions or OpenAPI components.schemas")


def ref_name(ref: str) -> str:
    return ref.rsplit("/", 1)[-1]


def collect_properties(
    schema: dict[str, Any] | None,
    registry: dict[str, dict[str, Any]],
    seen_refs: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return {}

    seen_refs = seen_refs or set()
    properties: dict[str, Any] = {}

    ref = schema.get("$ref")
    if isinstance(ref, str):
        if ref in seen_refs:
            return {}
        target = registry.get(ref_name(ref))
        if isinstance(target, dict):
            properties.update(collect_properties(target, registry, seen_refs | {ref}))

    all_of = schema.get("allOf")
    if isinstance(all_of, list):
        for part in all_of:
            properties.update(collect_properties(part, registry, seen_refs))

    schema_properties = schema.get("properties")
    if isinstance(schema_properties, dict):
        properties.update(schema_properties)

    return properties


def find_schemas(
    registry: dict[str, dict[str, Any]],
    candidates: list[str],
) -> list[dict[str, Any]]:
    lower_names = {name.lower(): name for name in registry}
    matches: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    for candidate in candidates:
        matched_name = registry.get(candidate)
        if matched_name is None:
            actual_name = lower_names.get(candidate.lower())
            if actual_name is None:
                continue
            matched_name = registry[actual_name]
            schema_name = actual_name
        else:
            schema_name = candidate

        if schema_name in seen_names:
            continue
        seen_names.add(schema_name)
        matches.append(matched_name)

    return matches


def property_names_for_schemas(
    registry: dict[str, dict[str, Any]],
    candidates: list[str],
) -> set[str]:
    names: set[str] = set()
    schemas = find_schemas(registry, candidates)
    for schema in schemas:
        names.update(collect_properties(schema, registry).keys())
    return names


def extract_upstream_fields(spec: dict[str, Any]) -> dict[str, set[str]]:
    registry = build_registry(spec)

    paper_fields = property_names_for_schemas(
        registry,
        ["FullPaper", "PaperWithLinks", "BasePaper"],
    )
    if not paper_fields:
        raise SpecFormatError("unable to find paper schema definitions")

    author_schemas = find_schemas(
        registry,
        ["AuthorWithPapers", "AuthorDetail", "Author"],
    )
    author_fields: set[str] = set()
    paper_subfields: set[str] = set()
    for schema in author_schemas:
        properties = collect_properties(schema, registry)
        author_fields.update(properties.keys())
        papers_property = properties.get("papers")
        if isinstance(papers_property, dict):
            paper_subfields.update(
                collect_properties(papers_property.get("items"), registry).keys()
            )
    if not author_fields:
        raise SpecFormatError("unable to find author schema definitions")
    author_fields.update({f"papers.{name}" for name in paper_subfields})

    citation_fields: set[str] = set()
    citation_schemas = find_schemas(registry, ["Citation", "Reference", "CitationReference"])
    for schema in citation_schemas:
        properties = collect_properties(schema, registry)
        for name, property_schema in properties.items():
            if name in {"citingPaper", "citedPaper", "paper"}:
                citation_fields.update(collect_properties(property_schema, registry).keys())
            else:
                citation_fields.add(name)
    if not citation_fields:
        raise SpecFormatError("unable to find citation/reference schema definitions")

    return {
        "PaperFields.VALID_FIELDS": paper_fields,
        "AuthorDetailFields.VALID_FIELDS": author_fields,
        "CitationReferenceFields.VALID_FIELDS": citation_fields,
    }


def report_drift(name: str, local_fields: set[str], upstream_fields: set[str]) -> bool:
    missing = sorted(upstream_fields - local_fields)
    stale = sorted(local_fields - upstream_fields)
    if not missing and not stale:
        print(f"{name}: OK")
        return False

    print(f"{name}: DRIFT DETECTED")
    if missing:
        print("  New upstream fields missing locally:")
        for field in missing:
            print(f"    - {field}")
    if stale:
        print("  Local fields not present upstream:")
        for field in stale:
            print(f"    - {field}")
    return True


def main() -> int:
    spec = fetch_spec()
    if spec is None:
        return 0

    try:
        upstream_fields = extract_upstream_fields(spec)
    except SpecFormatError as exc:
        print(f"Warning: unexpected spec format: {exc}")
        return 0
    except Exception as exc:  # pragma: no cover - defensive fallback
        print(f"Warning: failed to parse Semantic Scholar API spec: {exc}")
        return 0

    local_field_sets = {
        "PaperFields.VALID_FIELDS": set(PaperFields.VALID_FIELDS),
        "AuthorDetailFields.VALID_FIELDS": set(AuthorDetailFields.VALID_FIELDS),
        "CitationReferenceFields.VALID_FIELDS": set(CitationReferenceFields.VALID_FIELDS),
    }

    drift_detected = False
    for name, local_fields in local_field_sets.items():
        drift_detected |= report_drift(name, local_fields, upstream_fields[name])

    if drift_detected:
        print("Semantic Scholar API spec drift detected.")
        return 1

    print("No Semantic Scholar API spec drift detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
