# app.py
import os
import re
import json
import redis
from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError
import pandas as pd
from sqlalchemy_utils import generic_repr

# --- SETUP ---
load_dotenv()
app = Flask(__name__)

# Configure Redis with error handling
try:
    redis_client = redis.Redis(
        host=os.getenv('REDIS_HOST', 'localhost'),
        port=int(os.getenv('REDIS_PORT', 6379)),
        db=0,
        decode_responses=True,
        socket_timeout=5  # 5 second timeout
    )
    # Test Redis connection
    redis_client.ping()
except (redis.ConnectionError, redis.TimeoutError) as e:
    print(f"Warning: Redis connection failed: {e}")
    redis_client = None

# Configure Azure AI Client
client = ChatCompletionsClient(
    endpoint=os.getenv("AZURE_AI_ENDPOINT", "https://models.github.ai/inference"),
    credential=AzureKeyCredential(os.getenv("AI_TOKEN")),
)
MODEL = "openai/gpt-4o" # Or your preferred model

# Configure Database with connection pooling
db_url = os.getenv("DATABASE_URL", "mysql+mysqlconnector://root:password123@localhost:3306/insight_bot")
engine = create_engine(
    db_url,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=1800
)

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

def get_cache_key(user_question):
    """Generate a cache key for the user question."""
    return f"query:{user_question.strip().lower()}"

def get_cached_response(cache_key):
    """Get cached response if it exists."""
    if not redis_client:
        return None
    try:
        cached_data = redis_client.get(cache_key)
        if cached_data:
            return json.loads(cached_data)
    except Exception as e:
        print(f"Cache error: {e}")
    return None

def cache_response(cache_key, response_data, ttl=3600):
    """Cache the response with a TTL of 1 hour."""
    if not redis_client:
        return
    try:
        redis_client.setex(
            cache_key,
            ttl,
            json.dumps(response_data)
        )
    except Exception as e:
        print(f"Cache error: {e}")

def pre_filter_question(user_question):
    """Fast, rule-based filter for obvious non-queries."""
    for pattern, status, message in CLASSIFICATION_RULES:
        if pattern.search(user_question):
            return {"status": status, "message": message}
    return None

def is_query_relevant(user_question):
    """Uses a cheap LLM call to check if the query is relevant to the database schema."""
    cache_key = f"relevance:{user_question.strip().lower()}"
    cached_result = get_cached_response(cache_key)
    if cached_result is not None:
        return cached_result

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
            max_tokens=5
        )
        answer = response.choices[0].message.content.strip().upper()
        result = "YES" in answer
        cache_response(cache_key, result)
        return result
    except Exception as e:
        print(f"Error in is_query_relevant: {e}")
        return False

def clean_and_validate_sql(sql_string):
    """Enhanced SQL validation with multiple safety checks."""
    if "```sql" in sql_string:
        match = re.search(r"```sql\n(.*?)\n```", sql_string, re.DOTALL)
        if match:
            sql_string = match.group(1)
    
    sql_string = sql_string.strip()
    
    # Basic security checks
    if ';' in sql_string.strip(';'):
        raise ValueError("Multiple SQL statements are not allowed for security reasons.")
    if not sql_string.lower().startswith('select'):
        raise ValueError("Only SELECT queries are allowed.")
    
    # Check for dangerous operations
    dangerous_keywords = ['drop', 'delete', 'update', 'insert', 'truncate', 'alter', 'create', 'replace']
    if any(keyword in sql_string.lower() for keyword in dangerous_keywords):
        raise ValueError("Query contains forbidden operations.")
    
    # Ensure LIMIT clause is present
    if 'limit' not in sql_string.lower():
        sql_string += ' LIMIT 1000'  # Add a reasonable default limit
    
    # Remove any trailing semicolon
    sql_string = sql_string.strip(';')
    
    # Validate query with EXPLAIN in a separate connection
    try:
        validation_engine = create_engine(
            db_url,
            pool_pre_ping=True,
            pool_recycle=300
        )
        with validation_engine.connect() as connection:
            explain_query = f"EXPLAIN {sql_string}"
            connection.execute(text(explain_query))
    except Exception as e:
        raise ValueError(f"Query validation failed: {str(e)}")
    finally:
        validation_engine.dispose()
    
    return sql_string

def generate_sql(user_question):
    cache_key = f"sql:{user_question.strip().lower()}"
    cached_sql = get_cached_response(cache_key)
    if cached_sql:
        return cached_sql

    prompt = f"Given the MySQL schema:\n{DB_SCHEMA}\n\nGenerate a single, valid MySQL SELECT query for the question: \"{user_question}\"\n\nOnly output the SQL query itself, with no additional text or formatting."
    try:
        response = client.complete(
            messages=[SystemMessage("You are an expert SQL query generator."), 
                     UserMessage(prompt)], 
            model=MODEL, 
            temperature=0.0
        )
        sql = response.choices[0].message.content
        cache_response(cache_key, sql)
        return sql
    except Exception as e:
        print(f"Error in generate_sql: {e}")
        return None

def diagnose_sql_error(user_question, sql_query, error_message):
    cache_key = f"error:{user_question.strip().lower()}:{sql_query}"
    cached_diagnosis = get_cached_response(cache_key)
    if cached_diagnosis:
        return cached_diagnosis

    prompt = f"""A user asked: "{user_question}"\nI generated this SQL: "{sql_query}"\nThe database returned this error: "{error_message}"\n\nBased on the schema below, explain the problem to the user in a simple, friendly way and suggest a valid alternative question.\n\nSchema:\n{DB_SCHEMA}"""
    try:
        response = client.complete(
            messages=[SystemMessage("You are a helpful database assistant."), 
                     UserMessage(prompt)], 
            model=MODEL, 
            temperature=0.7
        )
        diagnosis = response.choices[0].message.content
        cache_response(cache_key, diagnosis)
        return diagnosis
    except Exception as e:
        print(f"Error in diagnose_sql_error: {e}")
        return "I couldn't run that query. It might be asking for information that isn't in the database."

def execute_sql(sql_query):
    """Execute SQL query with proper connection handling."""
    # Create a new connection for execution
    execution_engine = create_engine(
        db_url,
        pool_pre_ping=True,
        pool_recycle=300
    )
    try:
        with execution_engine.connect() as connection:
            # Execute the query in a transaction
            result = pd.read_sql_query(text(sql_query), connection)
            return result.to_dict(orient='records')
    except Exception as e:
        print(f"Error executing SQL: {e}")
        raise
    finally:
        # Ensure the execution engine is disposed
        execution_engine.dispose()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/query', methods=['POST'])
def handle_query():
    user_question = request.json.get('question', '').strip()
    if not user_question:
        return jsonify({"sql_query": "N/A", "results": {"error": "Please enter a question."}})

    # Check cache first
    cache_key = get_cache_key(user_question)
    cached_response = get_cached_response(cache_key)
    if cached_response:
        return jsonify(cached_response)

    # Step 1: Fast, rule-based pre-filter
    classification = pre_filter_question(user_question)
    if classification:
        response = {"sql_query": "N/A (Query Rejected)", "results": {"error": classification['message']}}
        cache_response(cache_key, response)
        return jsonify(response)

    # Step 2: LLM-based Relevancy Firewall
    if not is_query_relevant(user_question):
        response = {
            "sql_query": "N/A (Query Rejected)",
            "results": {"error": "I'm sorry, that question does not seem to be related to the available sales, product, or customer data."}
        }
        cache_response(cache_key, response)
        return jsonify(response)

    # Generate and validate SQL
    raw_sql = generate_sql(user_question)
    if not raw_sql:
        response = {"sql_query": "N/A", "results": {"error": "The AI model could not generate a valid query. Please try rephrasing your question."}}
        cache_response(cache_key, response)
        return jsonify(response), 500

    try:
        cleaned_sql = clean_and_validate_sql(raw_sql)
    except ValueError as e:
        response = {"sql_query": raw_sql, "results": {"error": str(e)}}
        cache_response(cache_key, response)
        return jsonify(response)

    try:
        results = execute_sql(cleaned_sql)
        response = {"sql_query": cleaned_sql, "results": results}
        cache_response(cache_key, response)
        return jsonify(response)
    except ProgrammingError as e:
        error_explanation = diagnose_sql_error(user_question, cleaned_sql, str(e))
        response = {"sql_query": cleaned_sql, "results": {"error": error_explanation}}
        cache_response(cache_key, response)
        return jsonify(response)
    except Exception as e:
        print(f"Generic execution error: {e}")
        response = {"sql_query": cleaned_sql, "results": {"error": "An unexpected error occurred. Please check the logs."}}
        cache_response(cache_key, response)
        return jsonify(response), 500

if __name__ == '__main__':
    app.run(debug=True)
