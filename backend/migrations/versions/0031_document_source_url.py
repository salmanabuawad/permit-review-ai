"""Knowledge uploads keep the official address they came from (e.g. a gov.il BlobFolder PDF) for citations"""
from alembic import op
import sqlalchemy as sa

revision = '0031'
down_revision = '0030'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('committee_documents') as b:
        b.add_column(sa.Column('source_url', sa.String(1000), nullable=True))


def downgrade():
    with op.batch_alter_table('committee_documents') as b:
        b.drop_column('source_url')
