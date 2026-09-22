"""Create flags and per-user overrides."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "flags",
        sa.Column("name", sa.String(100), primary_key=True),
        sa.Column("description", sa.String(1000), nullable=False),
        sa.Column("default_enabled", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "user_overrides",
        sa.Column(
            "flag_name",
            sa.String(100),
            sa.ForeignKey("flags.name", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("user_id", sa.String(128), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
    )


def downgrade():
    op.drop_table("user_overrides")
    op.drop_table("flags")
