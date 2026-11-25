import { Help, Term } from "../help";

// Help notes for the variant curation page. Facts come from docs/modules/curation.md,
// docs/modules/genomics.md, the glossary, src/ehr_rwe_eln/curation/, and api/curation.py; the
// counts come from the run and variant on screen, so the notes stay true when another is picked.

const fmt = (n: number) => n.toLocaleString("en-US");

// A small heading inside a note, for the longer ones with sections.
const Head = ({ children }: { children: React.ReactNode }) => (
  <h3 className="mt-1 text-xs font-semibold tracking-wide text-foreground uppercase">{children}</h3>
);

type Criterion = { code: string; label: string; strength: string; proposal_id?: number };

export function PageHelp() {
  return (
    <Help page title="Variant curation">
      <Head>Why run it</Head>
      <p>
        A genetic variant is a spot in the genome where people differ. When a test finds one in a gene linked to
        a disease, someone has to decide what it means: does it cause the disease (pathogenic), is it harmless
        (benign), or is there not enough evidence to say (uncertain significance)? That decision is variant
        curation.
      </p>
      <p>
        Labs follow the <Term t="ACMG/AMP" /> criteria: each criterion is one piece of evidence, for or against, at a set strength. Some can be
        decided from data alone, like how common the variant is. Others need a person to read papers. This page
        does the data part automatically, has Claude point to papers, and leaves the class to a person, so you can
        see which part of each answer came from where.
      </p>

      <Head>Where the data comes from</Head>
      <p>
        <strong>Variants</strong> are real records from ClinVar, the public archive of what labs and expert panels
        have concluded about human variants (release 2026-11-15). The genomics module planted 48 of them, in six
        genes, by their standard symbols BRCA1, BRCA2, MLH1, MSH2, APC, and LDLR, in 5,000 synthetic people from this project&apos;s simulated
        health records. The variants are real; the people carrying them are not.
      </p>
      <p>
        <strong>Frequencies</strong> come from <Term t="gnomAD" /> v4, which counts variants in
        hundreds of thousands of real exomes and genomes. This page includes data from the gnomAD v4 release.
      </p>
      <p>
        <strong>Consequences</strong> come from Ensembl <Term t="VEP" />: what the variant does to
        the gene&apos;s main transcript, such as cutting the protein short.
      </p>
      <p>
        <strong>Rules</strong> come from <Term t="ClinGen" />: each gene&apos;s expert panel sets its own thresholds
        for the criteria, published in the <Term t="CSpec" /> registry, read 2026-11-19. ClinGen content is{" "}
        <Term t="CC0" />, a public domain dedication.
      </p>
      <p>
        <strong>Literature</strong>: LitVar2, from <Term t="NCBI" />, finds
        papers that mention the variant, and PubTator3 gives their text. Claude reads passages that name the variant and
        proposes evidence, each claim with a <Term t="PMID" /> and a quoted sentence that code checks
        against the text it was sent.
      </p>
      <p>
        <strong>The curator</strong> accepts the proposals they agree with and records a class, with their name and
        the time.
      </p>

      <Head>What it does</Head>
      <p>
        For each variant, the rules look up its frequency and consequence, apply the gene&apos;s panel thresholds,
        and add up points: supporting 1, moderate 2, strong 4, very strong 8, with benign evidence counted
        against. 10 or more is pathogenic, 6 to 9 likely pathogenic, 0 to 5 uncertain significance, -1 to -6 likely
        benign, -7 or less benign. What the rules cannot decide is listed with the reason.
      </p>
      <p>
        The rules never read ClinVar&apos;s classification. That is what lets the page compare their answer with
        the expert panels&apos; answer honestly. Claude&apos;s proposals change nothing until a person accepts them.
      </p>

      <Head>How to read it</Head>
      <p>
        Pick a variant set at the top, then a variant from the list on the left. Its detail reads top to bottom:
        the evidence, the criteria the rules met and what they left open, then the literature, the decision, and
        the history. Each &ldquo;?&rdquo; on the page explains the part next to it.
      </p>
      <p>Synthetic people, for research and demonstration only. Not for diagnosis.</p>
    </Help>
  );
}

type SetSummary = { variant_set: string; variants: number; decided: number };

export function SetsHelp({ sets }: { sets: SetSummary[] }) {
  const of = (name: string) => sets.find((s) => s.variant_set === name);
  const line = (name: string) => {
    const s = of(name);
    return s ? ` (${fmt(s.variants)} variants here, ${fmt(s.decided)} decided)` : "";
  };
  return (
    <Help title="Variant sets and filters">
      <p>Each button is the latest run of the rules on one set of variants. There are three kinds:</p>
      <p>
        <strong>panel</strong>
        {line("panel")}: the variants planted in the synthetic genomics study. ClinVar&apos;s answer for them is
        kept out of the run, so no expert panel class is shown. In the 2026-11-19 run, 47 of the 48 landed in the
        class their ClinVar record gives.
      </p>
      <p>
        <strong>eval</strong>
        {line("eval")}: ClinVar variants with three stars (reviewed by an expert panel) in the six genes, up to
        20 per gene and class, picked with a fixed seed. The panel&apos;s class is the answer key.
      </p>
      <p>
        <strong>erepo</strong>
        {line("erepo")}: every short-variant curation in the six genes from <Term t="ClinGen" />&apos;s
        Evidence Repository, which records the class and each criterion the panel used or rejected. The
        page opens on this set.
      </p>
      <p>
        <strong>Decided</strong> counts variants with at least one recorded curator decision.
      </p>
      <p>
        The menu filters the list: variants with literature proposals, variants nobody has decided yet, or
        variants where the rules and the panel land in different tiers. The tiers are the three the agreement
        numbers use: pathogenic or likely pathogenic, uncertain, and benign or likely benign. So
        &ldquo;Pathogenic&rdquo; against &ldquo;Likely pathogenic&rdquo; counts as the same tier, and the list
        still shows both classes.
      </p>
    </Help>
  );
}

export function ListHelp({ shown, total }: { shown: number; total: number }) {
  return (
    <Help title="The variant list">
      <p>
        {fmt(shown)} of the {fmt(total)} variants in this run pass the filter. They are sorted by gene. Click one to
        open it on the right.
      </p>
      <p>
        <strong>First line</strong>: the gene and the variant&apos;s <Term t="HGVS" /> names: the c. name is the
        change in the gene&apos;s coding <Term t="DNA" />, the p. name in brackets the change to the protein.
      </p>
      <p>
        <strong>Second line</strong>: the class the rules gave. When the expert panel&apos;s class differs, it
        follows as &ldquo;panel&rdquo; and its class.
      </p>
      <p>
        <strong>Third line</strong>: how many verified literature proposals Claude made, and the latest curator
        decision with who made it, or &ldquo;undecided&rdquo;.
      </p>
    </Help>
  );
}

const pointsText = (p: number | null) =>
  p === null ? "no points (BA1, the stand-alone benign criterion, decides it on its own)" : `${p} points`;

export function HeaderHelp({
  classification,
  points,
  expected,
}: {
  classification: string;
  points: number | null;
  expected: string | null;
}) {
  return (
    <Help title="The variant and its class">
      <p>
        The title names the variant by gene and <Term t="HGVS" /> notation. The line under it gives its <Term t="ID" />:
        chromosome, position, the reference letters, and the changed letters, on <Term t="GRCh38" />, the current
        reference genome.
      </p>
      <p>
        <strong>Rules</strong>: {classification}, from {pointsText(points)}. This is what the automatic rules
        decided from data alone, before anyone read a paper.
      </p>
      {expected ? (
        <p>
          <strong>Expert panel</strong>: {expected}. The class an expert panel gave this variant. The rules never
          read it; it is shown only to compare.
        </p>
      ) : (
        <p>
          No expert panel class is shown for this set: for the planted panel variants, the answer key is kept out
          of the run.
        </p>
      )}
      <p>
        How to read a difference: in the 2026-11-19 run against 578 ClinVar expert panel variants, when the rules
        called a variant pathogenic or likely pathogenic they were right 120 of 122 times, and benign or likely
        benign 144 of 150 times, with no reversals (pathogenic called benign, or the other way). Most differences
        are variants the rules leave at uncertain significance because the deciding evidence is in papers or lab
        studies.
      </p>
    </Help>
  );
}

export function EvidenceHelp({
  gnomad,
}: {
  gnomad: { ac: number; an: number; af: number | null; faf95?: number | null; faf95_group?: string | null } | null | undefined;
}) {
  return (
    <Help title="The evidence">
      <p>
        <strong>Consequence</strong>: what Ensembl <Term t="VEP" /> says the variant does to the <Term t="MANE" />{" "}
        Select transcript: the one version of the gene&apos;s transcript that <Term t="NCBI" /> and Ensembl, run by{" "}
        <Term t="EMBL-EBI" />, agree on, and that clinical reports use. A stop gained or a frameshift cuts
        the protein short; a missense variant swaps one amino acid. The exon or intron says where in the gene it
        falls.
      </p>
      <p>
        <strong><Term t="gnomAD" /> v4</strong>: how often the variant turns up in hundreds of
        thousands of people. An allele is one copy of the gene; each person has two.{" "}
        {!gnomad || gnomad.ac === 0
          ? "This variant is absent: gnomAD has no call at the site, or counted it zero times. Absent counts as frequency 0, which can meet PM2, the criterion for a variant absent or extremely rare in population data."
          : `This one is seen ${fmt(gnomad.ac)} times in ${fmt(gnomad.an)} alleles.`}
      </p>
      <p>
        <strong><Term t="AF" /></strong> is that count as a share. <strong><Term t="FAF">FAF95</Term></strong> is
        the low end of a 95% confidence range on the frequency, in the ancestry group where it is
        highest. Expert panels set their &ldquo;too common&rdquo; thresholds on it: if even the low end is above
        what the disease allows, the variant is too common to cause it.
      </p>
      <p>This page includes data from the gnomAD v4 release.</p>
    </Help>
  );
}

export function CriteriaHelp({
  met,
  notAssessed,
  points,
  classification,
}: {
  met: Criterion[];
  notAssessed: number;
  points: number | null;
  classification: string;
}) {
  return (
    <Help title="Criteria and points">
      <p>
        <Term t="ACMG/AMP" /> criteria are named by code. The first letter says which way, P pathogenic or B benign; the next says how strong: VS
        very strong, S strong, M moderate, P supporting, A stand-alone. A suffix like &ldquo;_Supporting&rdquo; means
        the criterion counts at a different strength from its usual one, as the panel&apos;s rules or the evidence
        set it.
      </p>
      <p>The rules can meet these, from data:</p>
      <p>
        <strong>BA1</strong>: too common in <Term t="gnomAD" /> to cause the disease; benign on its
        own. <strong>BS1</strong>: more common than the disease allows. <strong>PM2</strong>: absent or extremely
        rare. <strong>PVS1</strong>: a null variant (one that stops the gene making working protein) in a gene where
        loss of function causes the disease; each panel says where in the gene that holds.{" "}
        <strong>PM5_PTC</strong> (<Term t="PTC" />): for BRCA1 and BRCA2, other proven pathogenic
        premature stops in the same exon.{" "}
        <strong>PS3</strong> and <strong>BS3</strong>: for BRCA1 and BRCA2, a calibrated lab assay in{" "}
        <Term t="ENIGMA" />&apos;s table shows a damaging effect, or
        none.
      </p>
      <p>
        <strong>This variant</strong>: {met.length} {met.length === 1 ? "criterion" : "criteria"} met, {notAssessed}{" "}
        left to the curator, adding to {pointsText(points)}: <strong>{classification}</strong>. Points are supporting
        1, moderate 2, strong 4, very strong 8, benign counted against; 10 or more is pathogenic, 6 to 9 likely
        pathogenic, 0 to 5 uncertain significance, -1 to -6 likely benign, -7 or less benign.
      </p>
      <p>
        <strong>Left to the curator</strong> lists what the rules could not settle and why, such as a splice site
        a panel grades by hand, or a stop in the last exon. Missense changes usually need lab, case, or family
        evidence the rules do not have. An empty list here does not mean the class is final; only a curator&apos;s decision is.
      </p>
    </Help>
  );
}

export function PhenotypeHelp({ release, subjects, high }: { release: string; subjects: number; high: number }) {
  return (
    <Help title="Carriers' phenotypes">
      <p>
        A phenotype is what shows in a person&apos;s records: their diagnoses. This box asks whether the synthetic
        people who carry the variant have conditions that fit the gene.
      </p>
      <p>
        Each person&apos;s conditions are mapped to <Term t="HPO" /> terms and scored against the
        terms linked to the gene&apos;s group (the two breast cancer genes, the three colon cancer genes, or{" "}
        <Term t="LDLR" /> for hyperlipidemia, high blood fats). The percentile places each carrier among all 5,000 study subjects: 90 or above is
        the top 10%.
      </p>
      <p>
        {subjects === 0
          ? "Nobody in the study carries this variant, so there is nothing to place."
          : `Here, ${fmt(subjects)} ${subjects === 1 ? "carrier" : "carriers"}, ${fmt(high)} in the top 10%.`}
      </p>
      <p>
        Context, not evidence. It is not scored as PP4 (phenotype specific to the gene): that criterion is judged
        for one patient under each panel&apos;s rules, and in the 2026-11-19 check the score found the right gene
        group only about as well as knowing who has the condition. Carriers were planted by condition, so a
        phenotype can point to a gene group, never to one gene in it.
      </p>
      <p>
        This service/product is using the Human Phenotype Ontology (release {release}). Find out more at
        http://www.human-phenotype-ontology.org. Köhler et al., Nucleic Acids Research 2014, doi:10.1093/nar/gkt1026.
      </p>
    </Help>
  );
}

export function ExomiserHelp({ release, gene, auc }: { release: string; gene: string; auc: number | null }) {
  return (
    <Help title="Carriers' Exomiser rank">
      <p>
        Exomiser 15.1.0 (data release {release}) is the standard open tool for ranking the genes a person carries
        variants in, to help find a rare disease. Here it ran on each study subject&apos;s panel variants and{" "}
        <Term t="HPO" /> terms.
      </p>
      <p>
        Only its phenotype score is shown: how well the person&apos;s conditions fit each gene. Its variant score
        reads ClinVar, which would hand the curator ClinVar&apos;s answer under another name.
      </p>
      <p>
        <strong>Rank</strong>: where {gene} lands among the few panel genes each carrier has a variant in. Rank 1
        means it fit best. In the 2026-11-22 run, the phenotype score put the planted gene first for 36 of 123
        pathogenic carriers (29%), against about 15% by picking at random.
      </p>
      {auc !== null && (
        <p>
          <strong><Term t="AUC" /></strong> {auc.toFixed(2)}: the chance that a random pathogenic carrier
          of {gene} scores above a random non-carrier with a variant in the gene. 0.5 is a coin flip, 1.0 perfect.
        </p>
      )}
      <p>Context, not evidence: not scored as PP4 (phenotype specific to the gene).</p>
    </Help>
  );
}

export function ProposalsHelp({ verified, rejected }: { verified: number; rejected: number }) {
  return (
    <Help title="Literature proposed by Claude">
      <p>
        Some criteria need papers, not data. Claude proposes four:{" "}
        <strong>PS3</strong> (a well-established lab assay shows the variant is damaging), <strong>BS3</strong> (one
        shows no damaging effect), <strong>PS4</strong> (the variant is much more common in affected people than in
        controls), and <strong>PP1</strong> (it travels with the disease through affected family members).
      </p>
      <p>
        Each claim names a <Term t="PMID" /> and quotes one sentence. Code then checks the PMID was one
        Claude was sent and the quote is in a passage from that paper. Failures are kept, greyed out, with the
        reason. This variant has {fmt(verified)} verified and {fmt(rejected)} rejected.
      </p>
      <p>
        Tick a verified claim to accept it; the decision below rescores at once. A box is locked when the claim was
        rejected or the rules already met that criterion, so the same evidence never counts twice. Accepting one
        criterion from two papers counts it once, at the stronger strength.
      </p>
      <p>
        How far to trust them: in a 2026-11-19 pilot of ten Evidence Repository variants, 70% of the criteria
        Claude proposed were ones the panel also used, and it found half of the panel&apos;s. Many panel sources sit
        in supplementary tables the search cannot reach, so a missing proposal is not evidence against.
      </p>
    </Help>
  );
}

export function DecisionHelp({ score }: { score: { classification: string; points: number | null } | null }) {
  return (
    <Help title="Recording a decision">
      <p>
        <strong>With the accepted evidence</strong>
        {score ? `: ${score.classification}, ${pointsText(score.points)}` : ""}. The rules&apos; criteria plus any
        literature you ticked, through the same points scale.
      </p>
      <p>
        <strong>Class</strong> starts at that score. You can pick another, but then the note is required, saying
        why. <strong>Curator</strong> is the name you type; this browser remembers it. The app has no sign-in, so a
        decision records who said they made it, not a checked identity.
      </p>
      <p>
        <strong>Record decision</strong> adds a row to the history. Decisions are only ever added, never edited,
        and the newest one is the class that stands.
      </p>
      <p>
        On the public demo site, recording is switched off (the PUBLIC_DEMO setting), because anyone could write
        there. The box says so, and the form still rescores as you accept evidence or change the class. Run the
        app locally to record decisions.
      </p>
    </Help>
  );
}

export function HistoryHelp({ count }: { count: number }) {
  return (
    <Help title="Decision history">
      <p>
        Every decision recorded for this variant, newest first: {fmt(count)} so far. Each shows the class chosen,
        who and when, the class the criteria scored at the time with its points, and how many literature claims
        were accepted.
      </p>
      <p>
        When the chosen class differs from the scored one, the curator&apos;s note says why. Nothing here is ever
        changed or deleted; a new decision adds a row.
      </p>
    </Help>
  );
}

export function SourcesHelp() {
  return (
    <Help title="Sources">
      <p>
        Everything needed to repeat this run: the variant set and run number, when it ran, and each input&apos;s
        version.
      </p>
      <p>
        <strong>gnomad</strong>: the <Term t="gnomAD" /> dataset. <strong>ensembl</strong>: the Ensembl release{" "}
        <Term t="VEP" /> answers came from. <strong>clinvar</strong>: the ClinVar
        release, empty for the planted panel. <strong>rules_sha256</strong>: the start of a{" "}
        <Term t="SHA-256" /> fingerprint of the rules file, which changes if any threshold does.{" "}
        <strong>cspec</strong>: each gene&apos;s expert panel document and version in{" "}
        <Term t="ClinGen" />&apos;s <Term t="CSpec" /> registry. <strong>erepo</strong>, on that set: the
        Evidence Repository export file, dated in its name.
      </p>
      <p>
        Includes data from the gnomAD v4 release. Expert panel thresholds from ClinGen&apos;s CSpec registry, read
        2026-11-19 (<Term t="CC0" />: public domain).
      </p>
    </Help>
  );
}
