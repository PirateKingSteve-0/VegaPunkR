# Diagram Maintenance Scripts

This directory contains the architecture diagram maintenance system.

## Files

- **`diagram_agent.py`** - Pre-commit hook that detects when architecture diagrams need updating
- **`update_diagrams.py`** - Helper script for manual or automated diagram updates
- **`.diagram_update_context.json`** - Auto-generated context (git-ignored)

## Quick Start

```bash
# Install pre-commit
pip install pre-commit
pre-commit install

# Now whenever you commit architecture files, you'll get a reminder to update diagrams
git add api/models.py
git commit -m "Add new field"
# → Hook will tell you which diagram sections to update

# See detailed update instructions
python3 scripts/update_diagrams.py

# Or just ask Claude Code:
# "Update the architecture diagram based on my recent changes.
#  Use the context in scripts/.diagram_update_context.json"
```

## Full Documentation

See [docs/diagram-maintenance-guide.md](../docs/diagram-maintenance-guide.md) for:
- Installation instructions
- Usage examples
- CI/CD integration
- Customization options
- Troubleshooting

## Workflow

```
Code Change → Pre-commit Hook → Diagram Agent → Context JSON → You update diagram
                                                               ↓
                                                    Manual edit OR Claude Code OR API
```
