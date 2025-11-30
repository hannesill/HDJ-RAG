import os
import glob
import time
import json
import sys
import argparse
import pymupdf4llm
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

# --- CONFIGURATION ---
PDF_DIR = "data/pdfs"
PROCESSED_DIR = "data/processed"
CONTEXT_FILE = "data/context.json"
GOLD_FILE = "data/gold_standard.json"
# ---------------------

def get_client():
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("❌ GOOGLE_API_KEY missing in .env")
        sys.exit(1)
    return genai.Client(api_key=api_key)

def convert_pdfs_to_md():
    """Converts PDFs to Markdown using pymupdf4llm."""
    if not os.path.exists(PROCESSED_DIR):
        os.makedirs(PROCESSED_DIR)
    
    pdfs = glob.glob(os.path.join(PDF_DIR, "*.pdf"))
    md_files = []
    
    print(f"📝 Converting {len(pdfs)} PDFs to Markdown...")
    for pdf_path in pdfs:
        try:
            # Convert PDF to Markdown text
            md_text = pymupdf4llm.to_markdown(pdf_path)
            
            # Save as .md file
            base_name = os.path.splitext(os.path.basename(pdf_path))[0]
            md_path = os.path.join(PROCESSED_DIR, f"{base_name}.md")
            
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(md_text)
            
            md_files.append(md_path)
            print(f"   - Converted: {os.path.basename(pdf_path)} -> {os.path.basename(md_path)}")
        except Exception as e:
            print(f"❌ Failed to convert {pdf_path}: {e}")
            
    return md_files

def sync_files():
    """Nukes old store, converts PDFs to MD, uploads MDs."""
    print("🚀 Syncing documents...")
    
    # 1. Convert PDFs
    md_files = convert_pdfs_to_md()
    if not md_files:
        print("❌ No markdown files generated.")
        return

    client = get_client()
    
    # 2. Delete ALL old stores (prevent duplicates)
    print("🗑️  Cleaning up old stores...")
    try:
        all_stores = list(client.file_search_stores.list())
        for store in all_stores:
            if "hdj_batch_latest" in store.display_name:
                try:
                    client.file_search_stores.delete(name=store.name, config={'force': True})
                    print(f"   - Deleted: {store.display_name} ({store.name})")
                except Exception as e:
                    print(f"   - Failed to delete {store.display_name}: {e}")
    except Exception as e:
        print(f"   ⚠️  Could not list/delete old stores: {e}")

    # 3. Create New Store
    print("✨ Creating store...")
    store = client.file_search_stores.create(config={"display_name": "hdj_batch_latest_md"})
    
    # 4. Upload Files (Two-Step: Upload -> Import)
    print(f"📤 Uploading {len(md_files)} files...")
    operations = []
    for md_file in md_files:
        filename = os.path.basename(md_file)
        print(f"   - Uploading: {filename}")
        
        uploaded_file = client.files.upload(
            file=md_file,
            config={'display_name': filename}
        )
        
        print(f"     Importing to store...")
        op = client.file_search_stores.import_file(
            file_search_store_name=store.name,
            file_name=uploaded_file.name
        )
        operations.append(op)

    # 5. Wait for processing
    print(f"⏳ Waiting for {len(operations)} operations...")
    for op in operations:
        while not op.done:
            time.sleep(2)
            op = client.operations.get(op)
        print(f"   - Done: {op.name}")

    # Verify active state
    print("🔎 Verifying files...")
    while True:
        files = list(client.file_search_stores.documents.list(parent=store.name))
        if not files:
             print("   (Checking...)")
             time.sleep(2)
             continue
             
        if all(f.state.name == "STATE_ACTIVE" for f in files):
            print(f"   ✅ {len(files)} files active")
            break
        
        print("   (Processing...)")
        time.sleep(2)

    # 6. Save ID
    with open(".env", "w") as f:
        f.write(f"GOOGLE_API_KEY={os.environ.get('GOOGLE_API_KEY')}\n")
        f.write(f"GOOGLE_STORE_ID={store.name}\n")
    
    print("✅ Done")

def run_analysis(query_mode=False, model_name="gemini-2.5-flash", debug=False):
    """Scans docs for HDJ concepts."""
    store_id = os.environ.get("GOOGLE_STORE_ID")
    if not store_id:
        print("❌ Run 'python rag_tool.py sync' first.")
        return None

    try:
        with open(CONTEXT_FILE) as f:
            context = json.load(f)
            definition = context.get("definition", "")
    except:
        definition = ""

    client = get_client()
    
    # Build document ID to filename mapping from File API
    doc_map = {}
    try:
        files = list(client.files.list())
        for f in files:
            if f.display_name.endswith('.md'):
                file_id = f.name.split('/')[-1]
                doc_map[file_id] = f.display_name
    except:
        pass
    
    prompt = """Find passages about data justice, fairness in data systems, discrimination, surveillance, privacy rights, and data governance.

For each passage:
SOURCE: [filename or ID]
QUOTE: [short key phrase]
CONTEXT: [what it's about]

Find 10-15 passages."""
    
    if query_mode:
        print(f"🔎 Searching with {model_name}...")
    
    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(file_search=types.FileSearch(file_search_store_names=[store_id]))]
            )
        )
        
        if not response.text:
            if query_mode:
                print("⚠️  No response")
            if debug and hasattr(response, 'candidates'):
                print(f"🐛 Finish reason: {response.candidates[0].finish_reason if response.candidates else 'unknown'}")
            return []
        
        if debug:
            print(f"\n🐛 Response:\n{response.text[:800]}\n")
        
        results = []
        lines = response.text.split('\n')
        current = {}
        
        for line in lines:
            line = line.strip()
            if line.startswith('SOURCE:'):
                if current.get('quote'):
                    results.append(current)
                source = line.split('SOURCE:')[1].strip()
                # Map document ID to filename if needed
                for doc_id, filename in doc_map.items():
                    if doc_id in source:
                        source = filename
                        break
                current = {'filename': source}
            elif line.startswith('QUOTE:'):
                current['quote'] = line.split('QUOTE:')[1].strip().strip('"')
            elif line.startswith('CONTEXT:'):
                current['relevance_reason'] = line.split('CONTEXT:')[1].strip()
        
        if current.get('quote'):
            results.append(current)

        if query_mode:
            print(f"\n✅ Found {len(results)} segments\n")
            for i, r in enumerate(results, 1):
                print(f"{i}. [{r.get('filename', '?')}]")
                print(f"   {r.get('quote', '')[:150]}...")
                print("-" * 60)
        
        return results

    except Exception as e:
        print(f"❌ Error: {e}")
        if debug:
            import traceback
            traceback.print_exc()
        return []

def test_basic_search():
    """Test if file search works with simple queries."""
    print("🔬 Testing file search...\n")
    
    store_id = os.environ.get("GOOGLE_STORE_ID")
    if not store_id:
        print("❌ No store ID. Run 'sync' first.")
        return
    
    client = get_client()
    test_queries = ["data justice", "Aadhaar", "discrimination", "privacy"]
    
    for query in test_queries:
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=f'Find "{query}" in the documents.',
                config=types.GenerateContentConfig(
                    tools=[types.Tool(file_search=types.FileSearch(file_search_store_names=[store_id]))]
                )
            )
            
            status = "✅" if response.text and len(response.text) > 50 else "❌"
            print(f"{status} {query}: {len(response.text) if response.text else 0} chars")
                
        except Exception as e:
            print(f"❌ {query}: {e}")
    
    print("\n" + "="*50)
    print("✅ = File search is working")
    print("❌ = Check store or API issues")
    print("="*50)

def test_gold_standard(model_name="gemini-2.5-flash", debug=False):
    """Checks if gold standard quotes are found."""
    print(f"🧪 Testing with {model_name}...")
    
    # Load Gold Standard
    try:
        with open(GOLD_FILE) as f:
            gold_data = json.load(f)
    except:
        print("⚠️  data/gold_standard.json is missing or empty.")
        return

    # Run Analysis
    found_segments = run_analysis(query_mode=False, model_name=model_name, debug=debug)
    if not found_segments:
        print("❌ No results returned.")
        print("\nTry: python rag_tool.py debug")
        return

    found_texts = " ".join([s.get('quote', '') for s in found_segments]).lower()

    print(f"\n📊 RESULTS ({len(gold_data)} gold examples):")
    
    if len(found_segments) > 0:
        print(f"(Found {len(found_segments)} segments from: {', '.join(set([s.get('filename', 'Unknown') for s in found_segments]))})")

    score = 0
    for item in gold_data:
        target = item['text'].lower()
        # Check if a significant chunk of the gold text is in the results
        # We use a sliding window or just check if the first 50 chars match
        # Better: check if a good portion of the text is present
        target_snippet = target[:100] if len(target) > 100 else target
        
        is_found = target_snippet in found_texts
        
        # Also check individual segments for better matching
        if not is_found:
            for segment in found_segments:
                if target_snippet in segment.get('quote', '').lower():
                    is_found = True
                    break
        
        status = "✅ FOUND" if is_found else "❌ MISSED"
        if is_found: score += 1
        
        print(f"{status}: \"{item['text'][:60]}...\"")

    print(f"\n🎯 Score: {score}/{len(gold_data)}")

def list_store_files():
    """Lists files currently in the Google Cloud store."""
    store_id = os.environ.get("GOOGLE_STORE_ID")
    if not store_id:
        print("❌ No store ID found in .env. Run 'sync' first.")
        return

    client = get_client()
    try:
        print(f"📂 Checking store: {store_id}...")
        files = list(client.file_search_stores.documents.list(parent=store_id))
        
        if not files:
            print("⚠️  Store is empty.")
        else:
            print(f"✅ Found {len(files)} files:")
            for f in files:
                print(f"   - {f.display_name} (State: {f.state.name})")
                
    except Exception as e:
        print(f"❌ Error listing files: {e}")

def direct_query(query_text, model_name="gemini-2.5-flash"):
    """Run a direct query against the file search store."""
    store_id = os.environ.get("GOOGLE_STORE_ID")
    if not store_id:
        print("❌ No store ID found. Run 'sync' first.")
        return
    
    client = get_client()
    
    print(f"🔍 Running direct query: '{query_text}'")
    print(f"   Model: {model_name}")
    print(f"   Store: {store_id}\n")
    
    try:
        prompt = f"""Search the uploaded documents for information about: {query_text}

Return any relevant passages you find. Be specific and quote exact text from the documents.
Include the source filename for each quote."""

        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(file_search=types.FileSearch(file_search_store_names=[store_id]))]
            )
        )
        
        print("📄 RESPONSE:")
        print("=" * 60)
        if response.text:
            print(response.text)
            print("=" * 60)
            print(f"\n✅ Response length: {len(response.text)} chars")
        else:
            print("(No response - likely blocked by RECITATION filter)")
            print("=" * 60)
            if hasattr(response, 'candidates') and response.candidates:
                print(f"Finish reason: {response.candidates[0].finish_reason}")
        
    except Exception as e:
        print(f"❌ Query failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HDJ RAG Tool - Health Data Justice Document Analysis")
    parser.add_argument("command", choices=["sync", "analyze", "test", "list", "debug", "query"], 
                       help="Command to run: sync (upload docs), analyze (search docs), test (gold standard), list (show files), debug (test file search), query (direct query)")
    parser.add_argument("--model", default="gemini-2.5-flash", help="Model to use (default: gemini-2.5-flash)")
    parser.add_argument("--debug", action="store_true", help="Enable debug output")
    parser.add_argument("--query", type=str, help="Query text for 'query' command")
    args = parser.parse_args()

    if args.command == "sync":
        sync_files()
    elif args.command == "analyze":
        run_analysis(query_mode=True, model_name=args.model, debug=args.debug)
    elif args.command == "test":
        test_gold_standard(model_name=args.model, debug=args.debug)
    elif args.command == "list":
        list_store_files()
    elif args.command == "debug":
        test_basic_search()
    elif args.command == "query":
        if not args.query:
            print("❌ Please provide a query with --query 'your query text'")
            sys.exit(1)
        direct_query(args.query, model_name=args.model)

