"""Make every release a synthetic data spec lists, and store each with its provenance.

Usage: DB_NAME=ehr_rwe_eln_tte uv run python scripts/synthesize.py [--spec path/to/spec.yaml]

The default spec is src/ehr_rwe_eln/synth/specs/person_summary.yaml. Each run adds new releases;
nothing is replaced. Synthetic source data only: the specs here are seeded for that case.
"""

import argparse
from pathlib import Path

from ehr_rwe_eln.config import DatabaseSettings
from ehr_rwe_eln.synth import bayes_net, vae
from ehr_rwe_eln.synth.release import save_release
from ehr_rwe_eln.synth.source import build_source
from ehr_rwe_eln.synth.spec import SPECS, load_spec


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, default=SPECS / "person_summary.yaml")
    args = parser.parse_args()
    spec = load_spec(args.spec)

    with DatabaseSettings().connect() as con:
        source = build_source(con, spec)
        print(f"{spec.name}: {len(source):,} source rows, {len(spec.columns)} columns")
        for release in spec.releases:
            if release.method == "vae":
                synthetic, spend = vae.synthesize(source, spec, release)
            else:
                synthetic, measurements = bayes_net.synthesize(source, spec, release)
                spend = bayes_net.plan(measurements)
            release_id = save_release(con, spec, release, spend, synthetic, len(source))
            con.commit()
            spent = sum(s["epsilon"] for s in spend)
            print(
                f"  release {release_id}: {release.method}, epsilon {release.epsilon:g}"
                f" (spent {spent:.3f}), {len(synthetic):,} rows"
            )


if __name__ == "__main__":
    main()
