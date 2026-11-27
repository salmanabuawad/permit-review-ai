"""Permit requests submitted from Permit360 Pro projects, with confirmation numbers"""
from alembic import op
import sqlalchemy as sa

from app import models

revision = '0028'
down_revision = '0027'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'submissions',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('confirmation_number', sa.String(30), nullable=False, unique=True),
        sa.Column('project_id', sa.String(32), sa.ForeignKey('permit_cases.id'), nullable=False, unique=True),
        sa.Column('committee_id', sa.String(40), sa.ForeignKey('planning_committees.id')),
        sa.Column('target_tenant_id', sa.String(40)),
        sa.Column('target_case_id', sa.String(32)),
        sa.Column('submitted_by', sa.String(40), nullable=False),
        sa.Column('submitted_at', models.UTCDateTime(), nullable=False),
        sa.Column('snapshot', sa.JSON()),
    )


def downgrade():
    op.drop_table('submissions')
