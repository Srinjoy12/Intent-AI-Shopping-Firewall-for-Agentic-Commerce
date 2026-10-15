"""
Channel3 API Schema & Structured Attributes Inspection Script.

Tests Channel3 connectivity and prints actual schema of structured_attributes
and offers returned by the API.

Run with:
  cd backend && python scripts/test_channel3_schema.py
"""

import json
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv

load_dotenv(backend_dir / ".env")

from app.config import get_settings
from app.channel3_client import search_products, retrieve_product


def main():
    settings = get_settings()
    print("=" * 70)
    print("CHANNEL3 API SCHEMA INSPECTION")
    print("=" * 70)
    print(f"API Key: {'Set' if settings.channel3_api_key else 'MISSING in backend/.env'}")

    if not settings.channel3_api_key:
        print("\nNotice: CHANNEL3_API_KEY is not set. Testing with pre-cached fixtures.")
        from app.fixtures import get_all_fixture_products
        fixtures = get_all_fixture_products()
        print(f"Loaded {len(fixtures)} fixtures:")
        for f in fixtures:
            print(f"\n- Product ID: {f['product_id']}")
            print(f"  Title:      {f['title']}")
            print(f"  Attributes: {json.dumps(f['structured_attributes'], indent=4)}")
            print(f"  Offers:     {len(f['offers'])} offer(s)")
            for off in f['offers']:
                print(f"    * Domain: {off['domain']}, Price: ${off['price']}, Avail: {off['availability']}")
        return

    print("\n[1/2] Searching Channel3 for query 'laptop'...")
    try:
        results = search_products("laptop", limit=2)
        print(f"Retrieved {len(results)} products:")
        for p in results:
            print(f"\nID: {p.get('product_id')}")
            print(f"Title: {p.get('title')}")
            print(f"Structured Attributes: {json.dumps(p.get('structured_attributes', {}), indent=2)}")
            print(f"Offers: {json.dumps(p.get('offers', []), indent=2)}")

        if results:
            sample_id = results[0]["product_id"]
            print(f"\n[2/2] Retrieving single product by ID: {sample_id}...")
            single = retrieve_product(sample_id)
            print(f"Single retrieve success: {bool(single)}")
    except Exception as e:
        print(f"Channel3 search error: {e}")


if __name__ == "__main__":
    main()
