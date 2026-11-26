"""Process360 workflow templates and tasks"""
from alembic import op
import sqlalchemy as sa

from app import models  # noqa: F401 — custom column types (models.UTCDateTime)

revision = '0018'
down_revision = '0017'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('workflow_templates',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('tenant_id', sa.String(40), sa.ForeignKey('municipalities.id'), nullable=False),
        sa.Column('name_he', sa.String(200), nullable=False), sa.Column('steps', sa.JSON(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False), sa.Column('created_at', models.UTCDateTime(), nullable=False))
    op.create_index('ix_workflow_templates_tenant_id', 'workflow_templates', ['tenant_id'])
    op.create_table('workflow_tasks',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('tenant_id', sa.String(40), sa.ForeignKey('municipalities.id'), nullable=False),
        sa.Column('case_id', sa.String(32), sa.ForeignKey('permit_cases.id', ondelete='CASCADE'), nullable=False),
        sa.Column('template_id', sa.Integer(), sa.ForeignKey('workflow_templates.id'), nullable=False),
        sa.Column('step_key', sa.String(60), nullable=False), sa.Column('name_he', sa.String(200), nullable=False),
        sa.Column('role', sa.String(40), nullable=False), sa.Column('depends_on', sa.JSON(), nullable=False),
        sa.Column('decision', sa.Boolean(), nullable=False), sa.Column('sla_days', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False), sa.Column('assignee', sa.String(40)),
        sa.Column('ready_at', models.UTCDateTime()), sa.Column('started_at', models.UTCDateTime()),
        sa.Column('due_at', models.UTCDateTime()), sa.Column('done_at', models.UTCDateTime()),
        sa.Column('done_by', sa.String(40)), sa.Column('note', sa.Text()))
    op.create_index('ix_workflow_tasks_tenant_id', 'workflow_tasks', ['tenant_id'])
    op.create_index('ix_workflow_tasks_case_id', 'workflow_tasks', ['case_id'])


def downgrade():
    op.drop_table('workflow_tasks')
    op.drop_table('workflow_templates')
