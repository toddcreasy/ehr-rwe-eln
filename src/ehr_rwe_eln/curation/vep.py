"""What a variant does to its gene's protein, from Ensembl's Variant Effect Predictor (VEP).

VEP maps a genomic change onto each transcript of the genes it touches: the consequence
(missense, stop_gained, frameshift, splice donor or acceptor, and so on), the change in HGVS
notation (c. for the coding sequence, p. for the protein), the protein position, and the exon
or intron it falls in. Curation reads it on the MANE Select transcript, the one transcript per
gene that NCBI and Ensembl agree on and that clinical reports use. Unlike gnomAD, VEP annotates
any variant, including the many pathogenic ones gnomAD has never seen.

The exon structure of each MANE transcript comes from Ensembl's lookup endpoint, for PVS1's
splice rule: skipping an exon whose length is not a multiple of three shifts the reading frame.

Ensembl puts no restrictions on its data. Answers are cached per Ensembl release, so a new
release never silently changes an old answer.
"""

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

REST = "https://rest.ensembl.org"
BATCH = 50  # the endpoint takes up to 1,000, but large requests time out or come back empty
WAIT = 0.2  # well under Ensembl's 15 requests a second
RETRIES = 4


def _request(path: str, body: dict | None = None) -> object:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    headers |= {"User-Agent": "ehr-rwe-eln"}
    request = urllib.request.Request(REST + path, data, headers)  # noqa: S310  (fixed https URL)
    # Ensembl answers 429 when busy and sometimes 502 to 504; its guidance is to wait and retry.
    # Under load it has also rejected a valid batch with 400 that succeeded unchanged moments
    # later, so 400 is retried too; a request that is truly malformed still fails at the end.
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
                return json.loads(response.read())
        except urllib.error.HTTPError as e:
            if e.code not in (400, 429, 502, 503, 504) or attempt == RETRIES - 1:
                raise
            time.sleep(float(e.headers.get("Retry-After") or 10 * 2**attempt))
        except json.JSONDecodeError:
            # A busy server sometimes answers 200 with an empty body.
            if attempt == RETRIES - 1:
                raise
            time.sleep(10 * 2**attempt)
    raise AssertionError("unreachable")


def release(request: Callable = _request) -> int:
    return int(request("/info/data")["releases"][0])


def _mane(found: dict, genes: set[str]) -> dict | None:
    for t in found.get("transcript_consequences", []):
        if t.get("mane_select") and t.get("gene_symbol") in genes:
            return {
                "gene": t["gene_symbol"],
                "transcript": t["transcript_id"],
                "refseq": t["mane_select"],
                "consequences": t.get("consequence_terms", []),
                "hgvsc": (t.get("hgvsc") or "").split(":")[-1] or None,
                "hgvsp": (t.get("hgvsp") or "").split(":")[-1] or None,
                "protein_start": t.get("protein_start"),
                "exon": t.get("exon"),  # "number/total"
                "intron": t.get("intron"),
            }
    return None


def annotate(
    ids: list[str],
    genes: set[str],
    cache: Path,
    request: Callable = _request,
    wait: float = WAIT,
) -> dict[str, dict | None]:
    """MANE Select consequences per variant id (chrom-pos-ref-alt, the gnomAD form), for the
    first of genes the variant falls in; None if it touches none of them."""
    known = json.loads(cache.read_text()) if cache.exists() else {}
    missing = [i for i in dict.fromkeys(ids) if i not in known]
    for start in range(0, len(missing), BATCH):
        if start:
            time.sleep(wait)
        batch = missing[start : start + BATCH]
        lines = [
            " ".join([*i.split("-", 3)[:2], i, *i.split("-", 3)[2:], ".", ".", "."]) for i in batch
        ]
        found = request(
            "/vep/homo_sapiens/region",
            {"variants": lines, "mane": 1, "hgvs": 1, "numbers": 1},
        )
        by_id = {f["id"]: f for f in found}
        for i in batch:
            known[i] = _mane(by_id[i], genes) if i in by_id else None
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(known, indent=1, sort_keys=True) + "\n")
    return {i: known[i] for i in ids}


def exons(
    transcripts: list[str], cache: Path, request: Callable = _request, wait: float = WAIT
) -> dict[str, list[int]]:
    """Exon lengths in transcript order (5' to 3'), per Ensembl transcript id."""
    known = json.loads(cache.read_text()) if cache.exists() else {}
    for transcript in dict.fromkeys(transcripts):
        if transcript in known:
            continue
        found = request(f"/lookup/id/{transcript}?expand=1")
        # Ensembl lists exons by genomic position; on the minus strand the transcript reads
        # from the highest position down.
        parts = sorted(found["Exon"], key=lambda e: e["start"], reverse=found["strand"] == -1)
        known[transcript] = [e["end"] - e["start"] + 1 for e in parts]
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(known, indent=1, sort_keys=True) + "\n")
        time.sleep(wait)
    return {t: known[t] for t in transcripts}
