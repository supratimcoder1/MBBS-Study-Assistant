-- =============================================================================
-- MBBS Study Assistant – Full Database Schema
-- Run this in the Supabase SQL editor to bootstrap the database.
-- =============================================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ─── 1. Profiles ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    name TEXT,
    year TEXT,
    course TEXT,
    email TEXT UNIQUE NOT NULL,
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    is_approved BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── 2. Subjects ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.subjects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    book_title TEXT,
    file_path TEXT,
    processing_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (processing_status IN ('pending','processing','ready','failed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── 3. Document Uploads ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.document_uploads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id UUID NOT NULL REFERENCES public.subjects(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    status TEXT NOT NULL
      CONSTRAINT status_check CHECK (status IN ('uploaded', 'ocr_processing', 'extracting', 'building_hierarchy', 'chunking', 'indexing', 'completed', 'failed')),
    progress INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    document_type TEXT,
    toc_method_used TEXT,
    hierarchy_node_count INTEGER,
    chunk_count INTEGER,
    processing_time_seconds INTEGER,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ
);

-- ─── 4. Hierarchy Nodes ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.hierarchy_nodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id UUID NOT NULL REFERENCES public.subjects(id) ON DELETE CASCADE,
    parent_id UUID REFERENCES public.hierarchy_nodes(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    node_type TEXT NOT NULL,
    page_start INTEGER,
    page_end INTEGER,
    level INTEGER NOT NULL,
    path TEXT NOT NULL,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── 5. Content Chunks ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.content_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    node_id UUID NOT NULL REFERENCES public.hierarchy_nodes(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    text_content TEXT NOT NULL,
    page_start INTEGER,
    page_end INTEGER,
    fts_vector TSVECTOR,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT unique_node_chunk_index UNIQUE (node_id, chunk_index)
);

-- ─── 6. Chat Sessions ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.chat_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT 'New Chat',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── 7. Chat Subject Contexts (M2M) ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.chat_subject_contexts (
    chat_session_id UUID NOT NULL REFERENCES public.chat_sessions(id) ON DELETE CASCADE,
    subject_id UUID NOT NULL REFERENCES public.subjects(id) ON DELETE CASCADE,
    PRIMARY KEY (chat_session_id, subject_id)
);

-- ─── 7b. Chat Focus Areas (M2M – Level-1 hierarchy filter) ─────────────────
CREATE TABLE IF NOT EXISTS public.chat_focus_areas (
    chat_session_id UUID NOT NULL REFERENCES public.chat_sessions(id) ON DELETE CASCADE,
    node_id UUID NOT NULL REFERENCES public.hierarchy_nodes(id) ON DELETE CASCADE,
    PRIMARY KEY (chat_session_id, node_id)
);

-- ─── 8. Chat Messages ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_session_id UUID NOT NULL REFERENCES public.chat_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user','assistant')),
    content TEXT NOT NULL,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── 9. Starred Responses ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.starred_responses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    message_id UUID NOT NULL REFERENCES public.chat_messages(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT unique_user_message_star UNIQUE (user_id, message_id)
);


-- =============================================================================
-- INDEXES
-- =============================================================================
CREATE INDEX IF NOT EXISTS content_chunks_fts_idx ON public.content_chunks USING gin(fts_vector);
CREATE INDEX IF NOT EXISTS hierarchy_nodes_path_idx ON public.hierarchy_nodes(path);
CREATE INDEX IF NOT EXISTS hierarchy_nodes_parent_idx ON public.hierarchy_nodes(parent_id);
CREATE INDEX IF NOT EXISTS hierarchy_nodes_subject_idx ON public.hierarchy_nodes(subject_id);
CREATE INDEX IF NOT EXISTS profiles_email_idx ON public.profiles(email);
CREATE INDEX IF NOT EXISTS subjects_user_idx ON public.subjects(user_id);
CREATE INDEX IF NOT EXISTS document_uploads_subject_idx ON public.document_uploads(subject_id);
CREATE INDEX IF NOT EXISTS content_chunks_node_idx ON public.content_chunks(node_id);
CREATE INDEX IF NOT EXISTS content_chunks_ordering_idx ON public.content_chunks(node_id, chunk_index);
CREATE INDEX IF NOT EXISTS chat_sessions_user_idx ON public.chat_sessions(user_id);
CREATE INDEX IF NOT EXISTS chat_messages_chat_session_idx ON public.chat_messages(chat_session_id);
CREATE INDEX IF NOT EXISTS chat_focus_areas_session_idx ON public.chat_focus_areas(chat_session_id);


-- =============================================================================
-- FTS TRIGGER
-- =============================================================================
CREATE OR REPLACE FUNCTION content_chunks_trigger() RETURNS trigger AS $$
BEGIN
    NEW.fts_vector := to_tsvector('english', coalesce(NEW.text_content, ''));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tsvectorupdate ON public.content_chunks;
CREATE TRIGGER tsvectorupdate
    BEFORE INSERT OR UPDATE ON public.content_chunks
    FOR EACH ROW EXECUTE FUNCTION content_chunks_trigger();


-- =============================================================================
-- ROW LEVEL SECURITY
-- =============================================================================
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.subjects ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.document_uploads ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.hierarchy_nodes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.content_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_subject_contexts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_focus_areas ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.starred_responses ENABLE ROW LEVEL SECURITY;

-- Profiles
CREATE POLICY "Users can view and edit their own profiles"
    ON public.profiles FOR ALL USING (auth.uid() = id);

-- Subjects
CREATE POLICY "Users can manage their own subjects"
    ON public.subjects FOR ALL USING (auth.uid() = user_id);

-- Document Uploads
CREATE POLICY "Users can manage document uploads belonging to their subjects"
    ON public.document_uploads FOR ALL USING (
        EXISTS (SELECT 1 FROM public.subjects WHERE id = subject_id AND user_id = auth.uid())
    );

-- Hierarchy Nodes
CREATE POLICY "Users can manage hierarchy nodes belonging to their subjects"
    ON public.hierarchy_nodes FOR ALL USING (
        EXISTS (SELECT 1 FROM public.subjects WHERE id = subject_id AND user_id = auth.uid())
    );

-- Content Chunks
CREATE POLICY "Users can manage content chunks belonging to their subjects"
    ON public.content_chunks FOR ALL USING (
        EXISTS (
            SELECT 1 FROM public.hierarchy_nodes hn
            JOIN public.subjects s ON hn.subject_id = s.id
            WHERE hn.id = node_id AND s.user_id = auth.uid()
        )
    );

-- Chat Sessions
CREATE POLICY "Users can manage their own chat sessions"
    ON public.chat_sessions FOR ALL USING (auth.uid() = user_id);

-- Chat Subject Contexts
CREATE POLICY "Users can manage their own chat context mapping"
    ON public.chat_subject_contexts FOR ALL USING (
        EXISTS (SELECT 1 FROM public.chat_sessions cs WHERE cs.id = chat_session_id AND cs.user_id = auth.uid())
    );

-- Chat Focus Areas
CREATE POLICY "Users can manage their own chat focus area selections"
    ON public.chat_focus_areas FOR ALL USING (
        EXISTS (SELECT 1 FROM public.chat_sessions cs WHERE cs.id = chat_session_id AND cs.user_id = auth.uid())
    );

-- Chat Messages
CREATE POLICY "Users can manage chat messages in their own chats"
    ON public.chat_messages FOR ALL USING (
        EXISTS (SELECT 1 FROM public.chat_sessions cs WHERE cs.id = chat_session_id AND cs.user_id = auth.uid())
    );

-- Starred Responses
CREATE POLICY "Users can manage their own starred responses"
    ON public.starred_responses FOR ALL USING (auth.uid() = user_id);


-- =============================================================================
-- AUTO-CREATE PROFILE ON SIGNUP (Supabase trigger)
-- =============================================================================
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger AS $$
BEGIN
    INSERT INTO public.profiles (id, email, name)
    VALUES (
        NEW.id,
        NEW.email,
        COALESCE(NEW.raw_user_meta_data->>'name', '')
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();
