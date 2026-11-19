"""Allele frequencies from gnomAD, the Genome Aggregation Database, through its public API.

gnomAD aggregates exomes and genomes from hundreds of thousands of people; its v4 frequencies
are what clinical labs read to decide whether a variant is too common to cause a rare disease.
The data are released under CC0. The API is meant for interactive use and allows about 10
requests a minute, so this asks for up to BATCH variants per request, waits between requests,
and caches every answer on disk: each variant is fetched once, ever, per dataset.

A variant gnomAD has never seen is cached as None (absent), which is itself evidence: ACMG's
PM2 criterion is about variants absent from population databases.
"""

import json
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path

API = "https://gnomad.broadinstitute.org/api"
BATCH = 10
WAIT = 7.0  # seconds between requests, to stay under 10 a minute
FIELDS = "exome { ac an } genome { ac an }"


def _post(query: str, variables: dict) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode()
    request = urllib.request.Request(
        API, body, {"Content-Type": "application/json", "User-Agent": "ehr-rwe-eln"}
    )
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310  (fixed https URL)
        return json.loads(response.read())


def gnomad_id(chromosome: str, position: int, ref: str, alt: str) -> str:
    return f"{chromosome.removeprefix('chr')}-{position}-{ref}-{alt}"


def _frequency(found: dict | None) -> dict | None:
    if found is None:
        return None
    ac = sum((found.get(kind) or {}).get("ac", 0) for kind in ("exome", "genome"))
    an = sum((found.get(kind) or {}).get("an", 0) for kind in ("exome", "genome"))
    return {"ac": ac, "an": an, "af": ac / an if an else None}


def frequencies(
    ids: list[str],
    cache: Path,
    dataset: str = "gnomad_r4",
    post: Callable[[str, dict], dict] = _post,
    wait: float = WAIT,
) -> dict[str, dict | None]:
    """Exome and genome allele counts combined, per gnomAD variant id (chrom-pos-ref-alt).
    Reads the cache first and fetches only what it lacks."""
    known = json.loads(cache.read_text()) if cache.exists() else {}
    missing = [i for i in dict.fromkeys(ids) if i not in known]
    for start in range(0, len(missing), BATCH):
        if start:
            time.sleep(wait)
        batch = missing[start : start + BATCH]
        names = [f"v{i}" for i in range(len(batch))]
        query = (
            "query("
            + ", ".join(f"${n}: String!" for n in names)
            + ") { "
            + " ".join(
                f"{n}: variant(variantId: ${n}, dataset: {dataset}) {{ {FIELDS} }}" for n in names
            )
            + " }"
        )
        answer = post(query, dict(zip(names, batch, strict=True)))
        # "Variant not found" is an answer; anything else (a rate limit, a bad query) is not,
        # and must not be cached as absent.
        other = [e for e in answer.get("errors", []) if e.get("message") != "Variant not found"]
        if other or answer.get("data") is None:
            raise RuntimeError(f"gnomAD API: {other or answer}")
        data = answer["data"]
        for name, variant_id in zip(names, batch, strict=True):
            known[variant_id] = _frequency(data.get(name))
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(known, indent=1, sort_keys=True) + "\n")
    return {i: known[i] for i in ids}
