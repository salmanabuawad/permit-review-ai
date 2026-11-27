"""National knowledge in the AI knowledge base: committee documents without a committee"""
from alembic import op
import sqlalchemy as sa

revision = '0029'
down_revision = '0028'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('committee_documents') as b:
        b.alter_column('committee_id', existing_type=sa.String(40), nullable=True)


def downgrade():
    op.execute("DELETE FROM committee_documents WHERE committee_id IS NULL")
    with op.batch_alter_table('committee_documents') as b:
        b.alter_column('committee_id', existing_type=sa.String(40), nullable=False)
