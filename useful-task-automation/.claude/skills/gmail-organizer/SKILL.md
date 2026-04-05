---
name: gmail-organizer
description: Clean up and organize Gmail by deleting emails from Promotions, Forums, Social, Spam, and Drafts categories, then categorizing remaining inbox emails into structured labels. Use when cleaning Gmail, organizing inbox, bulk deleting promotional emails, or categorizing emails.
allowed-tools: Read, Grep, Glob, Bash, Agent
---

# Gmail Organizer — Delete & Categorize

## Goal
Two-phase Gmail cleanup:
1. **Phase 1 (Delete)**: Trash all emails in Promotions, Forums, Social, Spam, and Drafts using 5 parallel `gmail-delete` agents
2. **Phase 2 (Categorize)**: Label remaining inbox emails into structured categories using 10 parallel `email-categoriser` agents

## Date Range — IMPORTANT

**By default, this skill operates on a date range, NOT all emails.**

- The user should provide a date range (e.g., "last 7 days", "March 2026", "2026/03/01 to 2026/03/29")
- **If the user does NOT provide a date range, ASK them**: "What date range should I organize? (e.g., 'last 7 days', 'March 2026'). Say 'no date filter' to process all emails."
- **Only process ALL emails if the user explicitly says "no date filter" or "all emails"**
- Date format for the script: `YYYY/MM/DD` (e.g., `2026/03/01`)
- Pass dates via `--after` and `--before` flags to the Python scripts

**Examples:**
- "organize last week" → `--after 2026/03/22 --before 2026/03/30`
- "organize March 2026" → `--after 2026/02/28 --before 2026/03/30`
- "no date filter" → no `--after`/`--before` flags (processes all)

## Gmail Auth
- Token: `config/token.json`
- Credentials: `config/credentials.json`
- Scopes: `https://mail.google.com/` (full access — needed for delete, label, and trash operations)
- If token doesn't exist, the script will launch OAuth flow on first run

---

## Phase 1: Delete Phase

### What Gets Deleted (Moved to Trash)
Only emails that Gmail has already categorized into these built-in categories:
1. **Promotions** — Gmail category `CATEGORY_PROMOTIONS`
2. **Forums** — Gmail category `CATEGORY_FORUMS`
3. **Social** — Gmail category `CATEGORY_SOCIAL`
4. **Spam** — Gmail system label `SPAM`
5. **Drafts** — Gmail system label `DRAFT`

**IMPORTANT**: Do NOT decide categories yourself. Only use Gmail's own category/label assignments.

### Execution
Spawn **5 parallel `gmail-delete` agents** (one per category) using the Agent tool:

```
Agent 1: Delete Promotions  — python3 execution/gmail_delete.py --category promotions
Agent 2: Delete Forums       — python3 execution/gmail_delete.py --category forums
Agent 3: Delete Social       — python3 execution/gmail_delete.py --category social
Agent 4: Delete Spam         — python3 execution/gmail_delete.py --category spam
Agent 5: Delete Drafts       — python3 execution/gmail_delete.py --category drafts
```

Each agent:
1. Fetches all email IDs in its assigned category (paginating through all results)
2. Moves every email (including attachments) to Trash using Gmail API `messages.trash()`
3. Reports count of emails trashed

### After Phase 1
Collect results from all 5 agents. Display a summary table:

| Category   | Emails Trashed |
|------------|---------------|
| Promotions | X             |
| Forums     | X             |
| Social     | X             |
| Spam       | X             |
| Drafts     | X             |
| **Total**  | **X**         |

Confirm Phase 1 is complete before moving to Phase 2.

---

## Phase 2: Categorize Phase

### Labels to Create & Apply
Create these Gmail labels if they don't already exist:

1. **Company Communications**
   - Offer letters, experience letters, relieving letters
   - Interview schedules, onboarding emails
   - Clearance emails, document update requests
   - Background verification communications
   - Any genuine human communication with actual companies (HR, admin, hiring teams)
   - **Smart filter**: Must be actual communication with real companies — not marketing from companies

2. **Shopping and Online Purchases**
   - Order confirmations, order status updates, delivery notifications
   - Invoices and receipts from e-commerce (Amazon, Flipkart, Myntra, Minimalist, FNP, etc.)
   - Food delivery apps (Swiggy, Zomato, etc.)
   - Any purchase-related notification from online platforms

3. **Mediclaim and Life Insurance**
   - Health insurance / mediclaim policy updates and renewals
   - Renewal invoices and payment confirmations
   - Tax certificates (80D) for mediclaim
   - Life insurance policy communications
   - Any insurance-related correspondence

4. **PPF NPS Bank Fundsindia**
   - Public Provident Fund (PPF) notifications and transaction confirmations
   - National Pension Scheme (NPS) communications
   - Bank statements and bank notifications
   - Fundsindia mutual fund investment emails — purchases, SIP confirmations, statements, reports
   - Any investment or banking related communication

5. **Other**
   - Emails that don't clearly fit any of the above 4 categories
   - When in doubt, use this label

### Execution — Orchestration Loop

The skill acts as an **orchestrator** that keeps 10 `email-categorizer` agents active at all times.

**Setup:**
1. Create all 5 labels:
```bash
python3 execution/gmail_categorise.py --create-labels
```

2. Get total inbox email count (with date filter):
```bash
python3 execution/gmail_categorise.py --count-inbox --after YYYY/MM/DD --before YYYY/MM/DD
```
Omit `--after`/`--before` only if user explicitly said "no date filter".
This prints just the number. The skill uses this to calculate how many waves of agents to spawn.

**Orchestration:**

The skill uses the `email-categorizer` agent (defined in `.claude/agents/email-categorizer.md`).

- Each agent is given **100 emails** via an offset and limit
- The skill spawns **10 agents in parallel** using the Agent tool
- Each agent is invoked with: `Use the email-categorizer agent. Process emails at offset=<OFFSET> limit=100`
- The skill tracks `next_offset` — starts at 0, increments by 100 for each agent spawned
- When all 10 agents complete, the skill checks if `next_offset < total_count`
  - If yes: spawn the next batch of 10 agents with the next offsets
  - If no: all emails are categorized, move to summary
- This continues until every email has been assigned to an agent

**Example with 450 emails:**
- Wave 1: Spawn 10 agents → offsets 0, 100, 200, 300, 400, 500, 600, 700, 800, 900
  - Only agents with offset < 450 will find emails; the rest will report 0 emails
- Wave 1 completes → next_offset = 1000 > 450 → done

**Example with 2500 emails:**
- Wave 1: Spawn 10 agents → offsets 0, 100, 200, ..., 900
- Wave 1 completes → next_offset = 1000 < 2500
- Wave 2: Spawn 10 agents → offsets 1000, 1100, 1200, ..., 1900
- Wave 2 completes → next_offset = 2000 < 2500
- Wave 3: Spawn 10 agents → offsets 2000, 2100, 2200, ..., 2900
  - Only agents with offset < 2500 will find emails
- Wave 3 completes → next_offset = 3000 > 2500 → done

### After Phase 2
Collect results from all agents across all waves. Display a summary:

| Label                        | Emails Categorized |
|------------------------------|-------------------|
| Company Communications       | X                 |
| Shopping and Online Purchases| X                 |
| Mediclaim and Life Insurance | X                 |
| PPF NPS Bank Fundsindia      | X                 |
| Other                        | X                 |
| **Total**                    | **X**             |

---

## Project Structure
```
.claude/
├── agents/
│   └── email-categorizer.md          # Agent: reads emails, LLM categorizes, applies labels
└── skills/
    └── gmail-organizer/
        ├── SKILL.md                   # This file (orchestrator)
        ├── config/
        │   ├── credentials.json       # Google OAuth client credentials
        │   └── token.json             # OAuth token (auto-generated)
        ├── execution/
        │   ├── gmail_auth.py          # Shared Gmail authentication helper
        │   ├── gmail_delete.py        # Phase 1: Delete script
        │   └── gmail_categorise.py    # Phase 2: Fetch, read, apply-label script
        ├── data/
        │   └── label_ids.json         # Label name -> Gmail label ID mapping
        └── requirements.txt           # Python dependencies
```

## Dependencies
```
google-api-python-client
google-auth-httplib2
google-auth-oauthlib
```

Install with:
```bash
pip install -r requirements.txt
```

## Edge Cases
- **Large mailbox (10,000+ emails)**: Scripts paginate using `nextPageToken` — no email is missed
- **Rate limits**: Scripts use exponential backoff on Gmail API 429 errors
- **Email fits multiple categories**: Pick the most specific one (e.g., an Amazon invoice goes to "Shopping and Online Purchases", not "Other")
- **Unreadable email / empty body**: Categorize based on sender and subject only; if still unclear, assign "Other"
- **Label already exists**: Skip creation, reuse existing label

## First-Run Setup

Before executing, check if `config/credentials.json` exists. If it doesn't, assume the user is new. In that case:

1. Ask the user if this is their first time running this skill
2. Walk them through:
   - Creating a Google Cloud project and enabling the Gmail API
   - Downloading OAuth 2.0 client credentials as `config/credentials.json`
   - Running `pip install -r requirements.txt`
   - The first run will open a browser for OAuth consent
3. Confirm they're ready before proceeding
