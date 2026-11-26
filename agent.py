import datetime
import os
from dotenv import load_dotenv
from livekit import agents
from livekit.agents import Agent, AgentServer, AgentSession, RunContext, function_tool
from livekit.agents.beta.tools import EndCallTool
from livekit.plugins import deepgram, groq, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

import db

load_dotenv()


def build_prompt() -> str:
    today = datetime.date.today()
    return f"""You are Maya, the receptionist at Smile Dental.
Today is {today:%A, %d %B %Y} ({today.isoformat()}).
The clinic is open Monday to Saturday.

Your job: help the caller book an appointment, in this order:
1. Find out which day they want (skip this if they already said it).
2. Call check_availability straight away (don't ask permission).
3. Offer only the free times it returned.
4. Ask for their name.
5. Repeat the day, time and name back, then STOP and wait for the caller to say yes.
6. Only after they say yes, call book_appointment.
7. Tell them the result, then ask if there is anything else.

Rules:
- Do only ONE step per reply: ask one question, then stop and wait.
- Keep every reply short: one or two sentences.
- You are speaking out loud: no lists, emojis, symbols or notes like (wait).
- Say times like a person: "two PM", not "14:00".
- Turn words like "tomorrow", "next Monday" or "after one month" into a date
  yourself and call check_availability straight away.
- Never say a weekday unless a tool gave it to you.
- Say dates like a person: "Friday the 25th of December", not "2026-12-25".
- You are Maya. The caller is someone else, so always ask for their name.
- Never say it is booked unless book_appointment confirmed it.
- Never write the caller's words for them. Only speak as Maya."""


def say_date(date: str) -> str:
    """'2026-12-20' -> 'Sunday 20 December 2026'. Python knows the calendar, the LLM doesn't."""
    return f"{datetime.date.fromisoformat(date):%A %d %B %Y}"


class Receptionist(Agent):
    def __init__(self):
        super().__init__(
            instructions=build_prompt(),
            tools=[
                EndCallTool(
                    extra_description="Only call this after the caller says goodbye "
                    "or says they need nothing else."
                )
            ],
        )

    @function_tool()
    async def check_availability(self, context: RunContext, date: str) -> str:
        """Look up free appointment times for one day.

        Args:
            date: The day in YYYY-MM-DD format, for example 2026-11-27.
        """
        slots = db.free_slots(date)
        if not slots:
            return f"No free slots on {say_date(date)}. Tell the caller and ask for another day."
        return f"Free slots on {say_date(date)}: {', '.join(slots)}"

    @function_tool()
    async def book_appointment(
        self, context: RunContext, name: str, date: str, time: str
    ) -> str:
        """Book an appointment. Only call this after the caller chose a time,
        told you their name, and confirmed the details.

        Args:
            name: The caller's full name.
            date: The day in YYYY-MM-DD format.
            time: The time in 24-hour HH:MM format, one of the free slots.
        """
        if not name.strip() or "[" in name or name.strip().lower() == "maya":
            return "You don't know the caller's name yet. Ask for it first."
        booking_id = db.book(name, date, time)
        if booking_id is None:
            return "That slot is not available. Offer the caller another free time."
        return f"Booked. Booking number {booking_id} for {name} on {say_date(date)} at {time}."


async def save_transcript(ctx: agents.JobContext):
    """Runs once when a call ends: saves the conversation to transcripts/."""
    lines = []
    for item in ctx.primary_session.history.items:
        if item.type == "message" and item.role in ("user", "assistant"):
            who = "Maya" if item.role == "assistant" else "Caller"
            lines.append(f"{who}: {item.text_content}")
        elif item.type == "function_call":
            lines.append(f"    [tool] {item.name} {item.arguments}")
        elif item.type == "function_call_output":
            lines.append(f"    [result] {item.output}")

    os.makedirs("transcripts", exist_ok=True)
    filename = f"transcripts/{datetime.datetime.now():%Y-%m-%d_%H-%M-%S}.txt"
    with open(filename, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Transcript saved: {filename}")


server = AgentServer()


@server.rtc_session(on_session_end=save_transcript)
async def entrypoint(ctx: agents.JobContext):
    session = AgentSession(
        vad=silero.VAD.load(),
        stt=deepgram.STT(model="nova-3", language="en-IN"),
        turn_detection=MultilingualModel(),
        llm=groq.LLM(model="openai/gpt-oss-120b", reasoning_effort="medium"),
        tts=deepgram.TTS(model="aura-2-thalia-en"),
    )
    await session.start(room=ctx.room, agent=Receptionist())
    await session.generate_reply(instructions="Greet the caller and ask how you can help.")


if __name__ == "__main__":
    agents.cli.run_app(server)