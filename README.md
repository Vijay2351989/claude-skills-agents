# Claude Skills & Agents

A collection of reusable Claude Code skills and agents for automating everyday tasks and supercharging your software development workflow.

## Programming & Coding

### Skills

- **Create Spec from Requirements** — Transforms raw requirements into production-ready specifications by orchestrating system-architect and cto-reviewer agents. Applies expert judgment instead of blindly following requirements.
- **Phase Breakdown** — Partitions large spec documents into focused, modular documents organized by phases, features, or components for better navigation and team collaboration.
- **360 Ticket Resolver** — End-to-end Jira ticket resolution: performs root cause analysis, implements the fix, runs interactive code review, creates a test plan, runs tests relentlessly, and raises a PR with full RCA summary.
- **360 Review** — Orchestrates system-architect, cto-reviewer, and test-architect agents for adversarial analysis of ideas, requirements, or designs. Surfaces weaknesses and finds better alternatives.
- **Brainstorm** — Creative sounding board that orchestrates parallel thinking agents (visionary, systems realist, devil's advocate) to explore ideas and surface alternatives you haven't considered.
- **Project Manager** — Orchestrates end-to-end implementation of spec phases by coordinating elite-engineer, ui-ux-fullstack-savant, test-architect, docs-writer, and cto-code-reviewer agents.
- **Systematic Debugging** — Root-cause-first debugging methodology. No fixes without root cause investigation first.
- **Relentless Fixer** — Runs tests or programs and relentlessly fixes ALL failures by correcting root causes. Zero tolerance — iterates until 100% success.
- **Relentless UX Fixer** — Evaluates and fixes UI/UX issues using Playwright as a real user would. Demands showroom-quality experiences with zero tolerance for friction.
- **Update Docs** — Creates or updates end-user focused documentation based on spec materials, code changes, or guidance.

### Agents

- **Elite Engineer** — Master craftsman agent for writing production-grade code, implementing features, fixing bugs, and architecting solutions.
- **System Architect** — Designs new systems and features, creates technical specifications, and breaks down work into implementation tasks.
- **CTO Reviewer** — Expert-level architectural review, design validation, and strategic technical guidance. Finds gaps and better alternatives.
- **CTO Code Reviewer** — Post-implementation code review against requirements and best practices.
- **Test Architect** — Creates comprehensive automated test suites for CI/CD pipelines using real containers and services — no mocks.
- **UI/UX Fullstack Savant** — Specialist for frontend/UI work including Angular, styling, and BFF layers.
- **Docs Writer** — Generates user guides, API documentation, and READMEs.

## Useful Task Automation

### Skills

- **Gmail Cleanup** — Automatically clean up and manage your Gmail inbox
- **Gmail Organizer** — Categorize and organize emails by type
- **Movie Recommender** — Get personalized movie recommendations
- **Amazon Shopping** — Assist with Amazon shopping tasks

### Agents

- **Email Categorizer** — Classify emails into categories
- **Delete Email** — Bulk delete unwanted emails
- **Movie Discovery** — Multi-agent pipeline (IMDb, critics, word-of-mouth, OTT availability, scoring) for finding movies to watch

## Project Structure

```
├── programming-and-coding/
│   └── .claude/
│       ├── skills/       # Dev workflow skills (spec, review, debugging, etc.)
│       ├── agents/       # Specialist agents (engineer, architect, reviewer, etc.)
│       └── rules/        # Team orchestration rules
└── useful-task-automation/
    └── .claude/
        ├── skills/       # Task automation skills (email, shopping, movies)
        └── agents/       # Task automation agents
```

## Usage

Copy the skills and agents you need into your own Claude Code project's `.claude/` directory to start using them.
