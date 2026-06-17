import uuid
from sqlalchemy import (
    Column, String, Integer, ForeignKey, Text, DateTime,
    Table, CheckConstraint, UniqueConstraint, Boolean,
)
from sqlalchemy.dialects.postgresql import UUID, TSVECTOR, JSONB
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func

Base = declarative_base()

# ── Association table: chat ↔ subjects (many-to-many) ──────────────────────
chat_subject_contexts = Table(
    "chat_subject_contexts",
    Base.metadata,
    Column(
        "chat_session_id",
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "subject_id",
        UUID(as_uuid=True),
        ForeignKey("subjects.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

# ── Association table: chat ↔ focus areas (level-1 hierarchy nodes, many-to-many) ──
chat_focus_areas = Table(
    "chat_focus_areas",
    Base.metadata,
    Column(
        "chat_session_id",
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "node_id",
        UUID(as_uuid=True),
        ForeignKey("hierarchy_nodes.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


# ── 1. Profiles ─────────────────────────────────────────────────────────────
class Profile(Base):
    __tablename__ = "profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=True)
    year = Column(String, nullable=True)
    course = Column(String, nullable=True)
    email = Column(String, unique=True, nullable=False)
    is_admin = Column(Boolean, nullable=False, default=False)
    is_approved = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    subjects = relationship("Subject", back_populates="user", cascade="all, delete-orphan")
    chat_sessions = relationship("ChatSession", back_populates="user", cascade="all, delete-orphan")
    starred_responses = relationship("StarredResponse", back_populates="user", cascade="all, delete-orphan")


# ── 2. Subjects ─────────────────────────────────────────────────────────────
class Subject(Base):
    __tablename__ = "subjects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    book_title = Column(String, nullable=True)
    file_path = Column(String, nullable=True)
    processing_status = Column(String, nullable=False, default="pending")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "processing_status IN ('pending','processing','ready','failed')",
            name="processing_status_check",
        ),
    )

    user = relationship("Profile", back_populates="subjects")
    uploads = relationship("DocumentUpload", back_populates="subject", cascade="all, delete-orphan")
    nodes = relationship("HierarchyNode", back_populates="subject", cascade="all, delete-orphan")
    chat_sessions = relationship("ChatSession", secondary=chat_subject_contexts, back_populates="subjects")


# ── 3. Document Uploads ─────────────────────────────────────────────────────
class DocumentUpload(Base):
    __tablename__ = "document_uploads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subject_id = Column(UUID(as_uuid=True), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False)
    filename = Column(String, nullable=False)
    status = Column(String, nullable=False)
    progress = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    document_type = Column(String, nullable=True)
    toc_method_used = Column(String, nullable=True)
    hierarchy_node_count = Column(Integer, nullable=True)
    chunk_count = Column(Integer, nullable=True)
    processing_time_seconds = Column(Integer, nullable=True)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    processed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('uploaded', 'detected_digital', 'detected_scanned', 'binarising', 'extracting_ocr', 'extracting_toc', 'building_hierarchy', 'chunking', 'indexing', 'completed', 'failed')",
            name='status_check'
        ),
    )

    subject = relationship("Subject", back_populates="uploads")


# ── 4. Hierarchy Nodes ──────────────────────────────────────────────────────
class HierarchyNode(Base):
    __tablename__ = "hierarchy_nodes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subject_id = Column(UUID(as_uuid=True), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False)
    parent_id = Column(UUID(as_uuid=True), ForeignKey("hierarchy_nodes.id", ondelete="CASCADE"), nullable=True)
    title = Column(String, nullable=False)
    node_type = Column(String, nullable=False)
    page_start = Column(Integer, nullable=True)
    page_end = Column(Integer, nullable=True)
    level = Column(Integer, nullable=False)
    path = Column(String, nullable=False)
    metadata_ = Column("metadata", JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    subject = relationship("Subject", back_populates="nodes")
    parent = relationship("HierarchyNode", remote_side=[id], back_populates="children")
    children = relationship("HierarchyNode", back_populates="parent", cascade="all, delete-orphan")
    chunks = relationship("ContentChunk", back_populates="node", cascade="all, delete-orphan")


# ── 5. Content Chunks ───────────────────────────────────────────────────────
class ContentChunk(Base):
    __tablename__ = "content_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    node_id = Column(UUID(as_uuid=True), ForeignKey("hierarchy_nodes.id", ondelete="CASCADE"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    text_content = Column(Text, nullable=False)
    page_start = Column(Integer, nullable=True)
    page_end = Column(Integer, nullable=True)
    fts_vector = Column(TSVECTOR, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("node_id", "chunk_index", name="unique_node_chunk_index"),
    )

    node = relationship("HierarchyNode", back_populates="chunks")


# ── 6. Chat Sessions ────────────────────────────────────────────────────────
class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    title = Column(String, nullable=False, default="New Chat")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("Profile", back_populates="chat_sessions")
    messages = relationship("ChatMessage", back_populates="chat_session", cascade="all, delete-orphan")
    subjects = relationship("Subject", secondary=chat_subject_contexts, back_populates="chat_sessions")
    focus_areas = relationship("HierarchyNode", secondary=chat_focus_areas)


# ── 7. Chat Messages ────────────────────────────────────────────────────────
class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chat_session_id = Column(UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    metadata_ = Column("metadata", JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("role IN ('user','assistant')", name="role_check"),
    )

    chat_session = relationship("ChatSession", back_populates="messages")
    starred_by = relationship("StarredResponse", back_populates="message", cascade="all, delete-orphan")


# ── 8. Starred Responses ────────────────────────────────────────────────────
class StarredResponse(Base):
    __tablename__ = "starred_responses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    message_id = Column(UUID(as_uuid=True), ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "message_id", name="unique_user_message_star"),
    )

    user = relationship("Profile", back_populates="starred_responses")
    message = relationship("ChatMessage", back_populates="starred_by")
