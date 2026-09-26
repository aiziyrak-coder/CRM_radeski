"""Call-analysis prompt and its output schema (TZ 4.8.1).

The system prompt is long and stable (role, scripts, criteria, reference lists) so OpenAI's
prompt caching reuses it; only the transcript at the end changes per call. Bump PROMPT_VERSION
whenever the wording changes: it is stored with every analysis so results stay comparable.
"""

import enum
import re
from typing import Literal

from pydantic import BaseModel, Field

from app.modules.tasks.models import REASONS, Outcome

PROMPT_VERSION = "2026-09-v2"

RED_FLAGS = {
    "diagnosis": "the operator named a diagnosis or recommended a treatment/medicine "
    "(strictly forbidden: only a doctor may do that)",
    "pressure": "the operator pressured, argued with or blamed the patient",
    "false_promise": "the operator promised something the clinic doesn't guarantee "
    "(a cure, an exact result, a price or discount not in the price list)",
    "complaint": "the patient complained or was clearly unhappy with the clinic or a doctor",
}
RedFlagCode = Literal["diagnosis", "pressure", "false_promise", "complaint"]
ReasonCode = enum.StrEnum("ReasonCode", {r.upper(): r for r in REASONS})

# default criteria (TZ 4.8.1 #3); the supervisor edits them in the QA panel
DEFAULT_CRITERIA = [
    ("greeting", "Klinika nomi va ismini aytib salomlashdi", "Поздоровался, назвал клинику и имя",
     "Greeted the caller, named the clinic (Radeski) and their own name.", 10),
    ("patient_name", "Bemorning ismini so'radi", "Спросил имя пациента",
     "Asked how to address the patient (their name).", 10),
    ("need", "Ehtiyojni aniqladi", "Выяснил потребность",
     "Found out the problem or the service the patient is interested in.", 15),
    ("two_slots", "Aniq 2 ta vaqt taklif qildi", "Предложил 2 конкретных времени",
     "Offered two concrete appointment options (day and time), not an open question.", 15),
    ("next_step", "Keyingi qadamni taklif qildi", "Предложил следующий шаг",
     "Proposed the next step: booking, a consultation or an agreed callback.", 15),
    ("confirm", "Yozuvni sana va vaqt bilan takrorladi", "Повторил запись с датой и временем",
     "Repeated the booking back with the date and time. Not applicable if nothing was booked.", 10),
    ("polite", "Xushmuomala va qisqa gapirdi", "Вежливо и кратко",
     "Was polite, friendly and to the point; no long monologues.", 15),
    ("closing", "Skript bo'yicha yakunladi", "Завершил по скрипту",
     "Closed the call as the script says (thanks, goodbye, what happens next).", 10),
]  # fmt: skip


class CriterionResult(BaseModel):
    code: str
    passed: bool | None = Field(description="null when the criterion doesn't apply to this call")
    comment: str = Field(description="empty when passed; otherwise one short sentence, Uzbek")


class Violation(BaseModel):
    criterion: str = Field(description="criterion code that was not met")
    quote: str = Field(description="the operator's words, copied from the transcript")
    at: float | None = Field(description="seconds from the start, from the transcript marks")


class RedFlag(BaseModel):
    code: RedFlagCode
    quote: str
    at: float | None


class Extracted(BaseModel):
    interest: str | None = Field(description="service or problem the patient asked about")
    preferred_time: str | None = Field(description="when the patient wants to come")
    source: str | None = Field(description="how they heard of the clinic, if said")
    next_step: str | None = Field(description="agreed next step, e.g. 'call back on Friday'")


class AnalysisOut(BaseModel):
    conversation_type: str = Field(description="code of the script that fits this call best")
    language: Literal["uz", "ru", "mixed"]
    criteria: list[CriterionResult]
    violations: list[Violation]
    red_flags: list[RedFlag]
    summary: str = Field(description="2-3 sentences in Uzbek (Latin): who, what, result")
    outcome: Outcome | None = Field(description="call result, null if unclear")
    reason: ReasonCode | None = Field(description="refusal/cancellation reason when applicable")
    extracted: Extracted
    questions: list[str] = Field(description="questions the patient asked, short, in Uzbek")
    objections: list[str] = Field(description="patient's objections/doubts, short, in Uzbek")


OUTCOME_HELP = {
    "booked": "an appointment was made during the call",
    "confirmed": "the patient confirmed an existing appointment",
    "rescheduled": "an existing appointment was moved",
    "cancelled": "the patient cancelled an appointment",
    "refused": "the patient declined (needs a reason)",
    "thinking": "the patient will think about it",
    "callback": "agreed to talk again at a set time",
    "no_answer": "nobody talked (voicemail, silence)",
    "wrong_number": "wrong person / number",
    "do_not_call": "asked never to be called again",
    "done": "talked, nothing to book (information only, check-up call went fine)",
}


def system_prompt(
    criteria: list[tuple[str, str, str]], scripts: list[tuple[str, str, str | None]]
) -> str:
    """criteria: (code, name, description); scripts: (code, title, body or None). Keep it short:
    every token here is paid for on every analysed call."""
    lines = [
        "You are the quality-control analyst of Radeski Skin Clinic's call center "
        "(dermatology, trichology, cosmetology, laser; Fergana and Kokand, Uzbekistan).",
        "You get one phone call transcript between a clinic OPERATOR (O) and a PATIENT (P). "
        "Speech is Uzbek (Latin or Cyrillic, dialects), Russian or mixed; the transcript comes "
        "from speech recognition and may contain errors — judge the meaning, not the spelling.",
        "Each line starts with [seconds from the start]. Use those numbers for `at`.",
        "",
        "Rules:",
        "- Judge only the operator's behaviour for criteria and violations.",
        "- Quote the transcript exactly; never invent quotes. Phone numbers appear as [raqam].",
        "- Every criterion below must appear exactly once in `criteria` (use its code). "
        "passed=null when it can't apply (e.g. 'confirm' when nothing was booked).",
        "- A violation is a criterion with passed=false; give the operator quote that shows it "
        "(or the moment it should have happened).",
        "- Write summary, comments, questions and objections in Uzbek (Latin script).",
        "- The operator must never give medical advice; the doctor does that.",
        "",
        "Criteria:",
        *(f"- {code}: {name} — {desc}" for code, name, desc in criteria),
        "",
        "Red flags (report every occurrence, with a quote):",
        *(f"- {code}: {desc}" for code, desc in RED_FLAGS.items()),
        "",
        "Call outcomes (`outcome`):",
        *(f"- {code}: {desc}" for code, desc in OUTCOME_HELP.items()),
        "",
        "Refusal / cancellation reasons (`reason`): " + ", ".join(REASONS) + ".",
        "",
        "Call script codes (`conversation_type` is one of them):",
        *(f"- {code}: {title}" for code, title, _ in scripts),
        "",
        "Scripts this call is expected to follow:",
    ]
    for code, title, body in scripts:
        if body:
            lines += ["", f"### {code} — {title}", body.strip()]
    return "\n".join(lines)


# phone / document numbers never go to the LLM (TZ: data protection). Digit groups may be split
# by spaces, dashes, brackets, dots or commas (speech recognition writes "90, 123, 45, 67"), but a
# clock time ("10:30") never joins a number.
_DIGITS = re.compile(r"\+?\d(?:(?:[\s\-()]|[.,]\s?)*(?!\d{1,2}:\d{2})\d)+")


def _mask(m: re.Match) -> str:
    digits = "".join(c for c in m.group() if c.isdigit())
    # 7-8 digits ending in 000 are prices ("1 500 000 so'm"), which the analysis needs
    if len(digits) >= 9 or (len(digits) >= 7 and not digits.endswith("000")):
        return "[raqam]" + (m.group()[-1] if not m.group()[-1].isdigit() else "")
    return m.group()


def mask_pii(text: str) -> str:
    return _DIGITS.sub(_mask, text)


def user_prompt(context: list[str], transcript: list[dict]) -> str:
    lines = ["Call context:", *(f"- {c}" for c in context), "", "Transcript:"]
    for seg in transcript:
        who = "O" if seg["ch"] == "operator" else "P"
        lines.append(f"[{seg['start']:.1f}] {who}: {mask_pii(seg['text'])}")
    return "\n".join(lines)
