# Insight Bot

Insight Bot is a Python-based web application that lets you ask questions about your sales, products, and customers in plain English. It uses AI to generate safe SQL queries, runs them, and returns results—sometimes with chart suggestions!  
It’s designed for business users who want instant insights from their data, without writing SQL.

## Features

- 🧠 **AI-powered natural language to SQL conversion**
- 🔒 **Read-only, secure SQL execution** (SQL injection protection, only SELECTs allowed)
- ♻️ **Self-healing:** auto-corrects invalid SQL queries
- 📊 **Chart suggestions** for visualizing results
- ⚡ **Fast responses** with Redis caching
- 🐳 **Easy deployment** with Docker

## Setup

1. **Clone the repository**
2. **Create a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
4. **Set environment variables** (see below)

## Required Environment Variables

Set these in a `.env` file or your environment:

- `DATABASE_URL` — SQLAlchemy DB URL (e.g., `mysql+mysqlconnector://user:pass@host:port/db`)
- `REDIS_HOST` and `REDIS_PORT` — Redis connection info (default: `localhost:6379`)
- `AZURE_AI_ENDPOINT` — Azure OpenAI endpoint
- `AI_TOKEN` — Azure OpenAI API key

## Running the Application

### Using Docker
```bash
docker build -t insight-bot .
docker run -p 5000:5000 --env-file .env insight-bot
```

### Without Docker
```bash
python app.py
```

## Usage

Open your browser to [http://localhost:5000](http://localhost:5000) and ask questions like:
- “Show me the top 5 products by sales.”
- “How many customers signed up last month?”

The bot will generate a SQL query, run it, and display the results (with a chart if possible).

## API

### POST `/query`

**Request:**
```json
{
  "question": "List the top 5 products by sales",
  "conversation_id": "optional-uuid"
}
```
**Response:**
```json
{
  "sql_query": "...",
  "results": [...],
  "chart_suggestion": {...},
  "conversation_id": "..."
}
```

## Project Structure

- `app.py` — Main application file
- `templates/` — HTML templates
- `Dockerfile` — Docker configuration
- `requirements.txt` — Project dependencies
- `schema.sql` — Example database schema

## Security

- Only SELECT queries are allowed; all others are blocked with a cheeky message.
- SQL injection is prevented by strict validation and cleaning of all AI-generated SQL.

## License

MIT (or your license here)

---

*Feel free to add a screenshot or a project logo above for extra polish!*