"""Gmail Cleanup — delete emails per label using generic + label-specific rules.

Usage:
  python3 gmail_cleanup.py --list-labels                  List all Gmail labels
  python3 gmail_cleanup.py --preview                      Preview what would be deleted (dry run)
  python3 gmail_cleanup.py --preview --label "LABEL"      Preview for a specific label only
  python3 gmail_cleanup.py --cleanup                      Execute cleanup (trash matching emails)
  python3 gmail_cleanup.py --cleanup --label "LABEL"      Cleanup a specific label only
  python3 gmail_cleanup.py --stats                        Show email count per label

  Parallel batch commands (used by delete-email agent):
  python3 gmail_cleanup.py --fetch-ids --label "LABEL"    Fetch matching IDs → saves to data/<label>_ids.json
  python3 gmail_cleanup.py --trash-batch --label "LABEL" --start 0 --size 500  Trash a batch of IDs

Rules are loaded from config/rules.json.
"""

import os
import sys
import json
import argparse
import time
import re
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gmail_auth import get_gmail_service, ensure_data_dir, DATA_DIR

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES_PATH = os.path.join(SKILL_DIR, "config", "rules.json")
LOG_PATH = os.path.join(SKILL_DIR, "data", "cleanup_log.json")

# Only operate on these custom labels — no system/category/inbox labels
ALLOWED_LABELS = {
    "Company Communications",
    "Shopping and Online Purchases",
    "Mediclaim and Life Insurance",
    "PPF NPS Bank Fundsindia",
    "Other",
}


def load_rules():
    """Load cleanup rules from config/rules.json."""
    if not os.path.exists(RULES_PATH):
        print(f"No rules file found at {RULES_PATH}")
        return {"generic_rules": [], "label_rules": {}}
    with open(RULES_PATH) as f:
        return json.load(f)


def load_log():
    try:
        with open(LOG_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def append_log(entry):
    ensure_data_dir()
    log = load_log()
    log.append({**entry, "timestamp": datetime.now().isoformat()})
    with open(LOG_PATH, "w") as f:
        json.dump(log, f, indent=2)


def list_labels(service):
    """List all Gmail labels with message counts."""
    results = service.users().labels().list(userId="me").execute()
    labels = results.get("labels", [])

    # Fetch details for each label to get counts
    print(f"\n{'Label':<45} {'Total':>8} {'Unread':>8}")
    print("-" * 65)

    for label in sorted(labels, key=lambda l: l["name"]):
        if label["name"] not in ALLOWED_LABELS:
            continue
        try:
            detail = service.users().labels().get(userId="me", id=label["id"]).execute()
            total = detail.get("messagesTotal", 0)
            unread = detail.get("messagesUnread", 0)
            print(f"{label['name']:<45} {total:>8} {unread:>8}")
        except Exception:
            print(f"{label['name']:<45} {'?':>8} {'?':>8}")

    print()


def get_label_id_map(service):
    """Return a map of label name -> label id."""
    results = service.users().labels().list(userId="me").execute()
    return {l["name"]: l["id"] for l in results.get("labels", [])}


def build_query_from_rule(rule, cutoff_date=None):
    """Build a Gmail search query string from a rule dict.

    Supported rule fields:
      older_than_days: int       — emails older than N days
      from_contains: str         — from address contains this string
      subject_contains: str      — subject contains this string
      has_attachment: bool       — has attachment
      is_unread: bool            — is unread
      query: str                 — raw Gmail search query (advanced)
      size_larger_than: str      — size larger than (e.g. "5M", "1M")

    cutoff_date: str (YYYY/MM/DD) — if provided, only match emails before this date
    """
    parts = []

    if cutoff_date:
        parts.append(f"before:{cutoff_date}")

    if "older_than_days" in rule:
        days = rule["older_than_days"]
        date = (datetime.now() - timedelta(days=days)).strftime("%Y/%m/%d")
        parts.append(f"before:{date}")

    if "from_contains" in rule:
        parts.append(f"from:{rule['from_contains']}")

    if "subject_contains" in rule:
        parts.append(f"subject:({rule['subject_contains']})")

    if "has_attachment" in rule:
        if rule["has_attachment"]:
            parts.append("has:attachment")
        else:
            parts.append("-has:attachment")

    if "is_unread" in rule:
        if rule["is_unread"]:
            parts.append("is:unread")
        else:
            parts.append("is:read")

    if "size_larger_than" in rule:
        parts.append(f"larger:{rule['size_larger_than']}")

    if "query" in rule:
        parts.append(rule["query"])

    return " ".join(parts)


def fetch_matching_emails(service, label_id, query, max_results=None):
    """Fetch email IDs matching a query within a label. No limit if max_results is None."""
    all_ids = []
    page_token = None

    while True:
        try:
            batch_size = 500
            if max_results:
                batch_size = min(max_results - len(all_ids), 500)
            kwargs = {
                "userId": "me",
                "labelIds": [label_id],
                "q": query,
                "maxResults": batch_size,
            }
            if page_token:
                kwargs["pageToken"] = page_token

            results = service.users().messages().list(**kwargs).execute()
            messages = results.get("messages", [])
            all_ids.extend([m["id"] for m in messages])

            if max_results and len(all_ids) >= max_results:
                break

            page_token = results.get("nextPageToken")
            if not page_token:
                break

        except Exception as e:
            if "429" in str(e):
                print("    Rate limited, waiting 5s...")
                time.sleep(5)
                continue
            raise

    return all_ids


def get_email_summary(service, msg_id):
    """Get a short summary of an email for preview."""
    try:
        msg = service.users().messages().get(
            userId="me", id=msg_id, format="metadata",
            metadataHeaders=["From", "Subject", "Date"]
        ).execute()

        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        return {
            "id": msg_id,
            "from": headers.get("From", "unknown"),
            "subject": headers.get("Subject", "(no subject)"),
            "date": headers.get("Date", ""),
        }
    except Exception:
        return {"id": msg_id, "from": "?", "subject": "?", "date": "?"}


def trash_emails(service, msg_ids):
    """Move emails to trash in batches."""
    batch_size = 100
    trashed = 0

    for i in range(0, len(msg_ids), batch_size):
        batch = msg_ids[i:i + batch_size]
        retries = 0
        while retries < 3:
            try:
                service.users().messages().batchModify(
                    userId="me",
                    body={
                        "ids": batch,
                        "addLabelIds": ["TRASH"],
                        "removeLabelIds": ["INBOX"],
                    }
                ).execute()
                trashed += len(batch)
                break
            except Exception as e:
                if "429" in str(e):
                    retries += 1
                    wait = 2 ** retries
                    print(f"    Rate limited, waiting {wait}s...")
                    time.sleep(wait)
                else:
                    print(f"    Error trashing batch: {e}")
                    break

    return trashed


def process_label(service, label_name, label_id, generic_rules, label_rules, dry_run=True, cutoff_date=None):
    """Process a single label: apply generic + label-specific rules."""
    all_rules = []

    # Add generic rules
    for rule in generic_rules:
        all_rules.append({"source": "generic", **rule})

    # Add label-specific rules
    for rule in label_rules:
        all_rules.append({"source": f"label:{label_name}", **rule})

    if not all_rules:
        return {"label": label_name, "rules_applied": 0, "matched": 0, "trashed": 0}

    total_matched = []
    rule_results = []

    for rule in all_rules:
        rule_copy = {k: v for k, v in rule.items() if k != "source"}
        source = rule.get("source", "unknown")
        name = rule.get("name", build_query_from_rule(rule_copy, cutoff_date=cutoff_date))
        query = build_query_from_rule(rule_copy, cutoff_date=cutoff_date)

        if not query.strip():
            continue

        print(f"  Rule: {name}")
        print(f"    Query: {query}")

        matched_ids = fetch_matching_emails(service, label_id, query)
        print(f"    Matched: {len(matched_ids)} emails")

        rule_results.append({
            "rule_name": name,
            "source": source,
            "query": query,
            "matched": len(matched_ids),
        })

        if matched_ids:
            # Show preview of first 3
            if dry_run:
                previews = min(3, len(matched_ids))
                for mid in matched_ids[:previews]:
                    summary = get_email_summary(service, mid)
                    print(f"      - {summary['from'][:40]}  |  {summary['subject'][:50]}  |  {summary['date']}")
                if len(matched_ids) > previews:
                    print(f"      ... and {len(matched_ids) - previews} more")

            total_matched.extend(matched_ids)

    # Deduplicate
    unique_ids = list(set(total_matched))

    trashed = 0
    if not dry_run and unique_ids:
        print(f"  Trashing {len(unique_ids)} emails...")
        trashed = trash_emails(service, unique_ids)
        print(f"  Trashed: {trashed}")

    return {
        "label": label_name,
        "rules_applied": len([r for r in rule_results if r["query"].strip()]),
        "matched": len(unique_ids),
        "trashed": trashed,
        "rule_details": rule_results,
    }


def show_stats(service):
    """Show email count per label."""
    list_labels(service)


def fetch_and_save_ids(service, label_name, label_id, generic_rules, label_rules, cutoff_date=None):
    """Fetch all matching email IDs for a label and save to data/<label>_ids.json.
    Returns the count of unique IDs."""
    all_rules = list(generic_rules) + list(label_rules)
    if not all_rules:
        return 0

    all_ids = []
    for rule in all_rules:
        query = build_query_from_rule(rule, cutoff_date=cutoff_date)
        if not query.strip():
            continue
        print(f"  Rule: {rule.get('name', query)}")
        print(f"    Query: {query}")
        matched = fetch_matching_emails(service, label_id, query)
        print(f"    Matched: {len(matched)}")
        all_ids.extend(matched)

    unique_ids = list(set(all_ids))
    # Save to file
    ensure_data_dir()
    safe_name = label_name.replace(" ", "_").replace("/", "_")
    ids_file = os.path.join(DATA_DIR, f"{safe_name}_ids.json")
    with open(ids_file, "w") as f:
        json.dump({"label": label_name, "count": len(unique_ids), "ids": unique_ids}, f)
    print(f"  Total unique: {len(unique_ids)} → saved to {ids_file}")
    return len(unique_ids)


def trash_batch_from_file(service, label_name, start, size):
    """Read IDs from data/<label>_ids.json and trash a specific batch."""
    safe_name = label_name.replace(" ", "_").replace("/", "_")
    ids_file = os.path.join(DATA_DIR, f"{safe_name}_ids.json")

    if not os.path.exists(ids_file):
        print(f"ERROR: IDs file not found: {ids_file}")
        print("Run --fetch-ids first.")
        return 0

    with open(ids_file) as f:
        data = json.load(f)

    all_ids = data["ids"]
    batch_ids = all_ids[start:start + size]

    if not batch_ids:
        print(f"  No emails in range [{start}:{start + size}] (total: {len(all_ids)})")
        return 0

    print(f"  Trashing batch [{start}:{start + len(batch_ids)}] of {len(all_ids)} total...")
    trashed = trash_emails(service, batch_ids)
    print(f"  Trashed: {trashed}")

    append_log({
        "mode": "trash-batch",
        "label": label_name,
        "batch_start": start,
        "batch_size": size,
        "trashed": trashed,
    })

    return trashed


def main():
    parser = argparse.ArgumentParser(description="Gmail Cleanup")
    parser.add_argument("--list-labels", action="store_true", help="List all labels")
    parser.add_argument("--preview", action="store_true", help="Preview cleanup (dry run)")
    parser.add_argument("--cleanup", action="store_true", help="Execute cleanup")
    parser.add_argument("--stats", action="store_true", help="Show email stats per label")
    parser.add_argument("--fetch-ids", action="store_true", help="Fetch matching IDs and save to file")
    parser.add_argument("--trash-batch", action="store_true", help="Trash a batch of IDs from saved file")
    parser.add_argument("--label", type=str, help="Process only this label")
    parser.add_argument("--start", type=int, default=0, help="Batch start index (for --trash-batch)")
    parser.add_argument("--size", type=int, default=500, help="Batch size (for --trash-batch)")
    parser.add_argument("--before", type=str, default=None,
                        help="Cutoff date — only delete emails BEFORE this date (YYYY/MM/DD)")
    args = parser.parse_args()

    if not any([args.list_labels, args.preview, args.cleanup, args.stats, args.fetch_ids, args.trash_batch]):
        parser.print_help()
        return

    service = get_gmail_service()

    if args.list_labels:
        list_labels(service)
        return

    if args.stats:
        show_stats(service)
        return

    if args.fetch_ids:
        if not args.label:
            print("ERROR: --fetch-ids requires --label")
            return
        if args.label not in ALLOWED_LABELS:
            print(f"Label '{args.label}' is not in the allowed list.")
            return
        rules = load_rules()
        label_id_map = get_label_id_map(service)
        if args.label not in label_id_map:
            print(f"Label '{args.label}' not found in Gmail.")
            return
        generic_rules = rules.get("generic_rules", [])
        label_rules = rules.get("label_rules", {}).get(args.label, [])
        print(f"\n[{args.label}] Fetching matching email IDs...")
        if args.before:
            print(f"  Cutoff date: only emails before {args.before}")
        count = fetch_and_save_ids(service, args.label, label_id_map[args.label], generic_rules, label_rules, cutoff_date=args.before)
        print(f"\nDone. {count} emails ready for deletion.")
        return

    if args.trash_batch:
        if not args.label:
            print("ERROR: --trash-batch requires --label")
            return
        if args.label not in ALLOWED_LABELS:
            print(f"Label '{args.label}' is not in the allowed list.")
            return
        print(f"\n[{args.label}] Trashing batch [start={args.start}, size={args.size}]...")
        trashed = trash_batch_from_file(service, args.label, args.start, args.size)
        print(f"\nDone. {trashed} emails trashed.")
        return

    # Load rules
    rules = load_rules()
    generic_rules = rules.get("generic_rules", [])
    label_rules_map = rules.get("label_rules", {})

    if not generic_rules and not label_rules_map:
        print("No rules configured in config/rules.json")
        print("Add generic_rules and/or label_rules, then re-run.")
        return

    # Get label name -> id map
    label_id_map = get_label_id_map(service)

    # Determine which labels to process — only allowed labels
    if args.label:
        if args.label not in ALLOWED_LABELS:
            print(f"Label '{args.label}' is not in the allowed list.")
            print(f"Allowed labels: {', '.join(sorted(ALLOWED_LABELS))}")
            return
        target_labels = [args.label]
    else:
        # Generic rules apply to all allowed labels; label-specific rules to their label
        target_labels = list(ALLOWED_LABELS)
        # Also include any label-specific rule targets that are in allowed list
        for lbl in label_rules_map:
            if lbl in ALLOWED_LABELS and lbl not in target_labels:
                target_labels.append(lbl)

    dry_run = args.preview
    mode = "PREVIEW" if dry_run else "CLEANUP"
    print(f"\n{'=' * 60}")
    print(f"  Gmail Cleanup — {mode}")
    print(f"{'=' * 60}")
    print(f"  Generic rules: {len(generic_rules)}")
    print(f"  Labels with specific rules: {len(label_rules_map)}")
    print(f"  Target labels: {len(target_labels)}")
    if args.before:
        print(f"  Cutoff date: only emails before {args.before}")
    print(f"{'=' * 60}\n")

    all_results = []

    for label_name in sorted(target_labels):
        if label_name not in label_id_map:
            print(f"\n[{label_name}] — Label not found in Gmail, skipping.")
            continue

        label_id = label_id_map[label_name]
        label_specific = label_rules_map.get(label_name, [])

        print(f"\n[{label_name}]")
        result = process_label(
            service, label_name, label_id,
            generic_rules, label_specific,
            dry_run=dry_run, cutoff_date=args.before
        )
        all_results.append(result)

    # Summary
    total_matched = sum(r["matched"] for r in all_results)
    total_trashed = sum(r["trashed"] for r in all_results)

    print(f"\n{'=' * 60}")
    print(f"  Summary")
    print(f"{'=' * 60}")
    for r in all_results:
        status = f"matched {r['matched']}"
        if not dry_run:
            status += f", trashed {r['trashed']}"
        print(f"  {r['label']:<40} {status}")
    print(f"\n  Total: {total_matched} matched", end="")
    if not dry_run:
        print(f", {total_trashed} trashed", end="")
    print()

    # Log the run
    ensure_data_dir()
    append_log({
        "mode": mode.lower(),
        "labels_processed": len(all_results),
        "total_matched": total_matched,
        "total_trashed": total_trashed,
        "results": all_results,
    })


if __name__ == "__main__":
    main()
