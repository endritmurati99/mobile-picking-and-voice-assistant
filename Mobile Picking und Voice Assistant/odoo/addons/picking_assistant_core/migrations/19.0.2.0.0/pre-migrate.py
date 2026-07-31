"""Add the principal scope before the ORM sees the new constraint.

Idempotent on purpose: an update that is re-run must not fail, and rows written
before the scope existed keep working -- they are back-filled with the sentinel
`legacy`, which `api_reserve_request` refuses as an input, so such a row can
never be mistaken for a scoped reservation.
"""


def migrate(cr, version):
    cr.execute(
        """
        ALTER TABLE picking_assistant_idempotency
        ADD COLUMN IF NOT EXISTS principal_scope varchar
        """
    )
    cr.execute(
        """
        UPDATE picking_assistant_idempotency
           SET principal_scope = 'legacy'
         WHERE principal_scope IS NULL OR principal_scope = ''
        """
    )
    # The old two-column unique index would reject the very rows the new
    # three-column one allows, so it must go in the SAME pre-migration.
    cr.execute(
        """
        ALTER TABLE picking_assistant_idempotency
        DROP CONSTRAINT IF EXISTS picking_assistant_idempotency_key_unique
        """
    )
