"""reference data: roles and single-row settings (safe for production — no accounts)

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO role (code, display_name) VALUES
          ('STUDENT', 'Student'), ('PROFESSOR', 'Professor'), ('HOD', 'Head of Department'),
          ('PRINCIPAL', 'Principal'), ('ADMIN', 'Administrator')
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        "INSERT INTO institutional_timetable_settings (settings_id, version) VALUES (1, 1) ON CONFLICT DO NOTHING"
    )
    # Week start, lunch boundary and working hours are intentionally NOT set (not assumed).
    op.execute(
        "INSERT INTO institution_config (config_id, next_class_lookahead_days) VALUES (1, 7) ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM institution_config WHERE config_id = 1")
    op.execute("DELETE FROM institutional_timetable_settings WHERE settings_id = 1")
    op.execute("DELETE FROM role WHERE code IN ('STUDENT','PROFESSOR','HOD','PRINCIPAL','ADMIN')")
