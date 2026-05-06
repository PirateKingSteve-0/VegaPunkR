"""add peak/trough price to positions for trailing stops

Revision ID: b8d4f1e2c5a6
Revises: a7f2b9c4e1d3
Create Date: 2026-05-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8d4f1e2c5a6'
down_revision: Union[str, Sequence[str], None] = 'a7f2b9c4e1d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('positions', sa.Column('peak_price', sa.Float(), nullable=True))
    op.add_column('positions', sa.Column('trough_price', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('positions', 'trough_price')
    op.drop_column('positions', 'peak_price')
