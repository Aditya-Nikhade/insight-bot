import time
import requests

# Set this to your deployed API endpoint
API_URL = "https://insightbot.anikhade.com/query"  # <-- Make sure /query is included!

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

def test_remote_metrics():
    first_response_times = []
    second_response_times = []
    for i, q in enumerate(TEST_QUESTIONS, 1):
        print(f"\nTesting question {i}/{len(TEST_QUESTIONS)}: \"{q}\"")

        # First request (should be a cache miss)
        start1 = time.time()
        resp1 = requests.post(API_URL, json={"question": q})
        elapsed1 = time.time() - start1
        first_response_times.append(elapsed1)
        print(f"  -> First run: {elapsed1:.3f}s")
        try:
            data1 = resp1.json()
            if "notice" in data1:
                print(f"  -> Notice (first run): {data1['notice']}")
        except Exception:
            print(f"  -> Could not parse JSON response (first run). Raw response: {resp1.text[:200]}")

        time.sleep(7)  # Respect API rate limits

        # Second request (should be a cache hit)
        start2 = time.time()
        resp2 = requests.post(API_URL, json={"question": q})
        elapsed2 = time.time() - start2
        second_response_times.append(elapsed2)
        print(f"  -> Second run: {elapsed2:.3f}s")
        try:
            data2 = resp2.json()
            if "notice" in data2:
                print(f"  -> Notice (second run): {data2['notice']}")
        except Exception:
            print(f"  -> Could not parse JSON response (second run). Raw response: {resp2.text[:200]}")

        time.sleep(7)  # Respect API rate limits

    avg_first = sum(first_response_times) / len(first_response_times)
    avg_second = sum(second_response_times) / len(second_response_times)
    reduction = ((avg_first - avg_second) / avg_first) * 100 if avg_first > 0 else 0
    print("\n--- FINAL METRICS ---")
    print(f"Avg. response time (first run, cache miss): {avg_first:.3f} sec")
    print(f"Avg. response time (second run, cache hit): {avg_second:.3f} sec")
    print(f"Response time reduction: {reduction:.1f}%")

if __name__ == "__main__":
    test_remote_metrics() 