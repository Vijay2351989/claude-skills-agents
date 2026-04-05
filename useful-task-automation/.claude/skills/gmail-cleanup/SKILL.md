---
name: gmail-cleanup
description: Clean up Gmail by deleting emails per label using configurable generic and label-specific rules. Supports older-than, from-filter, subject-filter, size, read/unread status, and raw Gmail queries. Runs in parallel — one agent per label, sub-agents per 500-email batch.
allowed-tools: Read, Bash, Edit, Write, Agent
---

# Gmail Cleanup — Rule-Based Email Deletion (Parallel)

Delete emails from Gmail labels using generic rules (apply to all targeted labels) and label-specific rules. All rules live in `config/rules.json`.

## Cutoff Date — IMPORTANT

**By default, this skill requires a cutoff date to protect recent emails.**

- The user should provide a cutoff date (e.g., "before March 2026", "older than 30 days", "before 2026/03/01")
- **If the user does NOT provide a cutoff date, ASK them**: "What cutoff date should I use? Only emails BEFORE this date will be deleted. Say 'no cutoff date' to delete all matching emails regardless of date."
- **Only skip the cutoff date if the user explicitly says "no cutoff date" or "all dates"**
- Date format for the script: `YYYY/MM/DD` (e.g., `2026/03/01`)
- Pass cutoff via `--before YYYY/MM/DD` flag to all Python script commands (`--preview`, `--cleanup`, `--fetch-ids`)

**Examples:**
- "clean up emails before March 2026" → `--before 2026/03/01`
- "delete emails older than 6 months" → calculate date, use `--before YYYY/MM/DD`
- "no cutoff date" → no `--before` flag (deletes all matching emails)

## Allowed Labels

This skill ONLY operates on these 5 custom labels:
- Company Communications
- Shopping and Online Purchases
- Mediclaim and Life Insurance
- PPF NPS Bank Fundsindia
- Other

## Config File

**Path:** `.claude/skills/gmail-cleanup/config/rules.json`

## Rule Fields

Each rule is a JSON object. All fields are optional and combined with AND logic:

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Human-readable rule name (for display only) |
| `older_than_days` | int | Match emails older than N days |
| `from_contains` | string | Match emails where From contains this |
| `subject_contains` | string | Match emails where Subject contains this |
| `has_attachment` | bool | true = with attachments, false = without attachments |
| `is_unread` | bool | true = unread only, false = read only |
| `size_larger_than` | string | Match emails larger than size (e.g. "5M", "1M") |
| `query` | string | Raw Gmail search query for advanced use |

## Commands

```bash
SCRIPT=".claude/skills/gmail-cleanup/execution/gmail_cleanup.py"

# List labels with email counts
python3 $SCRIPT --list-labels

# Preview what would be deleted (dry run) — with cutoff date
python3 $SCRIPT --preview --before 2026/03/01
python3 $SCRIPT --preview --label "Company Communications" --before 2026/03/01

# Sequential cleanup (single-threaded, for small jobs) — with cutoff date
python3 $SCRIPT --cleanup --label "Company Communications" --before 2026/03/01

# Parallel batch commands (used by delete-email agent) — with cutoff date:
python3 $SCRIPT --fetch-ids --label "Company Communications" --before 2026/03/01
python3 $SCRIPT --trash-batch --label "Company Communications" --start 0 --size 500
```

**Note:** `--before` is applied during `--fetch-ids` (filters which emails are saved to the IDs file). The `--trash-batch` command does NOT need `--before` since it just trashes IDs already saved by `--fetch-ids`.

## Parallel Execution — How to Run Cleanup

When the user says "clean up my gmail" or "run cleanup", follow this two-level parallel approach.

### Step 1: Read the agent instructions

Read the delete-email agent definition:
```
.claude/agents/delete-email.md
```

This file contains the full instructions for how each label agent should work (fetch IDs → calculate batches → spawn parallel sub-agents for each 500 emails).

### Step 2: Spawn 5 parallel agents (one per label)

Use the Agent tool to spawn 5 `general-purpose` agents in a SINGLE message. For each agent, use the content from `delete-email.md` as the base prompt, replacing LABEL_NAME with the actual label:

```
Agent 1: "Company Communications"
Agent 2: "Shopping and Online Purchases"
Agent 3: "Mediclaim and Life Insurance"
Agent 4: "PPF NPS Bank Fundsindia"
Agent 5: "Other"
```

Each agent will internally handle Level 2 parallelization — spawning sub-agents for every 500-email batch.

### Step 3: Collect and report results

After all 5 agents complete, summarize:
- Per-label: matched count, trashed count, batches used
- Total emails trashed across all labels

## How to Handle User Requests

| User says | Action |
|-----------|--------|
| "clean up my gmail" | Read `.claude/agents/delete-email.md`, spawn 5 parallel agents (one per label) |
| "clean up Company Communications" | Read agent instructions, spawn 1 agent for that label |
| "preview cleanup" | Run `--preview` to show what would be matched |
| "show my labels" | Run `--list-labels` |
| "add a cleanup rule for ..." | Edit `config/rules.json` to add the rule |
| "what are the current rules?" | Read and display `config/rules.json` |
| "show cleanup history" | Read `data/cleanup_log.json` |
| "find top senders in LABEL" | Run sender analysis for that label |

## Important Rules

- **Always preview before first cleanup.** Run `--preview` first and show the user what will be matched.
- **Ask for confirmation** before running cleanup.
- **Emails are trashed, not permanently deleted.** Users can recover from Trash within 30 days.
- Config is the single source of truth — all changes go through `config/rules.json`.

## Authentication

Uses the same OAuth token as gmail-organizer. If token expires, re-run the auth flow:
```bash
python3 .claude/skills/gmail-cleanup/execution/gmail_auth.py
```
