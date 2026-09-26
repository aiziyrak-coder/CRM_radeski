"""AI reply drafts for chats (plan 5.4). The operator edits and sends; nothing is sent by AI."""

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.llm import get_llm
from app.modules.ai.prompts import mask_pii
from app.modules.ai.qa import patient_facts
from app.modules.catalog.models import Branch, Service
from app.modules.messaging.models import Conversation, Direction, Message
from app.modules.patients.models import Patient

HISTORY = 12


class DraftOut(BaseModel):
    text: str = Field(description="the reply, ready to send after the operator reads it")


async def _clinic_facts(session: AsyncSession) -> str:
    branches = await session.scalars(select(Branch).where(Branch.is_active))
    services = await session.scalars(
        select(Service).where(Service.is_active).order_by(Service.name_ru).limit(200)
    )
    lines = ["Branches:"]
    lines += [f"- {b.name_uz}: {b.address_uz or ''} tel. {b.phone or ''}" for b in branches]
    lines += ["", "Services (price in UZS where known):"]
    lines += [
        f"- {s.name_ru} / {s.name_uz}" + (f": {s.price} so'm" if s.price else "") for s in services
    ]
    return "\n".join(lines)


def _system(clinic: str) -> str:
    return "\n".join(
        [
            "You draft replies for the chat operator of Radeski Skin Clinic (dermatology, "
            "trichology, cosmetology, laser) in Fergana and Kokand, Uzbekistan.",
            "Rules:",
            "- Answer in the language of the patient's last message (Uzbek Latin or Russian).",
            "- 1-4 short, warm sentences. No emojis spam, no long lists.",
            "- Never name a diagnosis or recommend treatment/medicine: offer a doctor's "
            "consultation instead.",
            "- Prices and addresses only from the facts below; if unknown, say the operator will "
            "clarify. Never promise results.",
            "- Move towards booking: ask which day/time suits them and, if we don't have it, "
            "their phone number.",
            "",
            clinic,
        ]
    )


async def draft_reply(session: AsyncSession, conv: Conversation) -> str:
    rows = list(
        await session.scalars(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at.desc())
            .limit(HISTORY)
        )
    )
    rows.reverse()
    lines = []
    if conv.patient_id and (patient := await session.get(Patient, conv.patient_id)):
        lines += ["Known patient:", *(f"- {f}" for f in await patient_facts(session, patient)), ""]
    lines.append("Chat so far:")
    lines += [
        f"{'Patient' if m.direction is Direction.IN else 'Clinic'}: {mask_pii(m.text)}"
        for m in rows
    ]
    llm = get_llm()
    out = await llm.parse(
        system=_system(await _clinic_facts(session)),
        user="\n".join(lines),
        schema=DraftOut,
        cache_key="chat-draft-v1",
    )
    return out.text.strip()
