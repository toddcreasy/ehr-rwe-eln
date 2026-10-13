"""What an extraction from one ELN entry must look like. The LLM returns this model, and every
extraction is validated against it before anything is written.

An entry describes bench assays on specimens collected from study subjects. Only subject
specimens count: QC material, calibrators, and blanks are not samples, and a value an entry says
to discard (a failed run that was repeated) is not a result.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

SpecimenType = Literal["serum", "plasma", "whole blood", "urine"]

# Canonical analyte names; module 2's OMOP step maps each to a standard LOINC concept.
Analyte = Literal["creatinine", "hba1c", "crp", "hs_crp", "il6", "nt_probnp"]

# Units as UCUM codes (the Unified Code for Units of Measure), the form OMOP and FHIR use.
Unit = Literal["mg/dL", "umol/L", "%", "mmol/mol", "mg/L", "pg/mL"]


class Sample(BaseModel):
    sample_id: str = Field(
        description="The specimen's identifier exactly as written, e.g. S-0007-02."
    )
    subject_id: str = Field(description="The study subject code exactly as written, e.g. HTN-0007.")
    specimen_type: SpecimenType
    collection_date: date | None = Field(
        default=None, description="The day the specimen was collected, if the entry gives it."
    )


class Result(BaseModel):
    sample_id: str = Field(description="The sample this result was measured on.")
    analyte: Analyte
    value: float = Field(description="The reported value, in the unit given.")
    unit: Unit = Field(description="The unit as a UCUM code, whatever spelling the entry used.")


class Extraction(BaseModel):
    samples: list[Sample]
    results: list[Result]
