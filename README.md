# AI Benchmark Smasher

An AI-powered CTF (Capture The Flag) challenge solver using Gemini 2.5 and Playwright for intelligent web penetration testing.

## Architecture

- **Antigravity (AI Agent)**: The "human" CTF player
- **Gemini 2.5 Flash/Pro**: AI brain for analysis and strategy
- **FastAPI Backend**: Orchestrates analysis and tool execution  
- **PostgreSQL + pgvector**: Persistent storage and semantic search
- **Playwright**: Browser automation with persistent sessions

## Setup

1. **Prerequisites**
   - Docker and Docker Compose
   - GCP account with Vertex AI enabled
   - GCP service account key JSON file

2. **Configuration**
   ```bash
   cp .env.example .env
   # Edit .env with your GCP_PROJECT_ID
   # Place your GCP service account key at ./gcp-key.json
   ```

3. **Start Services**
   ```bash
   docker-compose up --build
   ```

4. **Run Database Migrations**
   ```bash
   docker-compose exec api alembic upgrade head
   ```

## API Endpoints

- `POST /sessions` - Create new CTF solving session
- `POST /chat` - Send messages to Gemini (with optional session_id)
- `GET /chat/history` - Get conversation history
- `GET /findings/{session_id}` - Get analysis findings
- `GET /flags/{session_id}` - Get discovered flags
- `GET /health` - Health check

## Usage

Antigravity will interact with the API to solve CTF challenges by:
1. Sending initial prompt with target URL
2. Gemini analyzes and asks clarifying questions
3. Antigravity responds to guide the analysis
4. System uses browser tool to interact with the target
5. Flags are automatically discovered and extracted

## Development

The system is designed to be extensible with new tools. Add tools in `api/tools/` and they'll be automatically registered for Gemini to use.
