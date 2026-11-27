"""review attestations and the derivation cache (V9)

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-26

Rollback: `alembic downgrade 0004` drops both tables; no existing table is changed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app import models  # noqa: F401 — custom column types (models.UTCDateTime)

revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('review_attestations',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.String(length=40), nullable=False),
    sa.Column('case_id', sa.String(length=32), nullable=False),
    sa.Column('run_id', sa.String(length=32), nullable=False),
    sa.Column('run_version', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.String(length=40), nullable=False),
    sa.Column('role', sa.String(length=40), nullable=False),
    sa.Column('decision', sa.String(length=40), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('digest', sa.String(length=64), nullable=False),
    sa.Column('signature', sa.String(length=64), nullable=False),
    sa.Column('at', models.UTCDateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'))
    with op.batch_alter_table('review_attestations', schema=None) as b:
        b.create_index(b.f('ix_review_attestations_tenant_id'), ['tenant_id'], unique=False)
        b.create_index(b.f('ix_review_attestations_case_id'), ['case_id'], unique=False)
        b.create_index(b.f('ix_review_attestations_run_id'), ['run_id'], unique=False)
    op.create_table('derivation_cache',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('scope', sa.String(length=10), nullable=False),
    sa.Column('algorithm', sa.String(length=80), nullable=False),
    sa.Column('algorithm_version', sa.String(length=40), nullable=False),
    sa.Column('input_sha256', sa.String(length=64), nullable=False),
    sa.Column('jurisdiction', sa.String(length=40), nullable=False),
    sa.Column('revision', sa.String(length=80), nullable=False),
    sa.Column('depends_on', sa.JSON(), nullable=False),
    sa.Column('output', sa.JSON(), nullable=False),
    sa.Column('hits', sa.Integer(), nullable=False),
    sa.Column('created_at', models.UTCDateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('key'))
    with op.batch_alter_table('derivation_cache', schema=None) as b:
        b.create_index(b.f('ix_derivation_cache_input_sha256'), ['input_sha256'], unique=False)


def downgrade() -> None:
    op.drop_table('derivation_cache')
    op.drop_table('review_attestations')
