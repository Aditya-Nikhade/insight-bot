# app.py
import os
import re
import json
import uuid
import redis
from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError, OperationalError
import pandas as pd
from decimal import Decimal

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
    redis_client.ping()
except (redis.ConnectionError, redis.TimeoutError) as e:
    print(f"Warning: Redis connection failed: {e}")
    redis_client = None

# Configure Azure AI Client
client = ChatCompletionsClient(
    endpoint=os.getenv("AZURE_AI_ENDPOINT"),
    credential=AzureKeyCredential(os.getenv("AI_TOKEN")),
)
MODEL = "openai/gpt-4.1"

# Configure Database (created once)
db_url = os.getenv("DATABASE_URL", "mysql+mysqlconnector://root:password123@localhost:3306/insight_bot")
engine = create_engine(
    db_url,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=1800,
    pool_pre_ping=True
)

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
    return f"query:{user_question.strip().lower()}"

def get_cached_response(cache_key):
    if not redis_client: return None
    try:
        cached_data = redis_client.get(cache_key)
        if cached_data: return json.loads(cached_data)
    except Exception as e:
        print(f"Cache error: {e}")
    return None

def cache_response(cache_key, response_data, ttl=3600):
    if not redis_client: return
    try:
        redis_client.setex(cache_key, ttl, json.dumps(response_data, default=str))
    except Exception as e:
        print(f"Cache error: {e}")

def pre_filter_question(user_question):
    for pattern, status, message in CLASSIFICATION_RULES:
        if pattern.search(user_question):
            return {"status": status, "message": message}
    return None

def is_query_relevant(user_question):
    cache_key = f"relevance:{user_question.strip().lower()}"
    cached_result = get_cached_response(cache_key)
    if cached_result is not None: return cached_result
    prompt = f"""The user asked: "{user_question}"\nMy database is ONLY about sales, products, and customers.\nIs the question answerable using ONLY this data? Answer with a single word: YES or NO."""
    try:
        response = client.complete(
            messages=[SystemMessage("You are a relevancy checker."), UserMessage(prompt)],
            model=MODEL, temperature=0.0, max_tokens=5
        )
        answer = response.choices[0].message.content.strip().upper()
        result = "YES" in answer
        cache_response(cache_key, result)
        return result
    except Exception as e:
        print(f"Error in is_query_relevant: {e}")
        return False

def clean_and_validate_sql(sql_string):
    """Cleans, secures, and validates the SQL query with the correct order of operations."""
    if "```" in sql_string:
        match = re.search(r"```(?:sql)?\s*\n?(.*?)\n?```", sql_string, re.DOTALL)
        if match:
            sql_string = match.group(1)
    sql_string = sql_string.strip()

    if ';' in sql_string.rstrip(';'):
        raise ValueError("Multiple SQL statements are not allowed for security reasons.")
    
    sql_string = sql_string.rstrip(';')

    if not sql_string.lower().startswith('select'):
        raise ValueError("Only SELECT queries are allowed.")
    dangerous_keywords = ['drop', 'delete', 'update', 'insert', 'truncate', 'alter', 'create', 'replace']
    if any(keyword in sql_string.lower() for keyword in dangerous_keywords):
        raise ValueError("Query contains forbidden operations.")

    sql_lower = sql_string.lower()
    is_agg_without_group = any(f in sql_lower for f in ['sum(', 'count(', 'avg(', 'min(', 'max(']) and 'group by' not in sql_lower
    if 'limit' not in sql_lower and not is_agg_without_group:
        sql_string += ' LIMIT 1000'

    try:
        with engine.connect() as connection:
            with connection.begin():
                connection.execute(text(f"EXPLAIN {sql_string}"))
    except (ProgrammingError, OperationalError) as e:
        raise ValueError(f"The generated SQL is invalid. Error: {e}")

    return sql_string

def generate_sql(user_question, conversation_history=None):
    cache_key = f"sql:{user_question.strip().lower()}"
    if not conversation_history:
        cached_sql = get_cached_response(cache_key)
        if cached_sql: return cached_sql

    system_prompt = "You are an expert SQL query generator."
    
    context_str = ""
    if conversation_history:
        context_str += "This is our conversation history (previous questions and the SQL I generated for them):\n"
        for entry in conversation_history:
            context_str += f"- User: \"{entry['user_question']}\"\n  AI_SQL: \"{entry['sql_query']}\"\n"
        context_str += "\nBased on this context, please answer the user's latest question. If their question is a follow-up, use the context to form the correct query. Otherwise, treat it as a new question.\n"

    prompt = f"{context_str}Given the MySQL schema:\n{DB_SCHEMA}\n\nGenerate a single, valid MySQL SELECT query for the question: \"{user_question}\"\n\nOnly output the SQL query itself, with no additional text or formatting."

    try:
        response = client.complete(
            messages=[SystemMessage(system_prompt), UserMessage(prompt)],
            model=MODEL, temperature=0.0
        )
        sql = response.choices[0].message.content
        if not conversation_history:
            cache_response(cache_key, sql)
        return sql
    except Exception as e:
        print(f"Error in generate_sql: {e}")
        return None

def generate_corrected_sql(user_question, original_sql, error_message):
    """Asks the AI to correct a faulty SQL query."""
    prompt = f"""A user asked: "{user_question}"
I generated this SQL query:
"{original_sql}"

However, it failed with the following MySQL error:
"{error_message}"

Based on the schema below and the error, please generate a corrected, valid MySQL SELECT query. Only output the corrected SQL query itself.

Schema:
{DB_SCHEMA}
"""
    try:
        response = client.complete(
            messages=[SystemMessage("You are a SQL query debugging expert."), UserMessage(prompt)],
            model=MODEL, temperature=0.2
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error in generate_corrected_sql: {e}")
        return None

def diagnose_sql_error(user_question, sql_query, error_message):
    # This function is now mainly a final fallback
    prompt = f"""A user asked: "{user_question}"\nI generated this SQL: "{sql_query}"\nThe database returned this error: "{error_message}"\n\nBased on the schema below, explain the problem to the user in a simple, friendly way and suggest a valid alternative question.\n\nSchema:\n{DB_SCHEMA}"""
    try:
        response = client.complete(
            messages=[SystemMessage("You are a helpful database assistant."), UserMessage(prompt)],
            model=MODEL, temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error in diagnose_sql_error: {e}")
        return "I couldn't run that query. It might be asking for information that isn't in the database."

def execute_sql(sql_query):
    """Execute SQL query within a transaction for safety."""
    try:
        with engine.connect() as connection:
            with connection.begin():
                result = pd.read_sql_query(text(sql_query), connection)
                return result.to_dict(orient='records')
    except Exception as e:
        print(f"Error executing SQL: {e}")
        raise

def analyze_and_suggest_chart(results):
    if not results or not isinstance(results, list) or len(results) == 0:
        return None
    headers = list(results[0].keys())
    if len(headers) != 2:
        return None
    label_column, data_column = None, None
    for header in headers:
        if isinstance(results[0][header], (int, float, Decimal)):
            data_column = header
        else:
            label_column = header
    if label_column and data_column:
        chart_type = 'bar'
        try:
            if pd.to_datetime(results[0][label_column], errors='coerce') is not pd.NaT:
                 chart_type = 'line'
        except Exception:
            pass
        return {"type": chart_type, "labels_column": label_column, "data_column": data_column}
    return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/query', methods=['POST'])
def handle_query():
    data = request.json
    user_question = data.get('question', '').strip()
    conversation_id = data.get('conversation_id')

    if not user_question:
        return jsonify({"sql_query": "N/A", "results": {"error": "Please enter a question."}})

    if not conversation_id:
        conversation_id = str(uuid.uuid4())
    
    conversation_history = []
    if redis_client:
        history_key = f"history:{conversation_id}"
        raw_history = redis_client.lrange(history_key, 0, 4)
        conversation_history = [json.loads(item) for item in reversed(raw_history)]

    classification = pre_filter_question(user_question)
    if classification:
        return jsonify({"sql_query": "N/A (Query Rejected)", "results": {"error": classification['message']}, "conversation_id": conversation_id})

    if not is_query_relevant(user_question):
        response = {"sql_query": "N/A (Query Rejected)", "results": {"error": "I'm sorry, that question does not seem to be related to the available sales, product, or customer data."}, "conversation_id": conversation_id}
        return jsonify(response)

    raw_sql = generate_sql(user_question, conversation_history)
    if not raw_sql:
        return jsonify({"sql_query": "N/A", "results": {"error": "The AI model could not generate a query."}, "conversation_id": conversation_id}), 500

    sql_to_execute = None
    try:
        cleaned_sql = clean_and_validate_sql(raw_sql)
        sql_to_execute = cleaned_sql
        results = execute_sql(cleaned_sql)
        
        if redis_client:
            new_history_item = json.dumps({"user_question": user_question, "sql_query": cleaned_sql})
            redis_client.lpush(history_key, new_history_item)
            redis_client.expire(history_key, 3600)

        chart_suggestion = analyze_and_suggest_chart(results)
        response = {"sql_query": cleaned_sql, "results": results, "chart_suggestion": chart_suggestion, "conversation_id": conversation_id}
        return jsonify(response)

    except ProgrammingError as e:
        print(f"Initial SQL failed. Attempting self-healing. Error: {e}")
        corrected_sql_raw = generate_corrected_sql(user_question, sql_to_execute, str(e))
        
        if corrected_sql_raw:
            try:
                cleaned_corrected_sql = clean_and_validate_sql(corrected_sql_raw)
                results = execute_sql(cleaned_corrected_sql)
                
                print("Self-healing successful!")
                if redis_client:
                    new_history_item = json.dumps({"user_question": user_question, "sql_query": cleaned_corrected_sql})
                    redis_client.lpush(history_key, new_history_item)
                    redis_client.expire(history_key, 3600)

                chart_suggestion = analyze_and_suggest_chart(results)
                response = {"sql_query": cleaned_corrected_sql, "results": results, "chart_suggestion": chart_suggestion, "conversation_id": conversation_id, "notice": "The initial query was automatically corrected."}
                return jsonify(response)
            except Exception as final_e:
                print(f"Self-healing failed. Final error: {final_e}")
                error_explanation = diagnose_sql_error(user_question, corrected_sql_raw, str(final_e))
                return jsonify({"sql_query": corrected_sql_raw, "results": {"error": error_explanation}, "conversation_id": conversation_id})
        else:
            error_explanation = diagnose_sql_error(user_question, sql_to_execute, str(e))
            return jsonify({"sql_query": sql_to_execute, "results": {"error": error_explanation}, "conversation_id": conversation_id})

    except ValueError as e:
        return jsonify({"sql_query": raw_sql, "results": {"error": str(e)}, "conversation_id": conversation_id})
    
    except Exception as e:
        print(f"Generic execution error: {e}")
        error_message = f"A database error occurred: {e}"
        return jsonify({"sql_query": sql_to_execute or raw_sql, "results": {"error": error_message}, "conversation_id": conversation_id}), 500

if __name__ == '__main__':
    app.run(debug=True)