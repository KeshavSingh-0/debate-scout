"""Thin wrapper around TypeSafe.ai's Jev model for classifying a condensed
case file.

Jev (https://typesafe.ai, SDK package `typesafe-sdk`) is a "typed decision"
model: instead of generating text you hand it, you hand it a `state` plus one
or more typed `questions` (Choice / Score / Noul) and get back a typed
answer with a confidence score -- no JSON parsing, no free-text to coerce.
That's the "type safety" this project is built to try out, and the reason
the docx/pdf parsers above exist: Jev is billed per input token, so feeding
it the condensed tags+blocks instead of the full case file is the whole
point.

"""

from __future__ import annotations

from dataclasses import dataclass

COUNTRIES = [
    "Nigeria",
    "Japan",
    "Saudi Arabia",
    "Taiwan",
    "Philippines",
    "Israel",
    "Ukraine",
    "Mexico",
    "All/Non-Specified",
]

K_AFF = "K-aff"
POLICY_AFF = "Policy aff"
ALL_NON_SPECIFIED = "All/Non-Specified"


@dataclass
class ClassificationResult:
    aff_type: str
    aff_type_confidence: float | None
    country: str | None
    country_confidence: float | None


def _build_client(api_key: str):
    from typesafe_sdk import TypeSafeClient

    return TypeSafeClient(model="jev-latest", api_key=api_key)


def classify_aff(condensed_text: str, api_key: str) -> ClassificationResult:
    from typesafe_sdk import Choice

    if not condensed_text.strip():
        raise ValueError("Nothing to classify -- condensed case text is empty")

    client = _build_client(api_key)

    aff_type_question = Choice(
        instructions=(
            "Read this debate case file (tags and evidence extracted from an affirmative "
            "case). Decide whether it is a 'K-aff' (a critical/kritikal affirmative that "
            "runs a critique, narrative, or performance instead of/alongside a traditional "
            "policy plan) or a 'Policy aff' (a traditional policy affirmative defending a "
            "plan of action, with stock issues like solvency and advantages/disadvantages)."
        ),
        criteria={
            K_AFF: "Centers a critique, narrative, poetry, performance, or framework argument rather than a USFG policy plan.",
            POLICY_AFF: "Defends a specific plan of government action with case-style advantages and solvency evidence.",
        },
    )

    response = client.system_one(state=condensed_text, questions={"aff_type": aff_type_question})
    aff_answer = response.choices["aff_type"]
    aff_type = aff_answer.choice
    aff_confidence = getattr(aff_answer, "confidence", None)

    if aff_type != POLICY_AFF:
        return ClassificationResult(
            aff_type=aff_type,
            aff_type_confidence=aff_confidence,
            country=ALL_NON_SPECIFIED,
            country_confidence=None,
        )

    country_question = Choice(
        instructions=(
            "This is a policy affirmative case. Identify which single country the plan's "
            "advocacy is most specifically about (e.g. a plan to engage, withdraw troops "
            "from, sanction, or send aid to that country). If the plan is not tied to one "
            "specific country from the list, answer 'All/Non-Specified'."
        ),
        criteria={country: country for country in COUNTRIES},
    )
    country_response = client.system_one(state=condensed_text, questions={"country": country_question})
    country_answer = country_response.choices["country"]

    return ClassificationResult(
        aff_type=aff_type,
        aff_type_confidence=aff_confidence,
        country=country_answer.choice,
        country_confidence=getattr(country_answer, "confidence", None),
    )
