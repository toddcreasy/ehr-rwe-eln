// The five sections, in the order data moves through them, and the live figures each shows.
// Every figure comes from the section's own API; nothing here is hard-coded.

export type Live = {
  dq?: { strictPercentPassed: number; countOverallFailed: number; countTotal: number; runs: number };
  tte?: { persons: number; runs: number };
  eln?: { entries: number; extracted: number; failed: number; samples: number; results: number };
  curation?: { variants: number; decided: number; sets: number };
  synth?: { releases: number; withdrawn: number; flags: number };
};

export type Figure = { value: string; label: string; attention?: boolean };

export type Module = {
  key: keyof Live;
  verb: string;
  name: string;
  href: string;
  summary: string;
  detail: string;
  figures: (live: Live) => Figure[];
};

const n = (x: number) => x.toLocaleString("en-US");

export const MODULES: Module[] = [
  {
    key: "dq",
    verb: "Check",
    name: "Data quality",
    href: "/dq/",
    summary: "Is the data fit to use?",
    detail:
      "Runs conformance, completeness, and plausibility checks (the Kahn framework) over the OMOP tables, modeled on OHDSI's Data Quality Dashboard, and shows which failed and why.",
    figures: ({ dq }) =>
      dq
        ? [
            { value: `${dq.strictPercentPassed.toFixed(1)}%`, label: "of applicable checks passed" },
            { value: n(dq.countOverallFailed), label: "checks failed", attention: dq.countOverallFailed > 0 },
            { value: n(dq.countTotal), label: "checks in the latest run" },
          ]
        : [],
  },
  {
    key: "tte",
    verb: "Emulate",
    name: "Trial emulation",
    href: "/tte/",
    summary: "What would a trial have found?",
    detail:
      "Writes a trial protocol in YAML (who is eligible, what each arm does, when follow-up starts), builds it from the records, balances the arms with propensity scores, and reports survival estimates next to bias diagnostics.",
    figures: ({ tte }) =>
      tte
        ? [
            { value: n(tte.persons), label: "people in the source" },
            { value: n(tte.runs), label: tte.runs === 1 ? "emulation run" : "emulation runs" },
          ]
        : [],
  },
  {
    key: "eln",
    verb: "Extract",
    name: "Lab notebook",
    href: "/eln/",
    summary: "What did the lab measure?",
    detail:
      "Claude reads free-text lab notebook entries and pulls out samples, assays, and results into typed records, then writes them as OMOP specimens and measurements and as FHIR resources, linked to the right patient.",
    figures: ({ eln }) =>
      eln
        ? [
            { value: `${n(eln.extracted)} of ${n(eln.entries)}`, label: "entries extracted" },
            { value: n(eln.results), label: "results recorded" },
            ...(eln.failed > 0 ? [{ value: n(eln.failed), label: "failed extraction", attention: true }] : []),
          ]
        : [],
  },
  {
    key: "curation",
    verb: "Curate",
    name: "Variant curation",
    href: "/curation/",
    summary: "Is this variant pathogenic?",
    detail:
      "Applies the ACMG/AMP criteria that data alone can decide, under each gene's ClinGen expert panel rules, then puts literature evidence and phenotype context in front of a curator, who records the final class.",
    figures: ({ curation }) =>
      curation
        ? [
            { value: n(curation.variants - curation.decided), label: "waiting for a curator", attention: curation.variants > curation.decided },
            { value: n(curation.decided), label: "decided" },
            { value: n(curation.sets), label: curation.sets === 1 ? "variant set" : "variant sets" },
          ]
        : [],
  },
  {
    key: "synth",
    verb: "Release",
    name: "Synthetic data",
    href: "/synth/",
    summary: "Can we share it safely?",
    detail:
      "Generates differentially private copies of the data, so no one person's record changes the release by much, and reports how faithful, useful, and resistant to privacy attacks each one is.",
    figures: ({ synth }) =>
      synth
        ? [
            { value: n(synth.releases), label: "releases" },
            synth.flags > 0
              ? { value: n(synth.flags), label: "monitor flags", attention: true }
              : { value: "clear", label: "privacy monitor" },
          ]
        : [],
  },
];
