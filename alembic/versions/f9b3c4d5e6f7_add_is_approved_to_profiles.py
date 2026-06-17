"""Add is_approved column to profiles

Revision ID: f9b3c4d5e6f7
Revises: 3b4a83deaede
Create Date: 2026-06-17 12:47:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f9b3c4d5e6f7'
down_revision: Union[str, None] = '3b4a83deaede'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add the column as nullable first
    op.add_column('profiles', sa.Column('is_approved', sa.Boolean(), nullable=True))

    # Set all existing users to approved so they are not locked out
    op.execute("UPDATE profiles SET is_approved = TRUE")

    # Now make it NOT NULL with a default of FALSE for future signups
    op.alter_column('profiles', 'is_approved', nullable=False, server_default=sa.text('FALSE'))


def downgrade() -> None:
    op.drop_column('profiles', 'is_approved')
