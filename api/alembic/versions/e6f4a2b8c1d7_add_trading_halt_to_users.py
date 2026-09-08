"""add account-wide trading halt to users

Revision ID: e6f4a2b8c1d7
Revises: d4a1b2c3e8f9
Create Date: 2026-08-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e6f4a2b8c1d7'
down_revision: Union[str, Sequence[str], None] = 'd4a1b2c3e8f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Both nullable with no server_default: NULL is "not halted", which is the
    # correct state for every existing row. A default would halt the account on
    # migration.
    op.add_column('users', sa.Column('trading_halted_on', sa.Date(), nullable=True))
    op.add_column('users', sa.Column('trading_halt_mode', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'trading_halt_mode')
    op.drop_column('users', 'trading_halted_on')
