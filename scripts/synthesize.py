"""Make every release a synthetic data spec lists, and store each with its provenance.

Usage: uv run python scripts/synthesize.py [--spec path/to/spec.yaml]

The default spec is src/ehr_rwe_eln/synth/specs/person_summary.yaml. Each release is trained on
the spec's training split; the holdout is kept for scripts/evaluate_synth.py. Each run adds new
releases; nothing is replaced. Synthetic source data only: the specs here are seeded for that.
"""

import argparse
from pathlib import Path

from ehr_rwe_eln.config import DatabaseSettings
from ehr_rwe_eln.synth import bayes_net, vae
from ehr_rwe_eln.synth.release import save_release
from ehr_rwe_eln.synth.source import build_source, split
from ehr_rwe_eln.synth.spec import SPECS, load_spec


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, default=SPECS / "person_summary.yaml")
    args = parser.parse_args()
    spec = load_spec(args.spec)

    with DatabaseSettings().connect() as con:
        train, holdout = split(build_source(con, spec), spec)
        print(
            f"{spec.name}: {len(train):,} training and {len(holdout):,} holdout rows,"
            f" {len(spec.columns)} columns"
        )
        for release in spec.releases:
            if release.method == "vae":
                synthetic, spend = vae.synthesize(train, spec, release)
            else:
                synthetic, measurements = bayes_net.synthesize(train, spec, release)
                spend = bayes_net.plan(measurements)
            release_id = save_release(
                con, spec, release, spend, synthetic, len(train), len(holdout)
            )
            con.commit()
            spent = sum(s["epsilon"] for s in spend)
            print(
                f"  release {release_id}: {release.method}, epsilon {release.epsilon:g}"
                f" (spent {spent:.3f}), {len(synthetic):,} rows"
            )


if __name__ == "__main__":
    main()
