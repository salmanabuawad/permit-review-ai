"""Committee roles reduced to administrator and reviewer: former professional roles become reviewer, the committee's
application editors become end users (same permissions they had); workflow steps addressed to old roles go to reviewers"""
import json

from alembic import op
import sqlalchemy as sa

revision = '0027'
down_revision = '0026'
branch_labels = None
depends_on = None

TO_REVIEWER = ('city_engineer', 'dept_manager', 'secretariat', 'inspector', 'external')


def upgrade():
    b = op.get_bind()
    roles = ", ".join(f"'{r}'" for r in TO_REVIEWER)
    b.execute(sa.text(f"UPDATE users SET role = 'reviewer' WHERE role IN ({roles})"))
    b.execute(sa.text("UPDATE users SET role = 'end_user' WHERE role = 'planner'"))
    b.execute(sa.text(f"UPDATE workflow_tasks SET role = 'reviewer' WHERE role IN ({roles}, 'planner')"))
    for tid, steps in b.execute(sa.text("SELECT id, steps FROM workflow_templates")).all():
        steps = json.loads(steps) if isinstance(steps, str) else steps
        if not isinstance(steps, list):
            continue
        new = [{**st, "role": "reviewer"} if isinstance(st, dict) and st.get("role") in TO_REVIEWER + ("planner",) else st for st in steps]
        if new != steps:
            b.execute(sa.text("UPDATE workflow_templates SET steps = :s WHERE id = :i"), {"s": json.dumps(new, ensure_ascii=False), "i": tid})


def downgrade():
    pass            # the former roles' boundaries are not recoverable from the data
