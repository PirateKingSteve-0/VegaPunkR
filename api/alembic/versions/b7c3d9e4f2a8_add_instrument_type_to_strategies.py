"""add instrument_type to strategies

The engine decided whether it was sizing OPTIONS or SHARES by string-matching
`strategy_type` for 'option' / '0dte' / 'scalping' (risk_manager.py,
strategy_executor.py). Renaming a strategy to something that misses those words
silently switched it to the share formula: measured on the live account, a $3.00
contract went from 1 contract to 3, because the share formula reads "$3.00" as
$3 rather than $300. The uncapped figure was 202 contracts — $60,600 of options
on a $1,214 account, stopped only by `max_contracts` and the broker's buying
power check.

Stores the fact instead of inferring it from a name.

NULL is deliberate and load-bearing: `Strategy.trades_options` falls back to the
old string match when this is unset, so any row this migration does not touch —
and any row created by an older code path — behaves exactly as it does today.
The upgrade can only make behaviour more correct, never different.

Revision ID: b7c3d9e4f2a8
Revises: a1b2c3d4e5f6
Create Date: 2026-09-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7c3d9e4f2a8'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('strategies', sa.Column('instrument_type', sa.String(), nullable=True))

    # Backfill from the same keywords the engine has been matching on, so the
    # stored value reproduces today's behaviour exactly rather than reclassifying
    # anything. Rows matching nothing stay NULL and keep using the fallback.
    op.execute(
        """
        UPDATE strategies
           SET instrument_type = 'option'
         WHERE lower(coalesce(strategy_type, '')) LIKE '%option%'
            OR lower(coalesce(strategy_type, '')) LIKE '%0dte%'
            OR lower(coalesce(strategy_type, '')) LIKE '%scalping%'
        """
    )


def downgrade() -> None:
    op.drop_column('strategies', 'instrument_type')
