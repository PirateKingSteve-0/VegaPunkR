#!/usr/bin/env python3
"""
Diagram Update Agent - Manual/Automated Execution
This script reads the context from diagram_agent.py and provides
instructions for updating diagrams.

Usage:
  python scripts/update_diagrams.py              # Show what needs updating
  python scripts/update_diagrams.py --auto       # Auto-update (requires Claude API)
"""

import json
import sys
import argparse
from pathlib import Path


def load_context():
    """Load the diagram update context."""
    context_file = Path(__file__).parent / ".diagram_update_context.json"

    if not context_file.exists():
        print("❌ No diagram update context found.")
        print("   This file is created by the pre-commit hook when relevant files change.")
        return None

    with open(context_file) as f:
        return json.load(f)


def show_manual_instructions(context):
    """Display manual update instructions."""
    print("\n" + "="*70)
    print("📊 ARCHITECTURE DIAGRAM UPDATE GUIDE")
    print("="*70)

    print(f"\n📝 Changed files ({len(context['changed_files'])}):")
    for file in context['changed_files']:
        print(f"   - {file}")

    print(f"\n📊 Affected sections ({len(context['affected_sections'])}):")
    for section in context['affected_sections']:
        print(f"   - {section}")

    print("\n" + "="*70)
    print("🔍 REVIEW CHECKLIST")
    print("="*70)

    section_guidance = {
        "1. High-Level System Architecture": """
        - Check if new routers, services, or integrations were added
        - Update component boxes and connections
        - Verify subgraph organization still makes sense
        """,
        "2. Database Schema & Relationships": """
        - Check models.py for new tables, fields, or relationships
        - Update the ER diagram with any schema changes
        - Verify foreign keys and relationship cardinality
        """,
        "3. Trading Execution Flow": """
        - Review changes to StreamDrivenWorker, StrategyExecutor
        - Update sequence diagram if execution steps changed
        - Check for new risk checks or signal logic
        """,
        "4. Exit Signal Flow": """
        - Review changes to exit signal logic
        - Update if new exit conditions were added
        - Check trailing stop or time-based exit changes
        """,
        "5. Component Dependency Graph": """
        - Add any new modules or services
        - Update dependencies between components
        - Remove deprecated dependencies
        """,
        "6. Multi-Environment Database Routing": """
        - Check database.py for routing logic changes
        - Verify environment selection flow
        """,
        "7. Order Lifecycle State Machine": """
        - Review order_manager.py for new states
        - Check if state transitions changed
        - Update timeout or retry logic
        """,
        "8. WebSocket Stream Architecture": """
        - Check tradier_stream_manager.py changes
        - Update if subscription logic changed
        - Verify reconnection handling
        """,
        "9. Risk Management Hierarchy": """
        - Check risk_manager.py for new risk checks
        - Update the decision tree if validation order changed
        - Add new rejection reasons
        """,
        "10. Frontend Angular Architecture": """
        - Review new pages, services, or components
        - Update component relationships
        - Check for new guards or route changes
        """
    }

    for section in sorted(context['affected_sections']):
        if section in section_guidance:
            print(f"\n{section}:")
            print(section_guidance[section])

    print("\n" + "="*70)
    print("🛠️  HOW TO UPDATE")
    print("="*70)
    print("""
1. Open docs/architecture-diagram.md in your editor

2. For each affected section above, review the changes in the source files

3. Update the Mermaid diagram syntax to reflect the changes

4. Test the diagram renders correctly:
   - Use VS Code with Mermaid extension, OR
   - Use https://mermaid.live/ to preview

5. Commit the updated diagram with your changes
""")

    print("\n" + "="*70)
    print("🤖 AUTOMATED UPDATE (EXPERIMENTAL)")
    print("="*70)
    print("""
To use Claude Code to automatically update the diagrams:

1. Copy the prompt below and paste into Claude Code conversation
2. Claude will analyze the changes and update the diagrams

PROMPT:
-------
""")
    print(context['prompt'])
    print("""
-------

Or run: python scripts/update_diagrams.py --auto
(Requires ANTHROPIC_API_KEY environment variable)
""")

    print("\n" + "="*70 + "\n")


def auto_update(context):
    """Automatically update diagrams using Claude API."""
    try:
        import anthropic
    except ImportError:
        print("❌ anthropic package not installed.")
        print("   Install with: pip install anthropic")
        sys.exit(1)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("❌ ANTHROPIC_API_KEY environment variable not set.")
        sys.exit(1)

    print("\n🤖 Launching diagram update agent...")
    print("   This will analyze your changes and update the diagrams.\n")

    client = anthropic.Anthropic(api_key=api_key)

    # Read current diagram
    diagram_path = Path(__file__).parent.parent / "docs" / "architecture-diagram.md"
    current_diagram = diagram_path.read_text()

    # Read changed files
    file_contents = {}
    for file in context['changed_files']:
        file_path = Path(__file__).parent.parent / file
        if file_path.exists():
            file_contents[file] = file_path.read_text()

    # Create comprehensive prompt
    prompt = f"""{context['prompt']}

CURRENT DIAGRAM:
{current_diagram}

CHANGED FILES:
"""
    for file, content in file_contents.items():
        prompt += f"\n--- {file} ---\n{content}\n"

    # Call Claude API
    print("Calling Claude API...")
    message = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=16000,
        messages=[{
            "role": "user",
            "content": prompt
        }]
    )

    response = message.content[0].text

    print("\n" + "="*70)
    print("🤖 CLAUDE'S ANALYSIS")
    print("="*70)
    print(response)
    print("="*70 + "\n")

    # Ask for confirmation
    confirm = input("Apply these changes? (y/n): ")
    if confirm.lower() == 'y':
        # Extract updated diagram from response
        # (This is a simplified version - you'd want better parsing)
        diagram_path.write_text(response)
        print("✅ Diagram updated successfully!")
    else:
        print("❌ Update cancelled.")


def main():
    parser = argparse.ArgumentParser(description="Update architecture diagrams")
    parser.add_argument("--auto", action="store_true", help="Auto-update using Claude API")
    args = parser.parse_args()

    context = load_context()
    if not context:
        sys.exit(1)

    if args.auto:
        auto_update(context)
    else:
        show_manual_instructions(context)


if __name__ == "__main__":
    main()
