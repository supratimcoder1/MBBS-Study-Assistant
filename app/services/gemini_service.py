"""
Gemini API Service
Wraps the Google GenAI client to generate study-assistant responses
grounded in retrieved medical textbook context.
"""

import logging
from google import genai

from app.core.config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

# Initialise the Gemini client once at module level
client = genai.Client(api_key=GEMINI_API_KEY)

# The model to use for generation
MODEL_ID = "gemini-3.1-flash-lite"

SYSTEM_INSTRUCTION = (
    "You are an MBBS study assistant. Answer questions primarily using the provided "
    "context from medical textbooks and cite the source section and page numbers. "
    "If the context is missing, limited, or does not contain enough information to fully answer the "
    "question, use your own general medical knowledge base to provide a complete explanation. "
    "In such cases, clearly specify what information was retrieved from the textbook context "
    "and what was supplemented from your own knowledge base. "
    "Use clear, concise language appropriate for medical students. "
    "Format your answers with headings, bullet points, and bold terms where helpful. "
    "Whenever a process, pathway, or sequence of events is described (or when the user "
    "explicitly requests it), generate a flowchart in text format (using arrows like '->' or "
    "indented blocks) to clearly illustrate the clinical/physiological pathway."
)


def reformulate_query(query: str, chat_history: list[dict] | None = None) -> str:
    """
    Use Gemini to reformulate a follow-up query to be self-contained for search.
    If there is no history or the operation fails, return the original query.
    """
    if not chat_history:
        return query

    # Format the recent history for the model (last 3 turns to keep context tight and fast)
    history_str = ""
    for msg in chat_history[-3:]:
        role = "User" if msg["role"] == "user" else "Assistant"
        history_str += f"{role}: {msg['content']}\n"

    prompt = (
        f"Given the following conversation history and a follow-up question, "
        f"rewrite the follow-up question to be a standalone search query that contains all necessary context "
        f"to search a medical textbook. Do NOT answer the question. Just output the search query.\n\n"
        f"Conversation History:\n{history_str}\n"
        f"Follow-up Question: {query}\n\n"
        f"Standalone Search Query:"
    )
    try:
        from google import genai
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=100,
            ),
        )
        rewritten = response.text or ""
        rewritten = rewritten.strip()
        # Clean any Standalone Search Query: prefixes if returned
        for prefix in ("Standalone Search Query:", "Standalone Search Query"):
            if rewritten.startswith(prefix):
                rewritten = rewritten[len(prefix):].strip()
        
        if rewritten:
            logger.info("Reformulated query: '%s' -> '%s'", query, rewritten)
            return rewritten
    except Exception as e:
        logger.exception("Failed to reformulate query: %s", e)

    return query


def generate_response(
    query: str,
    context_chunks: list[dict],
    chat_history: list[dict] | None = None,
) -> str:
    """
    Build a prompt from the retrieved context chunks and conversation history,
    then call the Gemini API and return the generated text.

    Parameters
    ----------
    query : str
        The user's current question.
    context_chunks : list[dict]
        Retrieved chunks, each with keys: text, title, path, page_start, page_end.
    chat_history : list[dict] | None
        Recent messages as [{"role": "user"|"assistant", "content": "..."}].

    Returns
    -------
    str
        The assistant's generated answer.
    """
    # ── Format context ──────────────────────────────────────────────────
    context_parts: list[str] = []
    for i, chunk in enumerate(context_chunks, start=1):
        header = (
            f"[Source {i}] {chunk.get('path', chunk.get('title', 'Unknown'))} "
            f"(pages {chunk.get('page_start', '?')}–{chunk.get('page_end', '?')})"
        )
        context_parts.append(f"{header}\n{chunk.get('text', '')}")

    context_block = "\n\n---\n\n".join(context_parts) if context_parts else "(No context available)"

    # ── Build message history for the API ───────────────────────────────
    contents: list[dict] = []

    # Include recent chat history for conversational context
    if chat_history:
        for msg in chat_history:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})

    # Current user turn with context
    user_message = (
        f"## Reference Material\n\n{context_block}\n\n"
        f"---\n\n## Question\n\n{query}"
    )
    contents.append({"role": "user", "parts": [{"text": user_message}]})

    # ── Call Gemini ─────────────────────────────────────────────────────
    try:
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=contents,
            config=genai.types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.3,
                max_output_tokens=4096,
            ),
        )
        answer = response.text or "I'm sorry, I wasn't able to generate a response."
        return answer

    except Exception as exc:
        logger.exception("Gemini API call failed: %s", exc)
        return (
            "I'm sorry, an error occurred while generating a response. "
            "Please try again later."
        )
