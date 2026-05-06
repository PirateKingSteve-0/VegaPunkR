"""add fees to trades and performance_metrics

Revision ID: a7f2b9c4e1d3
Revises: 1c3159917f07
Create Date: 2026-05-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7f2b9c4e1d3'
down_revision: Union[str, Sequence[str], None] = '1c3159917f07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('trades', sa.Column('fees', sa.Float(), nullable=True, server_default='0.0'))
    op.add_column('performance_metrics', sa.Column('total_fees', sa.Float(), nullable=True, server_default='0.0'))


def downgrade() -> None:
    op.drop_column('performance_metrics', 'total_fees')
    op.drop_column('trades', 'fees')
