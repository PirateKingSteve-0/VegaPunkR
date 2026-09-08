"""add mfe/mae price to trades so excursion survives position-row reuse

Maximum Favourable / Adverse Excursion — how far a trade went in our favour and
against us before it closed — is already tracked live on `positions.peak_price`
/ `trough_price`. It is not recoverable after the fact: `order_manager` resets
both on every reopen and position rows are REUSED for re-entries, so only a
row's most recent cycle survives.

That cost real data twice in the first live week (2026-09-02 and 09-03): in each
case the earlier trade's peak was overwritten by a re-entry into the same
contract hours later, and the only surviving figure had to carry the whole
argument. See TODO.md E5 and docs/live-test-results-2026-09-02.md F7b.

Written onto the SELL leg, which is the immutable record of a completed round
trip. Nullable: every existing row predates the capture and must stay valid.

Revision ID: a1b2c3d4e5f6
Revises: e6f4a2b8c1d7
Create Date: 2026-09-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'e6f4a2b8c1d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('trades', sa.Column('mfe_price', sa.Float(), nullable=True))
    op.add_column('trades', sa.Column('mae_price', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('trades', 'mae_price')
    op.drop_column('trades', 'mfe_price')
