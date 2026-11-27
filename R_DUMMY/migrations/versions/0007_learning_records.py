"""learning records: decided cases loaded to learn from"""
from alembic import op
import sqlalchemy as sa

from app import models  # noqa: F401 — custom column types (models.UTCDateTime)

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'learning_records',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('tenant_id', sa.String(40), sa.ForeignKey('municipalities.id'), nullable=False),
        sa.Column('case_id', sa.String(32), sa.ForeignKey('permit_cases.id', ondelete='CASCADE'), nullable=False),
        sa.Column('decision_id', sa.Integer, sa.ForeignKey('committee_decisions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source_document_id', sa.Integer, sa.ForeignKey('source_documents.id')),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('outcome', sa.String(40), nullable=False),
        sa.Column('reasons', sa.JSON, nullable=False),
        sa.Column('result', sa.JSON, nullable=False),
        sa.Column('created_by', sa.String(40), nullable=False),
        sa.Column('created_at', models.UTCDateTime(timezone=True), nullable=False),
        sa.Column('processed_at', models.UTCDateTime(timezone=True)),
    )
    op.create_index('ix_learning_records_tenant_id', 'learning_records', ['tenant_id'])
    op.create_index('ix_learning_records_case_id', 'learning_records', ['case_id'])


def downgrade():
    op.drop_table('learning_records')
