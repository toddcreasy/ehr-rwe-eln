# NIH and HHS requirements

How this repository's synthetic data process lines up with the federal rules that would govern it on a real controlled-access source: the NIH Genomic Data Sharing Policy, NIH's security requirements for controlled-access data, and the HIPAA Privacy Rule's de-identification standard. Each section quotes or paraphrases the primary source, says what the repository does, and names what is missing.

This is an engineering read of the rules, not legal advice. Whether a dataset is human subjects research, whether it is de-identified, and who may receive it are decided by an institution's IRB and privacy office and by the NIH Data Access Committee (DAC) for the study.

## What applies today

Nothing here binds this repository as it stands:

- The data are [Synthea](https://github.com/synthetichealth/synthea) output, synthetic lab notebook entries, and genotypes simulated with [msprime](https://tskit.dev/msprime/). No living person is the source of any record, so the work is not human subjects research under the Common Rule (45 CFR 46).
- None of it is protected health information, so the HIPAA Privacy Rule does not apply.
- The work is not NIH-funded, so the Genomic Data Sharing Policy does not apply.

The point of this document is the next step: if the same process were pointed at a [dbGaP](https://www.ncbi.nlm.nih.gov/gap/) study or another controlled-access source, what would each rule require, and how far does the repository already go?

## 1. NIH Genomic Data Sharing Policy

Source: NOT-OD-14-124. It applies to NIH-funded research that generates large-scale human genomic data (for example, sequence data on more than 1,000 participants), for grant applications due on or after January 25, 2015. Human data are registered in dbGaP.

| Requirement | This repository | Gap |
|---|---|---|
| Consent: participants consent to future research use and broad sharing, and the consent says whether data go to controlled or unrestricted access. | Synthetic sources have no consent. On a real source, a synthetic release is derived from participants' data, so it inherits the study's data use limitations (the consent-based terms that say what the data may be used for). Every spec must state them (`data_use_limitations`, required), and every data card prints them. | None in the code. |
| De-identification: data de-identified under the HHS human subjects regulations and the HIPAA Privacy Rule, and "assigned random, unique codes by the investigator," with the key kept by the submitting institution. | Releases carry no direct identifiers; `person_id` is used to build and split the source and never reaches a release. Genotype study codes and lab notebook subject codes (`HTN-0001` and on) are assigned in a random order. The registries linking codes to `person_id` are written for testing, to `data/registry/`, outside the folders a study would share; a real study would keep them with the data holder and never distribute them. | None in the code. |
| Controlled access: data are released for secondary research "only after investigators have obtained approval from NIH"; DACs decide primarily on whether proposed research conforms to the data use limitations. | Synthetic data are treated here as derived data. Differential privacy is a strong argument for wider sharing, but the decision belongs to the DAC. | No written rule that a synthetic release from controlled data stays within the approved users until the DAC says otherwise. |
| Data Use Certification: approved users agree to "not attempting to identify individual participants" and not to share data beyond those listed in the data access request. | The privacy attacks (distance to closest record, membership inference, attribute inference) exist to measure re-identification risk, and their reports stay internal. | On real controlled data those attacks are, in method, attempts to identify participants. They should be described in the data access request and approved before they run. |
| Institutional Certification: provided at just-in-time for human data. | An investigator obligation, outside the code. | Not applicable to the code. |

## 2. Security for controlled-access data

Source: NOT-OD-24-157, released July 25, 2024, effective January 25, 2025. Approved users of controlled-access human genomic data from NIH repositories attest that their institution's systems comply with NIST SP 800-171. An approved user who works on a third-party IT system or cloud provider attests that it complies with NIST SP 800-171. Repositories attest to the NIST SP 800-53 Moderate baseline (FedRAMP Moderate or FISMA Moderate satisfies it). The standard goes into new or renewed Data Use Certifications.

This repository is a single-user local stack. Every port binds to 127.0.0.1, the API key is a `SecretStr` read from a gitignored `.env`, and data stay in a Docker volume and the gitignored `data/` folder. That is sound hygiene but not NIST SP 800-171 compliance: there is no authentication, no audit logging, no account management, and no encryption beyond whatever the host disk provides.

The way to meet the requirement is not to retrofit a laptop: run the stack inside an environment the institution has already attested, such as an approved research enclave or an attested cloud workspace. If the app were shared among users there, it would also need authentication and audit logging of who read which release.

## 3. HIPAA Privacy Rule de-identification

Source: 45 CFR 164.514(b) and (c). Health information is de-identified by one of two methods.

- **Expert determination**: a person with appropriate statistical and scientific knowledge concludes that "the risk is very small" that the information could identify someone, alone or with other reasonably available information, and documents the methods and results.
- **[Safe Harbor](https://www.hhs.gov/hipaa/for-professionals/special-topics/de-identification/index.html)**: remove 18 kinds of identifiers of the individual and their relatives, employers, and household members, and have no actual knowledge that what remains could identify them. Among them: geographic units smaller than a state (the first three ZIP digits may stay where that area holds more than 20,000 people); every element of a date except the year; and ages over 89, which may be kept only as "a single category of age 90 or older."

Re-identification codes (164.514(c)) are allowed only if the code is not derived from or related to information about the individual, and the means of re-identifying is not disclosed.

**Which method fits.** Safe Harbor is written for records about real people. A differentially private synthetic row is not a record about anyone, but it is computed from such records, so the stronger argument is expert determination. The documentation an expert would review already exists: the [methodology](synthetic_data_methodology.md), the privacy spend and attack results stored with every release, and its data card. None of it is a determination; an expert would still have to make one.

**Safe Harbor as hygiene.** Even under expert determination, it is good practice for releases to avoid Safe Harbor identifiers:

- No names, contact details, record or account numbers, device identifiers, URLs, IP addresses, images, or biometric identifiers are released.
- No calendar dates are released: the person summary has ages, and the trial table has follow-up lengths in days. Whether intervals derived from dates are acceptable is a question for the expert.
- No geography is released (the source has none; the cohort pipeline's ETL does not load addresses).
- Ages are top-coded. The person summary and trial table release ages in ten-year bins, the last one "90 or older," as Safe Harbor allows; that bin decodes to 90.
- Codes: genotype study codes and lab notebook subject codes are random (section 1).

**Genomic data.** A genome is identifying in itself, which is why genomic data sit behind controlled access. Homer and colleagues showed in 2008 that a person's presence in a study can be detected even from summary allele frequencies, and NIH responded by removing aggregate genomic data from its public websites (Zerhouni and Nabel, Science, 2008). The genotypes here are simulated and belong to no one. A version trained on real genotypes would need its own risk assessment, including membership inference on the genotype data.

## Gaps and fixes

In order of importance:

1. **Top-code age at 90.** Done 2026-11-18: the last age bin is "90 or older" in both specs, and every release, report, data card, and methodology figure was remade.
2. **Approval before attacks.** On a real controlled-access source, list the privacy attacks in the data access request and run them only once approved.
3. **Data use limitations in the spec.** Done 2026-11-18: `data_use_limitations` is a required spec field, and every data card prints it.
4. **Random codes for lab notebook subjects.** Done 2026-11-18: `HTN-` codes are assigned in a random order, as the genotype codes are.
5. **Keep registries apart from releases.** Done 2026-11-18: both registries are written to `data/registry/`, outside `data/eln/` and `data/genomics/`.
6. **Attested environment.** Run on real data only inside a system the institution has attested under NIST SP 800-171, with authentication and audit logging if more than one person uses it.
7. **A written rule for derived data.** A synthetic release from controlled data stays within the approved users unless the DAC approves wider sharing.

## Sources

- NIH Genomic Data Sharing Policy, NOT-OD-14-124: https://grants.nih.gov/grants/guide/notice-files/NOT-OD-14-124.html
- Genomic Data Sharing overview: https://grants.nih.gov/policy-and-compliance/policy-topics/sharing-policies/gds/overview
- Implementation Update for Data Management and Access Practices Under the Genomic Data Sharing Policy, NOT-OD-24-157: https://grants.nih.gov/grants/guide/notice-files/NOT-OD-24-157.html
- 45 CFR 164.514, other requirements relating to uses and disclosures of protected health information: https://www.law.cornell.edu/cfr/text/45/164.514
- Homer et al., Resolving individuals contributing trace amounts of DNA to highly complex mixtures using high-density SNP genotyping microarrays, PLoS Genetics 4(8): e1000167, 2008: https://pmc.ncbi.nlm.nih.gov/articles/PMC2516199
- Zerhouni and Nabel, Protecting aggregate genomic data, Science, 2008: https://www.genome.gov/Pages/About/NACHGR/September2008Agenda/ProjectingAggregateGenomicData.pdf
