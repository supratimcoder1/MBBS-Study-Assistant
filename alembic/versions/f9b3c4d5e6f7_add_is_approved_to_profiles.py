"""Add is_approved to profiles

Revision ID: f9b3c4d5e6f7
Revises: 3b4a83deaede
Create Date: 2026-06-17 11:20:00.000000

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
    # 1. Add the column as nullable first (to allow existing rows)
    op.add_column('profiles', sa.Column('is_approved', sa.Boolean(), nullable=True, server_default=sa.text('false')))
    
    # 2. Update existing profiles to be approved
    op.execute("UPDATE profiles SET is_approved = true")
    
    # 3. Alter the column to NOT NULL
    op.alter_column('profiles', 'is_approved', existing_type=sa.Boolean(), nullable=False)


def downgrade() -> None:
    op.drop_column('profiles', 'is_approved')
