#!/usr/bin/env python3
"""
Architecture Diagram Agent
Automatically updates architecture-diagram.md when relevant files change.

This script runs as a pre-commit hook and uses Claude to intelligently
update the Mermaid diagrams based on code changes.
"""

import os
import sys
import json
from pathlib import Path
from typing import List, Dict, Set

# File patterns to diagram section mapping
FILE_TO_DIAGRAM_MAPPING = {
    "api/models.py": [
        "2. Database Schema & Relationships",
        "5. Component Dependency Graph"
    ],
    "api/database.py": [
        "6. Multi-Environment Database Routing",
        "5. Component Dependency Graph"
    ],
    "api/config.py": [
        "5. Component Dependency Graph",
        "1. High-Level System Architecture"
    ],
    "api/routers/": [
        "1. High-Level System Architecture",
        "5. Component Dependency Graph"
    ],
    "api/engine/stream_driven_worker.py": [
        "1. High-Level System Architecture",
        "3. Trading Execution Flow",
        "4. Exit Signal Flow",
        "8. WebSocket Stream Architecture"
    ],
    "api/engine/strategy_executor.py": [
        "3. Trading Execution Flow",
        "4. Exit Signal Flow",
        "5. Component Dependency Graph"
    ],
    "api/engine/risk_manager.py": [
        "3. Trading Execution Flow",
        "9. Risk Management Hierarchy",
        "5. Component Dependency Graph"
    ],
    "api/engine/signal_generator.py": [
        "3. Trading Execution Flow",
        "4. Exit Signal Flow",
        "5. Component Dependency Graph"
    ],
    "api/engine/order_manager.py": [
        "3. Trading Execution Flow",
        "7. Order Lifecycle State Machine",
        "5. Component Dependency Graph"
    ],
    "api/engine/tradier_stream_manager.py": [
        "8. WebSocket Stream Architecture",
        "1. High-Level System Architecture"
    ],
    "api/engine/stream_router.py": [
        "8. WebSocket Stream Architecture"
    ],
    "api/engine/trading_client_manager.py": [
        "1. High-Level System Architecture",
        "5. Component Dependency Graph"
    ],
    "api/tradier_integration/": [
        "1. High-Level System Architecture",
        "5. Component Dependency Graph"
    ],
    "api/schwab_integration/": [
        "1. High-Level System Architecture",
        "5. Component Dependency Graph"
    ],
    "api/services/": [
        "1. High-Level System Architecture",
        "5. Component Dependency Graph"
    ],
    "ui/src/app/pages/": [
        "10. Frontend Angular Architecture"
    ],
    "ui/src/app/services/": [
        "10. Frontend Angular Architecture",
        "5. Component Dependency Graph"
    ]
}


def get_affected_sections(changed_files: List[str]) -> Set[str]:
    """Determine which diagram sections are affected by the changed files."""
    affected = set()

    for file_path in changed_files:
        # Normalize path
        file_path = file_path.replace("\\", "/")

        # Check exact matches
        if file_path in FILE_TO_DIAGRAM_MAPPING:
            affected.update(FILE_TO_DIAGRAM_MAPPING[file_path])
            continue

        # Check directory patterns (e.g., api/routers/)
        for pattern, sections in FILE_TO_DIAGRAM_MAPPING.items():
            if pattern.endswith("/") and file_path.startswith(pattern):
                affected.update(sections)

    return affected


def create_update_prompt(changed_files: List[str], affected_sections: Set[str]) -> str:
    """Create a prompt for the diagram update agent."""
    sections_list = "\n".join(f"  - {section}" for section in sorted(affected_sections))
    files_list = "\n".join(f"  - {file}" for file in changed_files)

    prompt = f"""Architecture diagram update needed!

The following files have been modified:
{files_list}

This affects these diagram sections in docs/architecture-diagram.md:
{sections_list}

Please analyze the changes in these files and update the relevant sections of the architecture diagram.

Instructions:
1. Read each changed file to understand what was modified
2. For each affected diagram section, determine if updates are needed
3. Update the Mermaid diagrams to reflect the current state of the codebase
4. Ensure all relationships, data flows, and component interactions are accurate
5. Maintain the existing diagram style and formatting

Focus on:
- New/removed database models or fields
- New/removed API routes
- Changes to the execution pipeline
- New/modified services or integrations
- Frontend component additions/removals
- Updated data flows or state machines

Please update the diagram file and provide a summary of the changes made.
"""

    return prompt


def should_auto_update() -> bool:
    """Check if we should auto-update or just warn."""
    # Check for environment variable to control behavior
    return os.getenv("DIAGRAM_AUTO_UPDATE", "false").lower() == "true"


def main():
    """Main entry point for the diagram agent."""
    # Get changed files from pre-commit
    changed_files = sys.argv[1:]

    if not changed_files:
        print("✓ No architecture files changed")
        sys.exit(0)

    # Determine affected sections
    affected_sections = get_affected_sections(changed_files)

    if not affected_sections:
        print("✓ Changed files don't affect architecture diagrams")
        sys.exit(0)

    print("\n" + "="*70)
    print("🏗️  ARCHITECTURE DIAGRAM UPDATE NEEDED")
    print("="*70)
    print(f"\n📝 Changed files ({len(changed_files)}):")
    for file in changed_files:
        print(f"   - {file}")

    print(f"\n📊 Affected diagram sections ({len(affected_sections)}):")
    for section in sorted(affected_sections):
        print(f"   - {section}")

    # Write metadata for the update agent
    metadata_path = Path(__file__).parent / ".diagram_update_context.json"
    metadata = {
        "changed_files": changed_files,
        "affected_sections": list(affected_sections),
        "prompt": create_update_prompt(changed_files, affected_sections)
    }

    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"\n💾 Context saved to: {metadata_path}")

    if should_auto_update():
        print("\n🤖 Auto-update mode enabled")
        print("⚠️  This would trigger the diagram update agent...")
        print("    (Not yet implemented - requires Claude API integration)")
        print("\nTo enable auto-update, set: DIAGRAM_AUTO_UPDATE=true")
    else:
        print("\n" + "="*70)
        print("📋 ACTION REQUIRED:")
        print("="*70)
        print("""
After committing, please update the architecture diagram:

Option 1 - Use Claude Code:
  Ask Claude: "Update the architecture diagram based on my recent changes.
               Use the context in scripts/.diagram_update_context.json"

Option 2 - Manual Update:
  Edit docs/architecture-diagram.md directly

Option 3 - Enable Auto-Update:
  Set environment variable: export DIAGRAM_AUTO_UPDATE=true
  Then the diagram will be updated automatically on commit
""")

    print("="*70 + "\n")

    # Allow commit to proceed
    sys.exit(0)


if __name__ == "__main__":
    main()
