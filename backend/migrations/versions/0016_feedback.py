"""professional feedback records and regression cases"""
from alembic import op
import sqlalchemy as sa

from app import models  # noqa: F401 — custom column types (models.UTCDateTime)

revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('feedback_records',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('tenant_id', sa.String(40), sa.ForeignKey('municipalities.id'), nullable=False),
        sa.Column('finding_id', sa.String(32), nullable=False), sa.Column('run_id', sa.String(32), nullable=False),
        sa.Column('case_id', sa.String(32), nullable=False), sa.Column('rule_id', sa.String(80), nullable=False),
        sa.Column('rule_version', sa.String(20), nullable=False), sa.Column('category', sa.String(40), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False), sa.Column('original', sa.JSON(), nullable=False),
        sa.Column('corrected', sa.JSON(), nullable=False), sa.Column('candidate', sa.JSON(), nullable=False),
        sa.Column('similar', sa.JSON(), nullable=False), sa.Column('status', sa.String(20), nullable=False),
        sa.Column('created_by', sa.String(40), nullable=False), sa.Column('created_at', models.UTCDateTime(), nullable=False),
        sa.Column('decided_by', sa.String(40)), sa.Column('decision_note', sa.Text()))
    op.create_index('ix_feedback_records_tenant_id', 'feedback_records', ['tenant_id'])
    op.create_index('ix_feedback_records_finding_id', 'feedback_records', ['finding_id'])
    op.create_index('ix_feedback_records_rule_id', 'feedback_records', ['rule_id'])
    op.create_table('regression_cases',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('tenant_id', sa.String(40), sa.ForeignKey('municipalities.id'), nullable=False),
        sa.Column('rule_id', sa.String(80), nullable=False), sa.Column('facts', sa.JSON(), nullable=False),
        sa.Column('expect', sa.String(20), nullable=False), sa.Column('feedback_id', sa.String(32), nullable=False),
        sa.Column('created_at', models.UTCDateTime(), nullable=False))
    op.create_index('ix_regression_cases_tenant_id', 'regression_cases', ['tenant_id'])
    op.create_index('ix_regression_cases_rule_id', 'regression_cases', ['rule_id'])


def downgrade():
    op.drop_table('regression_cases')
    op.drop_table('feedback_records')
