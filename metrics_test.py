import time
import json
import redis  # Import redis
from app import app, redis_client  # Import redis_client from your app

# Sample user questions for testing
TEST_QUESTIONS = [
    "List all customers who signed up in 2023.",
    "Show the top 5 products by sales.",
    "How many sales were made last month?",
    "What is the average price of products in the 'Electronics' category?",
    "Give me the total quantity sold for each product.",
    "Who are the top 3 customers by total purchases?",
    "List all products.",
    "Show all sales for customer named 'Alice'.",
    "What is the total revenue for each month?",
    "List customers who bought more than 10 items in a single sale."
]


def clear_cache():
    """Clears the Redis cache to ensure a clean test environment."""
    if redis_client:
        print("Clearing Redis cache...")
        redis_client.flushdb()
        print("Cache cleared.")
    else:
        print("Redis client not available, skipping cache clear.")


def test_metrics():
    # --- FIX 1: Ensure a clean state before starting the test ---
    clear_cache()

    client = app.test_client()
    successful_generations = 0
    total = len(TEST_QUESTIONS)
    first_response_times = []
    second_response_times = []
    inferred_cache_hits = 0

    print("\nTesting query translation and caching...")
    for i, q in enumerate(TEST_QUESTIONS, 1):
        print(f"Testing question {i}/{total}: \"{q}\"")

        # --- First request (should be a cache miss) ---
        start_time1 = time.time()
        resp1 = client.post('/query', json={"question": q})
        elapsed1 = time.time() - start_time1
        first_response_times.append(elapsed1)

        data1 = resp1.get_json()
        sql1 = data1.get("sql_query", "")
        results1 = data1.get("results")
        error1 = None
        if isinstance(results1, dict):
            error1 = results1.get("error")

        # Check for successful generation (not necessarily logical accuracy)
        if sql1 and "N/A" not in sql1 and not error1:
            successful_generations += 1
            print(f"  -> Success (First Run): Took {elapsed1:.3f}s")
        else:
            print(f"  -> FAILED (First Run): {error1 or 'No SQL generated'}")

        time.sleep(7)  # <-- Add this line

        # --- Second request (should be a cache hit) ---
        start_time2 = time.time()
        resp2 = client.post('/query', json={"question": q})
        elapsed2 = time.time() - start_time2
        second_response_times.append(elapsed2)
        print(f"  -> Second Run: Took {elapsed2:.3f}s")
        time.sleep(7)  # <-- Add this line
        # Infer a cache hit based on response time. This is a reasonable
        # assumption but not a guarantee. A better method would be to
        # check a response header like 'X-Cache: HIT'.
        if elapsed2 < elapsed1 * 0.5:
            inferred_cache_hits += 1

    print("\n--- METRICS ---")
    # FIX 2: Renamed metric for clarity
    print(f"Successful Generation Rate: {successful_generations}/{total} ({successful_generations/total*100:.1f}%)")
    print(f"Avg. response time (cache miss): {sum(first_response_times)/total:.3f} sec")
    print(f"Avg. response time (cache hit):  {sum(second_response_times)/total:.3f} sec")
    print(f"Inferred Cache Hit Rate:      {inferred_cache_hits}/{total} ({inferred_cache_hits/total*100:.1f}%)")

if __name__ == "__main__":
    test_metrics()