#!/usr/bin/env python3
"""
Mermaid Diagram Syntax Validator
Checks for common syntax errors that prevent Mermaid diagrams from rendering.
"""

import re
import sys
from pathlib import Path
from typing import List, Dict, Tuple


class MermaidValidator:
    """Validates Mermaid diagram syntax and suggests fixes."""

    # Patterns that cause syntax errors in different diagram types
    # Note: These are ordered by severity and specificity
    GRAPH_EDGE_LABEL_ISSUES = [
        (r'\|[^|]*\([^)]*\)[^|]*\|', 'Parentheses in edge labels',
         'Remove () from labels like |start_strategy()| → |start strategy|'),
        (r'\|[^|<]*\/[^|<]*\|', 'Forward slashes in edge labels (not in br tag)',
         'Replace / with words: |R/W| → |Read Write|, |start/stop| → |start stop|'),
        (r'\|[^|]*:\s*"[^"]*"[^|]*\|', 'Colons with quotes in edge labels',
         'Remove colons and quotes: |env: "dev"| → |env dev|'),
        (r'\|[^|]*=[^|]*\|', 'Equals signs in edge labels',
         'Remove equals: |APP_ENV=prod| → |APP_ENV prod|'),
        (r'\|[^|<]*\.(?!\.)[a-z_]+[^|]*\|', 'Method calls with dots in edge labels',
         'Remove dots from method calls: |queue.get| → |queue get|'),
    ]

    NODE_LABEL_ISSUES = [
        (r'\[[^\]]*\|[^\]]*\]', 'Pipe characters in node labels',
         'Replace | with space: [trade|quote] → [trade quote]'),
    ]

    STATE_DIAGRAM_ISSUES = [
        (r'-->\s*\w+:\s*[^<\n]*:[^<\n]*<br/>', 'Multiple colons in state transition',
         'Remove extra colons: Status:<br/>pending → Status<br/>pending'),
        (r'-->\s*\w+:\s*[^<\n]*/[^<\n]*<br/>', 'Slashes in state transitions',
         'Replace / with words: (TP/SL/Trail) → TP SL Trail'),
    ]

    def __init__(self):
        self.errors = []
        self.warnings = []

    def validate_file(self, file_path: Path) -> Tuple[List[Dict], List[Dict]]:
        """
        Validate all Mermaid diagrams in a file.
        Returns: (errors, warnings)
        """
        self.errors = []
        self.warnings = []

        if not file_path.exists():
            self.errors.append({
                'file': str(file_path),
                'line': 0,
                'issue': 'File not found',
                'suggestion': f'Create the file: {file_path}'
            })
            return self.errors, self.warnings

        content = file_path.read_text()
        diagrams = self._extract_diagrams(content)

        for diagram_type, diagram_content, start_line in diagrams:
            self._validate_diagram(diagram_type, diagram_content, start_line, str(file_path))

        return self.errors, self.warnings

    def _extract_diagrams(self, content: str) -> List[Tuple[str, str, int]]:
        """Extract all Mermaid code blocks from markdown content."""
        diagrams = []
        lines = content.split('\n')
        in_mermaid = False
        diagram_lines = []
        diagram_type = None
        start_line = 0

        for i, line in enumerate(lines, 1):
            if line.strip() == '```mermaid':
                in_mermaid = True
                diagram_lines = []
                start_line = i + 1
            elif in_mermaid:
                if line.strip() == '```':
                    # End of diagram
                    diagram_content = '\n'.join(diagram_lines)
                    # Detect diagram type
                    if diagram_content.strip().startswith('graph'):
                        diagram_type = 'graph'
                    elif diagram_content.strip().startswith('sequenceDiagram'):
                        diagram_type = 'sequence'
                    elif diagram_content.strip().startswith('stateDiagram'):
                        diagram_type = 'state'
                    elif diagram_content.strip().startswith('erDiagram'):
                        diagram_type = 'er'
                    else:
                        diagram_type = 'unknown'

                    diagrams.append((diagram_type, diagram_content, start_line))
                    in_mermaid = False
                else:
                    diagram_lines.append(line)

        return diagrams

    def _validate_diagram(self, diagram_type: str, content: str, start_line: int, file_path: str):
        """Validate a single diagram."""
        lines = content.split('\n')

        for i, line in enumerate(lines, start_line):
            # Skip comments and empty lines
            if line.strip().startswith('%%') or not line.strip():
                continue

            # Check for issues based on diagram type
            if diagram_type in ['graph', 'flowchart']:
                self._check_graph_syntax(line, i, file_path)
            elif diagram_type == 'state':
                self._check_state_syntax(line, i, file_path)

            # Check node labels (applies to all graph-type diagrams)
            if diagram_type in ['graph', 'flowchart', 'state']:
                self._check_node_labels(line, i, file_path)

    def _check_graph_syntax(self, line: str, line_num: int, file_path: str):
        """Check for graph diagram edge label issues."""
        for pattern, issue, suggestion in self.GRAPH_EDGE_LABEL_ISSUES:
            if re.search(pattern, line):
                self.errors.append({
                    'file': file_path,
                    'line': line_num,
                    'content': line.strip(),
                    'issue': issue,
                    'suggestion': suggestion
                })

    def _check_state_syntax(self, line: str, line_num: int, file_path: str):
        """Check for state diagram transition issues."""
        for pattern, issue, suggestion in self.STATE_DIAGRAM_ISSUES:
            if re.search(pattern, line):
                self.errors.append({
                    'file': file_path,
                    'line': line_num,
                    'content': line.strip(),
                    'issue': issue,
                    'suggestion': suggestion
                })

    def _check_node_labels(self, line: str, line_num: int, file_path: str):
        """Check for node label issues."""
        for pattern, issue, suggestion in self.NODE_LABEL_ISSUES:
            if re.search(pattern, line):
                self.errors.append({
                    'file': file_path,
                    'line': line_num,
                    'content': line.strip(),
                    'issue': issue,
                    'suggestion': suggestion
                })


def format_errors(errors: List[Dict], warnings: List[Dict]) -> str:
    """Format validation results for display."""
    output = []

    if errors:
        output.append("\n" + "="*70)
        output.append("❌ MERMAID SYNTAX ERRORS FOUND")
        output.append("="*70)
        output.append("")

        for i, error in enumerate(errors, 1):
            output.append(f"{i}. Line {error['line']}: {error['issue']}")
            output.append(f"   File: {error['file']}")
            if 'content' in error:
                output.append(f"   Content: {error['content'][:80]}")
            output.append(f"   💡 Fix: {error['suggestion']}")
            output.append("")

    if warnings:
        output.append("\n" + "="*70)
        output.append("⚠️  WARNINGS")
        output.append("="*70)
        output.append("")

        for i, warning in enumerate(warnings, 1):
            output.append(f"{i}. Line {warning['line']}: {warning['issue']}")
            output.append(f"   💡 {warning['suggestion']}")
            output.append("")

    if not errors and not warnings:
        output.append("\n" + "="*70)
        output.append("✅ ALL MERMAID DIAGRAMS ARE VALID!")
        output.append("="*70)
        output.append("")
        output.append("All diagrams should render correctly in:")
        output.append("  - https://mermaid.live/")
        output.append("  - VS Code with Mermaid extension")
        output.append("  - GitHub markdown")
        output.append("")

    return '\n'.join(output)


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Validate Mermaid diagram syntax',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate the architecture diagram
  python scripts/validate_mermaid.py docs/architecture-diagram.md

  # Validate all markdown files with diagrams
  python scripts/validate_mermaid.py docs/*.md

  # Run as pre-commit hook (exit 0 even with errors, just warn)
  python scripts/validate_mermaid.py --warn-only docs/architecture-diagram.md
        """
    )
    parser.add_argument('files', nargs='+', help='Markdown files to validate')
    parser.add_argument('--warn-only', action='store_true',
                        help='Show errors but exit 0 (for pre-commit hook)')
    parser.add_argument('--fix', action='store_true',
                        help='Attempt to auto-fix common issues (experimental)')

    args = parser.parse_args()

    validator = MermaidValidator()
    all_errors = []
    all_warnings = []

    for file_path in args.files:
        path = Path(file_path)
        errors, warnings = validator.validate_file(path)
        all_errors.extend(errors)
        all_warnings.extend(warnings)

    # Display results
    print(format_errors(all_errors, all_warnings))

    # Exit code
    if all_errors:
        if args.warn_only:
            print("Note: Errors found but continuing (--warn-only mode)")
            sys.exit(0)
        else:
            print("Fix the errors above before committing.")
            sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
