"""Thin wrapper around TypeSafe.ai's Jev model for classifying a condensed
case file.

Jev (https://typesafe.ai, SDK package `typesafe-sdk`) is a "typed decision"
model: instead of generating text you hand it, you hand it a `state` plus one
or more typed `questions` (Choice / Score / Noul) and get back a typed
answer with a calibrated probability -- no JSON parsing, no free-text to
coerce. That's the "type safety" this project is built to try out, and the
reason the docx/pdf parsers above exist: Jev is billed per input token, so
feeding it the condensed tags+blocks instead of the full case file is the
whole point.

Question design here follows TypeSafe's own integration guidance (the
`typesafe-ai` skill):
  - All three questions below share the same state, so they're asked in one
    `system_one` call instead of two -- the state is paid for once instead
    of twice for a policy aff, which is exactly the token cost this project
    is trying to avoid ("bundle questions that share state").
  - The country question is asked speculatively alongside a `country_specific`
    Noul, and code decides which answer to use, rather than only asking it
    after a second round trip ("ask speculatively").
  - "All/Non-Specified" is kept out of the country Choice's own criteria --
    mixing a catch-all option in with eight concrete countries is exactly
    the kind of option that can quietly pull probability toward itself or
    away from the real answer ("keep options distinct and concrete";
    "ask about the null case separately"). A dedicated Noul handles that
    distinction instead, and code applies the result.
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
]

K_AFF = "K-aff"
POLICY_AFF = "Policy aff"
ALL_NON_SPECIFIED = "All/Non-Specified"

# A companion Noul decides whether to trust the country Choice at all,
# rather than using the Choice's own confidence as that gate -- confidence
# measures how concentrated the answer is, not whether the premise (a
# specific country is named) holds in the first place.
COUNTRY_SPECIFIC_THRESHOLD = 0.7


@dataclass
class ClassificationResult:
    aff_type: str
    aff_type_confidence: float | None
    country: str | None
    country_confidence: float | None


def _build_client(api_key: str):
    from typesafe_sdk import TypeSafeClient

    return TypeSafeClient(model="jev-latest", api_key=api_key)


def verify_api_key(api_key: str) -> None:
    """Confirms the Jev API key works before committing to a whole
    tournament run. This calls the models-list endpoint, not system_one --
    no state or questions are sent, so it costs no Jev input tokens.
    Raises on failure (e.g. typesafe_sdk.TypeSafeAuthenticationError)."""
    client = _build_client(api_key)
    client.models.list()


def classify_aff(condensed_text: str, api_key: str) -> ClassificationResult:
    from typesafe_sdk import Choice, Noul

    if not condensed_text.strip():
        raise ValueError("Nothing to classify -- condensed case text is empty")

    client = _build_client(api_key)

    aff_type_question = Choice(
        instructions="Is this debate affirmative case a K-aff or a policy aff?",
        criteria={
            K_AFF: "Centers a critique, narrative, poetry, performance, or framework argument rather than a USFG policy plan.",
            POLICY_AFF: "Defends a specific plan of government action, with case-style advantages and solvency evidence.",
        },
    )

    country_specific_question = Noul(
        instructions="Is this affirmative's plan specifically about one named country?",
        criteria={
            "true": (
                "The plan engages with, withdraws from, sanctions, sends aid to, or otherwise "
                "specifically targets one particular country."
            ),
            "false": (
                "The plan is multilateral, domestic, or otherwise not tied to any single named "
                "country."
            ),
        },
    )

    country_question = Choice(
        instructions="Which country is this affirmative's plan most specifically about?",
        criteria={country: country for country in COUNTRIES},
    )

    response = client.system_one(
        state=condensed_text,
        questions={
            "aff_type": aff_type_question,
            "country_specific": country_specific_question,
            "country": country_question,
        },
    )

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

    is_country_specific = response.nouls["country_specific"].noul >= COUNTRY_SPECIFIC_THRESHOLD
    if not is_country_specific:
        return ClassificationResult(
            aff_type=aff_type,
            aff_type_confidence=aff_confidence,
            country=ALL_NON_SPECIFIED,
            country_confidence=None,
        )

    country_answer = response.choices["country"]
    return ClassificationResult(
        aff_type=aff_type,
        aff_type_confidence=aff_confidence,
        country=country_answer.choice,
        country_confidence=getattr(country_answer, "confidence", None),
    )
