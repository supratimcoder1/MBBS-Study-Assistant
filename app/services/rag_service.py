"""
RAG Retrieval Service
Uses PostgreSQL full-text search (tsvector / tsquery) to find the most
relevant content chunks for a user query, then packages citation metadata.
"""

import logging
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)


def clean_query(query: str) -> str:
    """
    Clean conversational prefixes, fillers and trailing question marks from the user query
    to optimize full-text search term extraction.
    """
    import re
    q = query.strip()
    
    # List of regex patterns to strip from the beginning of the query
    # Ordered from longest/most specific to shortest/most general
    patterns = [
        r"^(?:write|give)\s+(?:a\s+)?(?:short\s+)?notes?\s+(?:on|about)\b",
        r"^(?:can\s+you\s+)?(?:explain|describe|discuss|detail|summarize|outline|define|list)\s+(?:the\s+)?(?:mechanism\s+of\s+action\s+of|mechanism\s+of|pathway\s+of|structure\s+and\s+function\s+of|role\s+of|concept\s+of|meaning\s+of|definition\s+of)?\b",
        r"^(?:what\s+is|what\s+are|how\s+does|how\s+do|why\s+does|why\s+do|tell\s+me\s+about|explain|describe|discuss|detail|summarize|outline|define|list)\s+(?:the\s+)?\b",
        r"^(?:mechanism\s+of\s+action\s+of|mechanism\s+of|pathway\s+of|structure\s+and\s+function\s+of|role\s+of)\s+(?:the\s+)?\b",
    ]
    
    for pattern in patterns:
        new_q = re.sub(pattern, "", q, flags=re.IGNORECASE).strip()
        if new_q and new_q != q:
            q = new_q
            # Clean up leading/trailing punctuation or space
            q = re.sub(r"^[?.,\s]+", "", q).strip()
            break
            
    # Remove trailing question marks and punctuation
    q = re.sub(r"[?\s]+$", "", q).strip()
    return q


def search_chunks(
    db: Session,
    query: str,
    subject_ids: list[str],
    focus_area_ids: list[str] = [],
    limit: int = 10,
) -> list[dict]:
    """
    Full-text search over content_chunks using plainto_tsquery and ts_rank.
    Includes query cleaning/preprocessing and fallback to OR search.

    The query is joined with hierarchy_nodes so each result carries its
    hierarchical path and title alongside the chunk text.

    Parameters
    ----------
    db : Session
        Active SQLAlchemy session.
    query : str
        Natural-language search query.
    subject_ids : list[str]
        UUIDs of subjects to restrict the search to.
    focus_area_ids : list[str]
        Optional UUIDs of level-1 hierarchy nodes. When provided, retrieval
        is restricted to chunks belonging to descendant nodes of these
        focus areas.
    limit : int
        Max number of chunks to return (default 10).

    Returns
    -------
    list[dict]
        Each dict has: text, title, path, page_start, page_end, rank.
    """
    import uuid as _uuid

    # Convert string IDs to uuid.UUID objects to match PostgreSQL column type
    uuid_subject_ids = []
    for sid in subject_ids:
        try:
            uuid_subject_ids.append(_uuid.UUID(str(sid)))
        except (ValueError, TypeError):
            pass

    if not uuid_subject_ids or not query.strip():
        return []

    # Convert focus area IDs
    uuid_focus_ids = []
    for fid in focus_area_ids:
        try:
            uuid_focus_ids.append(_uuid.UUID(str(fid)))
        except (ValueError, TypeError):
            pass

    # If focus areas are selected, look up their path prefixes
    focus_path_prefixes = []
    if uuid_focus_ids:
        from app.models.database import HierarchyNode
        focus_nodes = (
            db.query(HierarchyNode.path)
            .filter(HierarchyNode.id.in_(uuid_focus_ids))
            .all()
        )
        focus_path_prefixes = [row.path for row in focus_nodes if row.path]

    if uuid_focus_ids and not focus_path_prefixes:
        # Focus areas were requested but none resolved — return nothing
        return []

    # Clean the query string
    cleaned_query = clean_query(query)

    # Helper function to run the full-text search with dynamic tsquery expression
    def run_fts(q_str: str, use_or: bool = False) -> list:
        if use_or:
            tsquery_expr = "to_tsquery('english', replace(plainto_tsquery('english', :query)::text, ' & ', ' | '))"
        else:
            tsquery_expr = "plainto_tsquery('english', :query)"

        if focus_path_prefixes:
            # Build dynamic OR conditions for path prefix matching
            path_conditions = " OR ".join(
                f"hn.path LIKE :path_prefix_{i}" for i in range(len(focus_path_prefixes))
            )
            sql = text(f"""
                SELECT
                    cc.text_content   AS text,
                    hn.title          AS title,
                    hn.path           AS path,
                    cc.page_start     AS page_start,
                    cc.page_end       AS page_end,
                    ts_rank(cc.fts_vector, {tsquery_expr}) AS rank
                FROM content_chunks cc
                JOIN hierarchy_nodes hn ON cc.node_id = hn.id
                WHERE hn.subject_id = ANY(:subject_ids)
                  AND cc.fts_vector @@ {tsquery_expr}
                  AND ({path_conditions})
                ORDER BY rank DESC
                LIMIT :limit
            """)
        else:
            sql = text(f"""
                SELECT
                    cc.text_content   AS text,
                    hn.title          AS title,
                    hn.path           AS path,
                    cc.page_start     AS page_start,
                    cc.page_end       AS page_end,
                    ts_rank(cc.fts_vector, {tsquery_expr}) AS rank
                FROM content_chunks cc
                JOIN hierarchy_nodes hn ON cc.node_id = hn.id
                WHERE hn.subject_id = ANY(:subject_ids)
                  AND cc.fts_vector @@ {tsquery_expr}
                ORDER BY rank DESC
                LIMIT :limit
            """)

        params = {
            "query": q_str,
            "subject_ids": uuid_subject_ids,
            "limit": limit,
        }
        for i, prefix in enumerate(focus_path_prefixes):
            params[f"path_prefix_{i}"] = f"{prefix}%"

        return db.execute(sql, params).mappings().all()

    # Try strict AND first with cleaned query
    rows = run_fts(cleaned_query, use_or=False)
    search_mode = "AND (Cleaned)"

    # If 0 matches, fall back to OR search with cleaned query
    if not rows:
        rows = run_fts(cleaned_query, use_or=True)
        search_mode = "OR (Cleaned)"

    # If still 0 matches and cleaned query was different, fall back to OR search with original query
    if not rows and cleaned_query != query:
        rows = run_fts(query, use_or=True)
        search_mode = "OR (Original)"

    results = [dict(row) for row in rows]
    logger.info(
        "FTS search for '%s' (cleaned: '%s', mode: %s) across %d subject(s), %d focus area(s) returned %d chunks",
        query, cleaned_query, search_mode, len(subject_ids), len(focus_area_ids), len(results),
    )
    return results


def build_citation_metadata(chunks: list[dict]) -> dict:
    """
    Extract unique source nodes and page numbers from the retrieved chunks
    to attach as citation metadata on an assistant message.

    Returns
    -------
    dict
        {"source_nodes": ["Section A", ...], "pages": [1, 2, 3, ...]}
    """
    source_nodes: list[str] = []
    pages: set[int] = set()

    for chunk in chunks:
        title = chunk.get("title", "")
        if title and title not in source_nodes:
            source_nodes.append(title)

        for key in ("page_start", "page_end"):
            page = chunk.get(key)
            if page is not None:
                pages.add(page)

    return {
        "source_nodes": source_nodes,
        "pages": sorted(pages),
    }
