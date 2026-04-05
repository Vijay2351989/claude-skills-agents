"""Phase 2: Categorise — Count inbox, read emails by offset, create labels, apply labels."""

import argparse
import sys
import time
import json
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gmail_auth import get_gmail_service, ensure_data_dir

LABELS = [
    "Company Communications",
    "Shopping and Online Purchases",
    "Mediclaim and Life Insurance",
    "PPF NPS Bank Fundsindia",
    "Other",
]


def create_labels(service):
    """Create Gmail labels if they don't already exist."""
    print("Creating labels...")

    results = service.users().labels().list(userId="me").execute()
    existing = {label["name"]: label["id"] for label in results.get("labels", [])}

    label_ids = {}
    for label_name in LABELS:
        if label_name in existing:
            print(f"  Label '{label_name}' already exists.")
            label_ids[label_name] = existing[label_name]
        else:
            label_body = {
                "name": label_name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            }
            created = service.users().labels().create(
                userId="me", body=label_body
            ).execute()
            label_ids[label_name] = created["id"]
            print(f"  Created label '{label_name}' (id: {created['id']})")

    data_dir = ensure_data_dir()
    with open(os.path.join(data_dir, "label_ids.json"), "w") as f:
        json.dump(label_ids, f, indent=2)

    print(f"\nAll {len(LABELS)} labels ready.")
    return label_ids


def count_inbox(service, after=None, before=None):
    """Count total inbox emails by paginating through message IDs (lightweight)."""
    count = 0
    page_token = None

    query = "in:inbox"
    if after:
        query += f" after:{after}"
    if before:
        query += f" before:{before}"

    while True:
        try:
            results = service.users().messages().list(
                userId="me",
                q=query,
                maxResults=500,
                pageToken=page_token,
            ).execute()

            messages = results.get("messages", [])
            count += len(messages)

            page_token = results.get("nextPageToken")
            if not page_token:
                break

        except Exception as e:
            if "429" in str(e) or "rateLimitExceeded" in str(e):
                time.sleep(5)
                continue
            raise

    print(count)
    return count


def _load_custom_label_ids():
    """Load custom label IDs from label_ids.json if it exists."""
    data_dir = ensure_data_dir()
    labels_path = os.path.join(data_dir, "label_ids.json")
    if os.path.exists(labels_path):
        with open(labels_path) as f:
            label_map = json.load(f)
        return set(label_map.values())
    return set()


def read_emails(service, offset, limit, after=None, before=None):
    """Fetch emails from inbox at the given offset/limit and print them.

    Gmail API doesn't support offset-based pagination, so we paginate
    through message IDs, skip `offset` messages, then fetch full metadata
    for the next `limit` messages. Skips emails that already have a custom label.
    """
    # Load custom label IDs to skip already-categorized emails
    custom_label_ids = _load_custom_label_ids()

    # Build query with optional date filters
    query = "in:inbox"
    if after:
        query += f" after:{after}"
    if before:
        query += f" before:{before}"

    # Step 1: Collect all inbox message IDs by paginating
    # For large offsets, use before: date filter to narrow results and avoid
    # stale page tokens that cause "Precondition check failed" errors.
    all_ids = []
    page_token = None
    precondition_retries = 0

    while True:
        try:
            results = service.users().messages().list(
                userId="me",
                q=query,
                maxResults=500,
                pageToken=page_token,
            ).execute()

            messages = results.get("messages", [])
            all_ids.extend([m["id"] for m in messages])

            # Optimization: stop early if we have enough IDs
            if len(all_ids) >= offset + limit:
                break

            page_token = results.get("nextPageToken")
            if not page_token:
                break

            # Reset precondition retry counter on success
            precondition_retries = 0

        except Exception as e:
            if "429" in str(e) or "rateLimitExceeded" in str(e):
                time.sleep(5)
                continue
            if "failedPrecondition" in str(e) or "Precondition check failed" in str(e):
                precondition_retries += 1
                if precondition_retries <= 3:
                    print(f"  Page token expired (attempt {precondition_retries}/3), "
                          f"retrying after pause... (collected {len(all_ids)} IDs so far)")
                    time.sleep(2 ** precondition_retries)
                    # Invalidate the page token and restart pagination from scratch,
                    # but only collect IDs we haven't seen yet
                    collected_set = set(all_ids)
                    page_token = None
                    skip_known = True
                    restart_ids = []
                    while True:
                        try:
                            results = service.users().messages().list(
                                userId="me",
                                q=query,
                                maxResults=500,
                                pageToken=page_token,
                            ).execute()
                            messages = results.get("messages", [])
                            for m in messages:
                                mid = m["id"]
                                if mid not in collected_set:
                                    restart_ids.append(mid)
                                    collected_set.add(mid)
                            if len(all_ids) + len(restart_ids) >= offset + limit:
                                break
                            page_token = results.get("nextPageToken")
                            if not page_token:
                                break
                        except Exception as inner_e:
                            if "429" in str(inner_e) or "rateLimitExceeded" in str(inner_e):
                                time.sleep(5)
                                continue
                            # If we fail again with precondition, break with what we have
                            print(f"  Retry also failed: {inner_e}")
                            break
                    all_ids.extend(restart_ids)
                    break  # Exit outer loop with what we have
                else:
                    print(f"  Precondition error persists after {precondition_retries} retries. "
                          f"Using {len(all_ids)} IDs collected so far.")
                    break
            raise

    # Step 2: Slice to our batch
    batch_ids = all_ids[offset:offset + limit]

    if not batch_ids:
        print(f"=== No emails at offset {offset} (total: {len(all_ids)}) ===")
        return []

    print(f"=== Emails {offset + 1} to {offset + len(batch_ids)} ===\n")

    # Step 3: Fetch metadata for each email in the batch, skip already-labeled
    skipped = 0
    printed = 0
    for i, msg_id in enumerate(batch_ids):
        retry_count = 0
        while retry_count < 3:
            try:
                msg = service.users().messages().get(
                    userId="me",
                    id=msg_id,
                    format="metadata",
                    metadataHeaders=["From", "Subject", "To", "Date"],
                ).execute()

                # Skip if email already has one of our custom labels
                msg_labels = set(msg.get("labelIds", []))
                if custom_label_ids and msg_labels & custom_label_ids:
                    skipped += 1
                    break

                headers = {
                    h["name"]: h["value"]
                    for h in msg.get("payload", {}).get("headers", [])
                }

                printed += 1
                print(f"--- Email {offset + i + 1} ---")
                print(f"ID: {msg_id}")
                print(f"From: {headers.get('From', '')}")
                print(f"Subject: {headers.get('Subject', '')}")
                print(f"Date: {headers.get('Date', '')}")
                print(f"Snippet: {msg.get('snippet', '')}")
                print()
                break

            except Exception as e:
                if "429" in str(e) or "rateLimitExceeded" in str(e):
                    retry_count += 1
                    time.sleep(2 ** retry_count)
                    continue
                print(f"  Error fetching message {msg_id}: {e}")
                break

    print(f"=== End of batch ({printed} emails to categorize, {skipped} already labeled) ===")
    return batch_ids


def apply_label(service, email_id, label_name):
    """Apply a Gmail label to a single email."""
    data_dir = ensure_data_dir()
    labels_path = os.path.join(data_dir, "label_ids.json")
    if not os.path.exists(labels_path):
        print("ERROR: label_ids.json not found. Run --create-labels first.")
        sys.exit(1)

    with open(labels_path) as f:
        label_ids = json.load(f)

    if label_name not in label_ids:
        print(f"ERROR: Unknown label '{label_name}'. Valid: {', '.join(label_ids.keys())}")
        sys.exit(1)

    label_id = label_ids[label_name]

    retry_count = 0
    while retry_count < 3:
        try:
            service.users().messages().modify(
                userId="me",
                id=email_id,
                body={"addLabelIds": [label_id]},
            ).execute()
            print(f"OK: {email_id} -> {label_name}")
            return True
        except Exception as e:
            if "429" in str(e) or "rateLimitExceeded" in str(e):
                retry_count += 1
                time.sleep(2 ** retry_count)
                continue
            print(f"ERROR: Failed to label {email_id}: {e}")
            return False

    print(f"ERROR: Rate limit exceeded for {email_id}")
    return False


def main():
    parser = argparse.ArgumentParser(description="Gmail Categorise")
    parser.add_argument("--create-labels", action="store_true", help="Create Gmail labels")
    parser.add_argument("--count-inbox", action="store_true", help="Print total inbox email count")
    parser.add_argument("--read-emails", action="store_true", help="Read emails at given offset/limit from Gmail")
    parser.add_argument("--offset", type=int, default=0, help="Start offset for --read-emails")
    parser.add_argument("--limit", type=int, default=100, help="Number of emails for --read-emails")
    parser.add_argument("--after", type=str, default=None, help="Only emails after this date (YYYY/MM/DD)")
    parser.add_argument("--before", type=str, default=None, help="Only emails before this date (YYYY/MM/DD)")
    parser.add_argument("--apply-label", nargs=2, metavar=("EMAIL_ID", "LABEL_NAME"),
                        help="Apply a label to a single email")
    args = parser.parse_args()

    service = get_gmail_service()

    if args.create_labels:
        create_labels(service)
    elif args.count_inbox:
        count_inbox(service, after=args.after, before=args.before)
    elif args.read_emails:
        read_emails(service, args.offset, args.limit, after=args.after, before=args.before)
    elif args.apply_label:
        email_id, label_name = args.apply_label
        apply_label(service, email_id, label_name)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
