# app.py
import os
import re
from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError
import pandas as pd

# --- SETUP ---
load_dotenv()
app = Flask(__name__)

# Configure Azure AI Client
client = ChatCompletionsClient(
    endpoint=os.getenv("AZURE_AI_ENDPOINT", "https://models.github.ai/inference"),
    credential=AzureKeyCredential(os.getenv("GITHUB_TOKEN")),
)
MODEL = "openai/gpt-4o" # Or your preferred model

# Configure Database
db_url = os.getenv("DATABASE_URL", "mysql+mysqlconnector://root:password123@localhost:3306/insight_bot")
engine = create_engine(db_url)

# --- DATABASE SCHEMA & HELP TEXT ---
DB_SCHEMA = """
Table: customers, Columns: id (INT), name (VARCHAR), signup_date (DATE)
Table: products, Columns: id (INT), name (VARCHAR), category (VARCHAR), price (DECIMAL)
Table: sales, Columns: id (INT), customer_id (INT), product_id (INT), sale_date (DATE), quantity (INT)
"""

# --- ROBUST CLASSIFICATION RULES using REGEX ---
CLASSIFICATION_RULES = [
    (re.compile(r"^\b(hi|hello|hey|howdy|good morning)\b.*", re.IGNORECASE), "greeting", "Hello! I'm InsightBot. Please ask a question about our sales data."),
    (re.compile(r"^\b(delete|drop|update|insert|truncate|alter|ddl|dml)\b", re.IGNORECASE), "invalid_operation", "I can only perform read-only (SELECT) queries."),
    (re.compile(r".*\b(joke|weather|cook|time|fun fact|beyonce)\b.*", re.IGNORECASE), "off_topic", "I can only answer questions related to our sales, products, or customers."),
    (re.compile(r"^\s*$", re.IGNORECASE), "clarification", "Your query is empty. Please ask a question."),
    (re.compile(r"^\b(show me|what about|tell me something|list|can you)\b\s*$", re.IGNORECASE), "clarification", "That's a bit vague. Can you be more specific? e.g., 'List the top 5 products by sales'.")
]

def pre_filter_question(user_question):
    """Fast, rule-based filter for obvious non-queries."""
    for pattern, status, message in CLASSIFICATION_RULES:
        if pattern.search(user_question):
            return {"status": status, "message": message}
    return None

# --- NEW: LLM-based Relevancy Firewall ---
def is_query_relevant(user_question):
    """Uses a cheap LLM call to check if the query is relevant to the database schema."""
    prompt = f"""
    The user asked the following question: "{user_question}"
    
    My database contains information ONLY about sales, products, and customers.
    
    Is the user's question answerable using ONLY this data? Answer with a single word: YES or NO.
    """
    try:
        response = client.complete(
            messages=[SystemMessage("You are a relevancy checker."), UserMessage(prompt)],
            model=MODEL,
            temperature=0.0,
            max_tokens=5 # Keep it fast and cheap
        )
        answer = response.choices[0].message.content.strip().upper()
        return "YES" in answer
    except Exception as e:
        print(f"Error in is_query_relevant: {e}")
        return False # Fail safe: if unsure, assume it's not relevant

# --- HELPER & CORE AI FUNCTIONS ---

def clean_and_validate_sql(sql_string):
    """Cleans the SQL string and performs security validation."""
    if "```sql" in sql_string:
        match = re.search(r"```sql\n(.*?)\n```", sql_string, re.DOTALL)
        if match:
            sql_string = match.group(1)
    
    sql_string = sql_string.strip()
    if ';' in sql_string.strip(';'):
        raise ValueError("Multiple SQL statements are not allowed for security reasons.")
    if not sql_string.lower().startswith('select'):
        raise ValueError("Only SELECT queries are allowed.")
        
    return sql_string.strip(';')

def generate_sql(user_question):
    prompt = f"Given the MySQL schema:\n{DB_SCHEMA}\n\nGenerate a single, valid MySQL SELECT query for the question: \"{user_question}\"\n\nOnly output the SQL query itself, with no additional text or formatting."
    try:
        response = client.complete(messages=[SystemMessage("You are an expert SQL query generator."), UserMessage(prompt)], model=MODEL, temperature=0.0)
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error in generate_sql: {e}")
        return None

def diagnose_sql_error(user_question, sql_query, error_message):
    prompt = f"""A user asked: "{user_question}"\nI generated this SQL: "{sql_query}"\nThe database returned this error: "{error_message}"\n\nBased on the schema below, explain the problem to the user in a simple, friendly way and suggest a valid alternative question.\n\nSchema:\n{DB_SCHEMA}"""
    try:
        response = client.complete(messages=[SystemMessage("You are a helpful database assistant."), UserMessage(prompt)], model=MODEL, temperature=0.7)
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error in diagnose_sql_error: {e}")
        return "I couldn't run that query. It might be asking for information that isn't in the database."

def execute_sql(sql_query):
    with engine.connect() as connection:
        return pd.read_sql_query(text(sql_query), connection).to_dict(orient='records')

# --- FLASK ROUTE ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/query', methods=['POST'])
def handle_query():
    user_question = request.json.get('question', '').strip()
    if not user_question:
        return jsonify({"sql_query": "N/A", "results": {"error": "Please enter a question."}})

    # --- THE NEW VALIDATION PIPELINE ---

    # Step 1: Fast, rule-based pre-filter
    classification = pre_filter_question(user_question)
    if classification:
        return jsonify({"sql_query": "N/A (Query Rejected)", "results": {"error": classification['message']}})

    # Step 2: LLM-based Relevancy Firewall
    if not is_query_relevant(user_question):
        return jsonify({
            "sql_query": "N/A (Query Rejected)",
            "results": {"error": "I'm sorry, that question does not seem to be related to the available sales, product, or customer data."}
        })

    # --- If checks pass, proceed to SQL generation ---

    raw_sql = generate_sql(user_question)
    if not raw_sql:
        return jsonify({"sql_query": "N/A", "results": {"error": "The AI model could not generate a valid query. Please try rephrasing your question."}}), 500

    try:
        cleaned_sql = clean_and_validate_sql(raw_sql)
    except ValueError as e:
        return jsonify({"sql_query": raw_sql, "results": {"error": str(e)}})

    try:
        results = execute_sql(cleaned_sql)
        return jsonify({"sql_query": cleaned_sql, "results": results})
    except ProgrammingError as e:
        error_explanation = diagnose_sql_error(user_question, cleaned_sql, str(e))
        return jsonify({"sql_query": cleaned_sql, "results": {"error": error_explanation}})
    except Exception as e:
        print(f"Generic execution error: {e}")
        return jsonify({"sql_query": cleaned_sql, "results": {"error": "An unexpected error occurred. Please check the logs."}}), 500

if __name__ == '__main__':
    app.run(debug=True)