from alembic import op
import sqlalchemy as sa
revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('authority_memberships',
        sa.Column('account_id',sa.String(40),sa.ForeignKey('users.id'),primary_key=True),
        sa.Column('tenant_id',sa.String(40),sa.ForeignKey('municipalities.id'),primary_key=True),
        sa.Column('actor_id',sa.String(40),sa.ForeignKey('users.id'),nullable=False,unique=True))
    op.create_table('candidate_passages',
        sa.Column('id',sa.Integer,primary_key=True,autoincrement=True),
        sa.Column('tenant_id',sa.String(40),sa.ForeignKey('municipalities.id'),nullable=False),
        sa.Column('document_id',sa.Integer,sa.ForeignKey('source_documents.id'),nullable=False),
        sa.Column('snapshot_id',sa.Integer,sa.ForeignKey('source_snapshots.id'),nullable=False),
        sa.Column('page',sa.Integer,nullable=False),sa.Column('text_he',sa.Text,nullable=False))
    op.create_index('ix_candidate_passages_tenant_id','candidate_passages',['tenant_id'])
    op.create_index('ix_candidate_passages_document_id','candidate_passages',['document_id'])

def downgrade():
    op.drop_table('candidate_passages')
    op.drop_table('authority_memberships')
