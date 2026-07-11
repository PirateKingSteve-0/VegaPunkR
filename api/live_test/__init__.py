"""Live-trading test harness (Monday 2026-07-13).

Tooling for a controlled real-money test: dated structured logging and a
read-only broker-vs-local monitor. Nothing in this package places or cancels
orders — it only observes. See docs/live-test-plan-2026-07-13.md.

Run the monitor:  python -m live_test            (from the api/ dir)
                  python -m live_test.monitor --env prod --interval 60
"""
