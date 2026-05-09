"""add account-wide daily loss limit pct to users

Revision ID: d4a1b2c3e8f9
Revises: c9e5a73b2f81
Create Date: 2026-05-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4a1b2c3e8f9'
down_revision: Union[str, Sequence[str], None] = 'c9e5a73b2f81'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('daily_loss_limit_pct', sa.Float(), nullable=True, server_default='5.0'),
    )


def downgrade() -> None:
    op.drop_column('users', 'daily_loss_limit_pct')
