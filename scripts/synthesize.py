"""Make every release a synthetic data spec lists, and store each with its provenance.

Usage: uv run python scripts/synthesize.py [--spec path/to/spec.yaml] [--method mst]

The default spec is src/ehr_rwe_eln/synth/specs/person_summary.yaml. Each release is trained on
the spec's training split; the holdout is kept for scripts/evaluate_synth.py. Each run adds new
releases; nothing is replaced, so --method makes only that method's releases (to add a method
without remaking the others). Synthetic source data only: the specs here are seeded for that.

Reads OMOP from the lake through Redshift (OMOP_SOURCE=staging reads the staging Postgres) and
stores releases in Postgres.
"""

import argparse
from pathlib import Path

from ehr_rwe_eln.config import DatabaseSettings
from ehr_rwe_eln.omop import connect_omop
from ehr_rwe_eln.synth import aim, bayes_net, mst, vae
from ehr_rwe_eln.synth.release import save_release
from ehr_rwe_eln.synth.source import build_source, split
from ehr_rwe_eln.synth.spec import SPECS, load_spec


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, default=SPECS / "person_summary.yaml")
    parser.add_argument("--method", help="make only this method's releases")
    args = parser.parse_args()
    spec = load_spec(args.spec)

    omop, cdm = connect_omop()
    with omop:
        train, holdout = split(build_source(omop, spec, cdm), spec)
    with DatabaseSettings().connect() as con:
        print(
            f"{spec.name}: {len(train):,} training and {len(holdout):,} holdout rows,"
            f" {len(spec.columns)} columns"
        )
        for release in spec.releases:
            if args.method and release.method != args.method:
                continue
            if release.method == "vae":
                synthetic, spend = vae.synthesize(train, spec, release)
            elif release.method in ("mst", "aim"):
                module = mst if release.method == "mst" else aim
                synthetic, spend = module.synthesize(train, spec, release)
            else:
                synthetic, measurements = bayes_net.synthesize(train, spec, release)
                spend = bayes_net.plan(measurements)
            release_id = save_release(
                con, spec, release, spend, synthetic, len(train), len(holdout)
            )
            con.commit()
            if release.method in ("mst", "aim"):
                spent = f"rho {sum(s['rho'] for s in spend):.4f}, delta {spec.pgm.delta:g}"
            else:
                spent = f"{sum(s['epsilon'] for s in spend):.3f}"
            print(
                f"  release {release_id}: {release.method}, epsilon {release.epsilon:g}"
                f" (spent {spent}), {len(synthetic):,} rows"
            )


if __name__ == "__main__":
    main()
