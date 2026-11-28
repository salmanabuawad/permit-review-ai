"""OCR of scanned knowledge PDFs: pages read so far per committee snapshot"""
from alembic import op
import sqlalchemy as sa

revision = '0030'
down_revision = '0029'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('committee_snapshots') as b:
        b.add_column(sa.Column('ocr_pages', sa.Integer(), nullable=True))


def downgrade():
    op.execute("UPDATE committee_snapshots SET text_status = 'empty' WHERE text_status = 'ocr'")
    with op.batch_alter_table('committee_snapshots') as b:
        b.drop_column('ocr_pages')
