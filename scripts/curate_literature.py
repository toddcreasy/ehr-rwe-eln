"""Propose literature evidence for Evidence Repository variants with Claude, verify every quote,
and score the proposals against the criteria the expert panels applied.

Usage:
    uv run python scripts/curate_literature.py --dry-run [--variants 10]
        retrieve passages and count input tokens (free); no model calls
    uv run python scripts/curate_literature.py [--variants 10]
        call MODEL once per variant that has passages, and store and score the claims

Variants come from the latest --set erepo curation run: those the panel scored with PS3, BS3,
PS4, or PP1, in a fixed order. Each call costs money; the run prints measured tokens and cost.
Proposals go to curation.proposal and never change an assessment.
"""

import argparse
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import anthropic
from psycopg.types.json import Jsonb

from ehr_rwe_eln.agents.config import AgentSettings
from ehr_rwe_eln.config import DatabaseSettings
from ehr_rwe_eln.curation.erepo import parse_code
from ehr_rwe_eln.curation.literature import (
    CRITERIA,
    SYSTEM_PROMPT,
    ProposalFailed,
    literature_cases,
    propose,
    score_claims,
    verify,
)
from ehr_rwe_eln.synth.release import code_version

REFERENCE = Path(__file__).resolve().parent.parent / "data" / "reference"
# Claude Opus 5.5 list prices, dollars per million tokens: input, output, cache read, cache write.
PRICE = {"input": 4.0, "output": 20.0, "cache_read": 0.4, "cache_write": 5.0}


def cost(usage: Counter) -> float:
    return sum(usage[k] * PRICE[k] for k in PRICE) / 1e6


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variants", type=int, default=10, help="how many variants with passages")
    parser.add_argument("--dry-run", action="store_true", help="retrieve and count tokens only")
    args = parser.parse_args()

    settings = AgentSettings()
    key = settings.anthropic_api_key
    client = anthropic.Anthropic(api_key=key.get_secret_value() if key else None)
    with DatabaseSettings().connect() as con:
        chosen, skipped = literature_cases(con, args.variants, REFERENCE)
    print(f"{len(chosen)} variants with passages; skipped {dict(skipped)}")

    if args.dry_run:
        tokens = [
            client.messages.count_tokens(
                model=settings.model,
                system=[{"type": "text", "text": SYSTEM_PROMPT}],
                messages=[{"role": "user", "content": v["prompt"]}],
            ).input_tokens
            for v in chosen
        ]
        total = sum(tokens)
        print(f"input tokens: {total:,} ({total / max(len(tokens), 1):,.0f} a variant)")
        print(
            f"input cost: ${total * PRICE['input'] / 1e6:.2f}; output (thinking included) is extra"
        )
        return

    usage, rows, stored = Counter(), [], []
    start = time.time()
    for v in chosen:
        try:
            proposals, used = propose(v["prompt"], client, settings.model)
        except ProposalFailed as e:
            print(f"  {v['gene']} {v['variant_id']}: {e}")
            continue
        usage.update(used)
        verified, rejected = verify(proposals, v["passages"])
        rows.append((v["expert"], verified))
        stored += [(v, c, True) for c in verified] + [(v, c, False) for c in rejected]
        panel = [m for m in v["expert"]["met"] if parse_code(m)[0] in CRITERIA]
        print(
            f"  {v['gene']:<5} {v['variant_id']:<26} {len(verified)} verified, {len(rejected)}"
            f" rejected; panel met {panel};"
            f" proposed {[c['criterion'] + '_' + c['strength'] for c in verified]}"
        )
    summary = {
        "variants": len(rows),
        "claims_verified": sum(1 for *_, ok in stored if ok),
        "claims_rejected": sum(1 for *_, ok in stored if not ok),
        "criteria_vs_panel": score_claims(rows),
        "panel_cited_papers": sum(v["cited"] for v in chosen),
        "panel_cited_in_litvar": sum(v["cited_in_litvar"] for v in chosen),
        "panel_cited_in_passages": sum(v["cited_in_passages"] for v in chosen),
        "usage": dict(usage),
        "cost_usd": round(cost(usage), 4),
    }
    with DatabaseSettings().connect() as con:
        run_id = con.execute(
            "INSERT INTO curation.run (created_at, variant_set, sources, code_version, summary)"
            " VALUES (%s, 'erepo', %s, %s, %s) RETURNING run_id",
            [
                datetime.now(UTC),
                Jsonb(
                    {
                        "literature": {
                            "model": settings.model,
                            "litvar": "LitVar2",
                            "text": "PubTator3",
                        }
                    }
                ),
                code_version(),
                Jsonb(summary),
            ],
        ).fetchone()[0]
        with con.cursor() as cur:
            cur.executemany(
                "INSERT INTO curation.proposal (run_id, variant_id, gene, criterion, strength,"
                " pmid, quote, rationale, verified, rejected_why)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    [
                        run_id,
                        v["variant_id"],
                        v["gene"],
                        c["criterion"],
                        c["strength"],
                        c["pmid"],
                        c["quote"],
                        c["rationale"],
                        ok,
                        c.get("why"),
                    ]  # fmt: skip
                    for v, c, ok in stored
                ],
            )
        con.commit()
    print(f"run {run_id}: {summary['variants']} variants in {time.time() - start:.0f}s")
    print(f"  claims: {summary['claims_verified']} verified, {summary['claims_rejected']} rejected")
    for c, s in summary["criteria_vs_panel"].items():
        print(f"  {c}: {s}")
    print(
        f"  panel-cited papers: {summary['panel_cited_papers']}, in LitVar2"
        f" {summary['panel_cited_in_litvar']}, with a passage naming the variant"
        f" {summary['panel_cited_in_passages']}"
    )
    print(f"  tokens {dict(usage)}; cost ${summary['cost_usd']:.2f}")


if __name__ == "__main__":
    main()
