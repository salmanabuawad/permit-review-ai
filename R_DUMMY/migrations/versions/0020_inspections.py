"""Construction360 site inspections"""
from alembic import op
import sqlalchemy as sa

from app import models  # noqa: F401 — custom column types (models.UTCDateTime)

revision = '0020'
down_revision = '0019'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('inspections',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('tenant_id', sa.String(40), sa.ForeignKey('municipalities.id'), nullable=False),
        sa.Column('case_id', sa.String(32), sa.ForeignKey('permit_cases.id', ondelete='CASCADE'), nullable=False),
        sa.Column('milestone', sa.String(40), nullable=False), sa.Column('scheduled_for', sa.Date()),
        sa.Column('inspector_id', sa.String(40)), sa.Column('status', sa.String(20), nullable=False),
        sa.Column('result', sa.String(20)), sa.Column('observations', sa.JSON(), nullable=False),
        sa.Column('photos', sa.JSON(), nullable=False), sa.Column('notes', sa.Text()),
        sa.Column('done_at', models.UTCDateTime()), sa.Column('created_by', sa.String(40), nullable=False),
        sa.Column('created_at', models.UTCDateTime(), nullable=False))
    op.create_index('ix_inspections_tenant_id', 'inspections', ['tenant_id'])
    op.create_index('ix_inspections_case_id', 'inspections', ['case_id'])


def downgrade():
    op.drop_table('inspections')
