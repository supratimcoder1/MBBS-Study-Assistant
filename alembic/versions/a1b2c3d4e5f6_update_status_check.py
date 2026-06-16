"""Update status check constraint for document uploads

Revision ID: a1b2c3d4e5f6
Revises: ea1a3304ef3f
Create Date: 2026-06-13 14:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'ea1a3304ef3f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the old check constraint
    op.drop_constraint('status_check', 'document_uploads', type_='check')
    
    # Update existing rows to conform to the new constraint
    op.execute("UPDATE document_uploads SET status = 'extracting_toc' WHERE status = 'extracting'")
    op.execute("UPDATE document_uploads SET status = 'binarising' WHERE status = 'ocr_processing'")
    
    # Create the new check constraint with the expanded statuses
    op.create_check_constraint(
        'status_check', 
        'document_uploads', 
        "status IN ('uploaded', 'detected_digital', 'detected_scanned', 'binarising', 'extracting_ocr', 'extracting_toc', 'building_hierarchy', 'chunking', 'indexing', 'completed', 'failed')"
    )


def downgrade() -> None:
    # Drop the new check constraint
    op.drop_constraint('status_check', 'document_uploads', type_='check')
    
    # Recreate the old check constraint
    op.create_check_constraint(
        'status_check', 
        'document_uploads', 
        "status IN ('uploaded', 'ocr_processing', 'extracting', 'building_hierarchy', 'chunking', 'indexing', 'completed', 'failed')"
    )
