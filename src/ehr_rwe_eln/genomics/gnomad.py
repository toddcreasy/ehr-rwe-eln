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
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

API = "https://gnomad.broadinstitute.org/api"
BATCH = 10
WAIT = 7.0  # seconds between requests, to stay under 10 a minute
RETRIES = 5
BACKOFF = 30.0  # seconds before the first retry, doubling each time
# Answers that mean "busy, ask again later", not "this query is wrong".
TRANSIENT = ("overloaded", "rate limit", "too many requests")
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


def _ask(post: Callable[[str, dict], dict], query: str, variables: dict, backoff: float) -> dict:
    """One batch's data. "Variant not found" is an answer; an overloaded or rate-limited
    service is retried with backoff; anything else (a bad query) raises. None of these is ever
    cached as absent."""
    for attempt in range(RETRIES):
        try:
            answer = post(query, variables)
        except urllib.error.HTTPError as e:
            if e.code not in (429, 502, 503, 504) or attempt == RETRIES - 1:
                raise
            time.sleep(backoff * 2**attempt)
            continue
        other = [e for e in answer.get("errors", []) if e.get("message") != "Variant not found"]
        if not other and answer.get("data") is not None:
            return answer["data"]
        busy = all(any(w in str(e.get("message", "")).lower() for w in TRANSIENT) for e in other)
        if not (other and busy) or attempt == RETRIES - 1:
            raise RuntimeError(f"gnomAD API: {other or answer}")
        time.sleep(backoff * 2**attempt)
    raise AssertionError("unreachable")


def _cached(
    ids: list[str],
    cache: Path,
    fields: str,
    parse: Callable[[dict | None], dict | None],
    dataset: str,
    post: Callable[[str, dict], dict],
    wait: float,
    backoff: float = BACKOFF,
) -> dict[str, dict | None]:
    """Ask gnomAD for fields of each variant, BATCH per request, caching parse(answer) per id.
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
                f"{n}: variant(variantId: ${n}, dataset: {dataset}) {{ {fields} }}" for n in names
            )
            + " }"
        )
        data = _ask(post, query, dict(zip(names, batch, strict=True)), backoff)
        for name, variant_id in zip(names, batch, strict=True):
            known[variant_id] = parse(data.get(name))
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(known, indent=1, sort_keys=True) + "\n")
    return {i: known[i] for i in ids}


def frequencies(
    ids: list[str],
    cache: Path,
    dataset: str = "gnomad_r4",
    post: Callable[[str, dict], dict] = _post,
    wait: float = WAIT,
) -> dict[str, dict | None]:
    """Exome and genome allele counts combined, per gnomAD variant id (chrom-pos-ref-alt)."""
    return _cached(ids, cache, FIELDS, _frequency, dataset, post, wait)


# gnomAD v4's grpmax: the highest-frequency genetic ancestry group, leaving out the
# bottlenecked groups (Amish, Ashkenazi Jewish, Finnish) and "remaining", where a founder
# variant can be common without being benign. Middle Eastern is kept for exome and joint data
# (gnomAD help, "Group maximum allele frequency").
GRPMAX_GROUPS = ("afr", "amr", "eas", "mid", "nfe", "sas")
DETAIL_FIELDS = "joint { ac an faf95 { popmax popmax_population } populations { id ac an } }"


def _details(found: dict | None) -> dict | None:
    joint = (found or {}).get("joint")
    if not joint or not joint.get("an"):
        return None
    groups = {p["id"]: p for p in joint.get("populations") or []}
    grpmax = [
        groups[g]["ac"] / groups[g]["an"] for g in GRPMAX_GROUPS if groups.get(g, {}).get("an")
    ]
    faf = joint.get("faf95") or {}
    return {
        "ac": joint["ac"],
        "an": joint["an"],
        "af": joint["ac"] / joint["an"],
        "grpmax_af": max(grpmax) if grpmax else None,
        "faf95": faf.get("popmax"),
        "faf95_group": faf.get("popmax_population"),
    }


def details(
    ids: list[str],
    cache: Path,
    dataset: str = "gnomad_r4",
    post: Callable[[str, dict], dict] = _post,
    wait: float = WAIT,
) -> dict[str, dict | None]:
    """What curation needs from gnomAD, exomes and genomes joined: allele count and number,
    overall frequency, the grpmax frequency, and the 95% filtering allele frequency (FAF95) in
    the group where it is highest, the measure ClinGen expert panels set thresholds on. None
    when gnomAD has no call at the site."""
    return _cached(ids, cache, DETAIL_FIELDS, _details, dataset, post, wait)
