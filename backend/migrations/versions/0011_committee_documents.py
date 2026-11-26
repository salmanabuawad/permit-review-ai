"""committee documents, versions and searchable text (national register knowledge, unverified)"""
from alembic import op
import sqlalchemy as sa

from app import models  # noqa: F401 — custom column types (models.UTCDateTime)

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('committee_documents',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('committee_id', sa.String(40), sa.ForeignKey('planning_committees.id', ondelete='CASCADE'), nullable=False),
        sa.Column('url', sa.String(1000), nullable=False),
        sa.Column('title', sa.String(300)), sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('found_on', sa.String(1000)), sa.Column('status', sa.String(20), nullable=False),
        sa.Column('message', sa.String(300)), sa.Column('http_status', sa.Integer()),
        sa.Column('etag', sa.String(200)), sa.Column('last_modified', sa.String(100)),
        sa.Column('sha256', sa.String(64)), sa.Column('checked_at', models.UTCDateTime()),
        sa.UniqueConstraint('committee_id', 'url'))
    op.create_index('ix_committee_documents_committee_id', 'committee_documents', ['committee_id'])
    op.create_table('committee_snapshots',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('document_id', sa.Integer(), sa.ForeignKey('committee_documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False), sa.Column('content_type', sa.String(120), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False), sa.Column('path', sa.String(300), nullable=False),
        sa.Column('pages', sa.Integer(), nullable=False), sa.Column('text_status', sa.String(20), nullable=False),
        sa.Column('fetched_at', models.UTCDateTime(), nullable=False))
    op.create_index('ix_committee_snapshots_document_id', 'committee_snapshots', ['document_id'])
    op.create_index('ix_committee_snapshots_sha256', 'committee_snapshots', ['sha256'])
    op.create_table('committee_passages',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('snapshot_id', sa.Integer(), sa.ForeignKey('committee_snapshots.id', ondelete='CASCADE'), nullable=False),
        sa.Column('page', sa.Integer(), nullable=False), sa.Column('text_he', sa.Text(), nullable=False))
    op.create_index('ix_committee_passages_snapshot_id', 'committee_passages', ['snapshot_id'])
    if op.get_bind().dialect.name == 'postgresql':      # fast substring search over Hebrew text
        op.execute('CREATE INDEX ix_committee_passages_trgm ON committee_passages USING gin (text_he gin_trgm_ops)')


def downgrade():
    op.drop_table('committee_passages')
    op.drop_table('committee_snapshots')
    op.drop_table('committee_documents')
