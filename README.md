# HDJ RAG - Health Data Justice Document Analysis

A lean RAG tool using Google Gemini API (Free/Student Tier) to analyze policy documents for Health Data Justice concepts.

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Set up API key:**
   Create a `.env` file with:
   ```
   GOOGLE_API_KEY=your_api_key_here
   ```

3. **Add your PDFs** to `data/pdfs/`

4. **Configure definitions** in `data/context.json`

5. **Add test cases** in `data/gold_standard.json` (optional)

## Commands

### 1. Sync Documents (Upload/Resync)
```bash
python rag_tool.py sync
```
- Converts PDFs to Markdown for better text extraction
- Deletes old stores to prevent duplicates
- Uploads files to Google File Search API
- Saves store ID to `.env`

**Run this:** When you add/change PDFs or after initial setup

### 2. Analyze Documents
```bash
python rag_tool.py analyze [--model MODEL] [--debug]
```
- Searches documents for Health Data Justice concepts
- Uses multi-query strategy for better retrieval
- Extracts relevant quotes with sources

**Options:**
- `--model`: Choose model (default: `gemini-2.5-flash`)
  - Available: `gemini-2.5-flash`, `gemini-2.5-pro`, `gemini-2.0-flash`
- `--debug`: Show detailed debug output

**Example:**
```bash
python rag_tool.py analyze --model gemini-1.5-pro --debug
```

### 3. Test Gold Standard
```bash
python rag_tool.py test [--model MODEL] [--debug]
```
- Runs analysis and checks against known examples
- Reports precision/recall metrics
- Shows which gold standard quotes were found

### 4. List Store Files
```bash
python rag_tool.py list
```
- Shows files currently in the Google Cloud store
- Displays file states (ACTIVE, PROCESSING, etc.)
- Useful for verifying successful upload

### 5. Debug File Search
```bash
python rag_tool.py debug
```
- Tests basic file search functionality
- Tries simple keyword queries
- Helps diagnose retrieval issues
- **Run this first if analyze returns 0 results**

### 6. Direct Query
```bash
python rag_tool.py query --query "your search terms"
```
- Run a direct search query against documents
- Bypass the structured analysis flow
- Useful for testing specific searches

**Example:**
```bash
python rag_tool.py query --query "data justice and discrimination"
python rag_tool.py query --query "Aadhaar biometric system"
```

## Troubleshooting

### RECITATION Filter (Empty Results)

**Symptom**: `analyze` or `test` returns 0 results, or works sometimes but not others

**Cause**: Google's RECITATION filter blocks responses when the model would return long verbatim quotes. This is nondeterministic - it may work one run and fail the next.

**Solutions**:
1. **Retry**: Simply run the command again - it may work next time
2. **Check if file search works**:
   ```bash
   python rag_tool.py debug
   ```
3. **Use direct query for specific searches**:
   ```bash
   python rag_tool.py query --query "Aadhaar system"
   ```
4. **Alternative models**: Try `gemini-2.0-flash` instead (may have different filter behavior)

**Note**: This is a limitation of Gemini's safety systems. The tool is working correctly - when the filter doesn't trigger, it returns 10-15 exact quotes from the documents.

### File Store Issues

1. **Check store status:**
   ```bash
   python rag_tool.py list
   ```
   All files should show `STATE_ACTIVE`

2. **Resync if corrupted:**
   ```bash
   python rag_tool.py sync
   ```
   This deletes old stores and uploads fresh

### Rate Limits

If you hit 429 errors:
- Wait a few minutes and retry
- Free tier has daily request limits
- Consider using `gemini-2.5-flash` (lower rate limit impact)

## Architecture

```
PDFs → Markdown → Google File API → File Search Store → Gemini with File Search Tool
```

**Key Features:**
- Local PDF→MD conversion (pymupdf4llm) for better text extraction
- Automatic store cleanup to prevent duplicates
- Simple prompting for direct quote extraction
- Document ID to filename mapping for proper attribution

## File Structure

```
data/
  ├── pdfs/              # Source PDF documents
  ├── processed/         # Generated Markdown files
  ├── context.json       # Health Data Justice definition
  └── gold_standard.json # Test cases for validation
```
