"""add environment and trading mode to users

Revision ID: 015e4a41dc9e
Revises: f3c0b907af67
Create Date: 2025-11-20 11:11:27.972797

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '015e4a41dc9e'
down_revision: Union[str, Sequence[str], None] = 'f3c0b907af67'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add selected_environment and selected_trading_mode columns to users table."""
    # Add selected_environment column (defaults to 'dev')
    op.add_column('users', sa.Column('selected_environment', sa.String(), nullable=True, server_default='dev'))

    # Add selected_trading_mode column (defaults to 'paper')
    op.add_column('users', sa.Column('selected_trading_mode', sa.String(), nullable=True, server_default='paper'))

    # Create indexes for faster queries
    op.create_index(op.f('ix_users_selected_environment'), 'users', ['selected_environment'], unique=False)
    op.create_index(op.f('ix_users_selected_trading_mode'), 'users', ['selected_trading_mode'], unique=False)


def downgrade() -> None:
    """Remove selected_environment and selected_trading_mode columns from users table."""
    # Drop indexes first
    op.drop_index(op.f('ix_users_selected_trading_mode'), table_name='users')
    op.drop_index(op.f('ix_users_selected_environment'), table_name='users')

    # Drop columns
    op.drop_column('users', 'selected_trading_mode')
    op.drop_column('users', 'selected_environment')
