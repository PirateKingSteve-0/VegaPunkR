"""add account trading window to users

Revision ID: c9e5a73b2f81
Revises: b8d4f1e2c5a6
Create Date: 2026-05-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c9e5a73b2f81'
down_revision: Union[str, Sequence[str], None] = 'b8d4f1e2c5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('trading_window_enabled', sa.Boolean(), nullable=True, server_default=sa.false()))
    op.add_column('users', sa.Column('trading_window_start', sa.String(), nullable=True, server_default='09:45'))
    op.add_column('users', sa.Column('trading_window_end', sa.String(), nullable=True, server_default='15:45'))


def downgrade() -> None:
    op.drop_column('users', 'trading_window_end')
    op.drop_column('users', 'trading_window_start')
    op.drop_column('users', 'trading_window_enabled')
