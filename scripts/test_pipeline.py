import os
import sys
import uuid

# Ensure the root directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.pdf_processor import extract_toc, build_hierarchy, extract_chunks

def test_pipeline():
    file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scratch", "Debashis Paramanik (6th ed)_searchable.pdf"))
    
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return

    print(f"Testing pipeline with {file_path}...")
    
    # Test 1: Extract TOC
    print("\n--- Extracting TOC ---")
    toc_entries, method = extract_toc(file_path)
    print(f"Method used: {method}")
    print(f"Total TOC entries: {len(toc_entries)}")
    for i, entry in enumerate(toc_entries[:10]):
        print(f"  {i+1}. {entry}")
    if len(toc_entries) > 10:
        print("  ...")

    # Test 2: Build Hierarchy
    print("\n--- Building Hierarchy ---")
    dummy_subject_id = str(uuid.uuid4())
    nodes = build_hierarchy(toc_entries, dummy_subject_id)
    print(f"Total hierarchy nodes: {len(nodes)}")
    for i, node in enumerate(nodes[:10]):
        print(f"  {i+1}. {node['node_type'].upper()}: {node['title']} (Pages {node['page_start']}-{node['page_end']})")
        print(f"     Path: {node['path']}")
    if len(nodes) > 10:
        print("  ...")

    # Test 3: Extract Chunks
    print("\n--- Extracting Chunks ---")
    chunks = extract_chunks(file_path, nodes)
    print(f"Total text chunks: {len(chunks)}")
    for i, chunk in enumerate(chunks[:3]):
        print(f"  Chunk {i+1} (Pages {chunk['page_start']}-{chunk['page_end']}):")
        print(f"    {chunk['text_content'][:200]}...")
    if len(chunks) > 3:
        print("  ...")

if __name__ == "__main__":
    test_pipeline()
