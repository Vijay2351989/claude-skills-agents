"""Phase 1: Delete agent — Trash all emails in a given Gmail category."""

import argparse
import sys
import time
import json
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gmail_auth import get_gmail_service, ensure_data_dir

# Gmail query mapping for each category
CATEGORY_QUERIES = {
    "promotions": "category:promotions",
    "forums": "category:forums",
    "social": "category:social",
    "spam": "in:spam",
    "drafts": "in:drafts",
}


def fetch_message_ids(service, query, category):
    """Fetch all message IDs matching the query, paginating through all results."""
    message_ids = []
    page_token = None

    print(f"[{category.upper()}] Fetching emails...")

    while True:
        try:
            if category == "drafts":
                # Drafts use a different API endpoint
                results = service.users().drafts().list(
                    userId="me",
                    maxResults=500,
                    pageToken=page_token,
                ).execute()
                drafts = results.get("drafts", [])
                message_ids.extend([d["id"] for d in drafts])
            else:
                results = service.users().messages().list(
                    userId="me",
                    q=query,
                    maxResults=500,
                    pageToken=page_token,
                ).execute()
                messages = results.get("messages", [])
                message_ids.extend([m["id"] for m in messages])

            page_token = results.get("nextPageToken")
            if not page_token:
                break

            print(f"[{category.upper()}] Fetched {len(message_ids)} so far...")

        except Exception as e:
            if "429" in str(e) or "rateLimitExceeded" in str(e):
                print(f"[{category.upper()}] Rate limited, backing off...")
                time.sleep(5)
                continue
            raise

    print(f"[{category.upper()}] Found {len(message_ids)} emails total.")
    return message_ids


def trash_messages(service, message_ids, category):
    """Move messages to trash. Uses batch delete for efficiency."""
    if not message_ids:
        print(f"[{category.upper()}] No emails to trash.")
        return 0

    trashed = 0
    batch_size = 100  # Gmail batchModify supports up to 1000, but 100 is safer

    if category == "drafts":
        # Drafts must be deleted individually via drafts().delete()
        for draft_id in message_ids:
            retry_count = 0
            while retry_count < 3:
                try:
                    service.users().drafts().delete(
                        userId="me", id=draft_id
                    ).execute()
                    trashed += 1
                    break
                except Exception as e:
                    if "429" in str(e) or "rateLimitExceeded" in str(e):
                        retry_count += 1
                        time.sleep(2 ** retry_count)
                        continue
                    print(f"[DRAFTS] Error deleting draft {draft_id}: {e}")
                    break

            if trashed % 50 == 0 and trashed > 0:
                print(f"[DRAFTS] Deleted {trashed}/{len(message_ids)} drafts...")
    else:
        # Use batchModify to trash messages in bulk
        for i in range(0, len(message_ids), batch_size):
            batch = message_ids[i : i + batch_size]
            retry_count = 0
            while retry_count < 3:
                try:
                    service.users().messages().batchModify(
                        userId="me",
                        body={
                            "ids": batch,
                            "addLabelIds": ["TRASH"],
                            "removeLabelIds": ["INBOX"],
                        },
                    ).execute()
                    trashed += len(batch)
                    print(
                        f"[{category.upper()}] Trashed {trashed}/{len(message_ids)}..."
                    )
                    break
                except Exception as e:
                    if "429" in str(e) or "rateLimitExceeded" in str(e):
                        retry_count += 1
                        wait = 2 ** retry_count
                        print(
                            f"[{category.upper()}] Rate limited, waiting {wait}s..."
                        )
                        time.sleep(wait)
                        continue
                    print(f"[{category.upper()}] Error trashing batch: {e}")
                    # Try individual trash as fallback
                    for msg_id in batch:
                        try:
                            service.users().messages().trash(
                                userId="me", id=msg_id
                            ).execute()
                            trashed += 1
                        except Exception as inner_e:
                            print(
                                f"[{category.upper()}] Failed to trash {msg_id}: {inner_e}"
                            )
                    break

    return trashed


def main():
    parser = argparse.ArgumentParser(description="Gmail Delete Agent")
    parser.add_argument(
        "--category",
        required=True,
        choices=["promotions", "forums", "social", "spam", "drafts"],
        help="Gmail category to delete",
    )
    parser.add_argument("--after", help="Filter emails after date (YYYY/MM/DD)")
    parser.add_argument("--before", help="Filter emails before date (YYYY/MM/DD)")
    args = parser.parse_args()

    category = args.category
    query = CATEGORY_QUERIES[category]
    if args.after:
        query += f" after:{args.after}"
    if args.before:
        query += f" before:{args.before}"

    print(f"=== Gmail Delete Agent: {category.upper()} ===")

    service = get_gmail_service()
    message_ids = fetch_message_ids(service, query, category)
    trashed_count = trash_messages(service, message_ids, category)

    # Save result
    data_dir = ensure_data_dir()
    result = {
        "category": category,
        "total_found": len(message_ids),
        "total_trashed": trashed_count,
    }

    result_path = os.path.join(data_dir, f"delete_result_{category}.json")
    with open(result_path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"\n=== DONE: {category.upper()} ===")
    print(f"Found: {len(message_ids)} | Trashed: {trashed_count}")
    print(f"Results saved to: {result_path}")


if __name__ == "__main__":
    main()
