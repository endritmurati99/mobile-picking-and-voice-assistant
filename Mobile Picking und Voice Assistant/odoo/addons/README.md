# Odoo 19 Addons

This directory contains the Odoo 19 custom addons used by the productive `odoo` service
and by `odoo-lager-2`. It is the **only** addon tree in this repository.

## Porting note (carried over from the deleted `odoo/addons18/README.md`)

Odoo 19 security XML uses `res.groups.privilege`, while Odoo 18 used
`res.groups.category_id`. This is the one substantive difference the v18 port recorded,
and it is kept here so the knowledge survives the deletion of that tree.

## `odoo/addons18/` was deleted

`odoo/addons18/` was removed in the same commit that repointed both `odoo` and
`odoo-lager-2` at this directory — the two moves had to be atomic, or the live
containers would have started with an empty `/mnt/extra-addons`.

The deletion executes frozen decision §3.4's *"or it is deleted"* branch. The tree
remains recoverable from git history (`git show <commit>^:'Mobile Picking und Voice
Assistant/odoo/addons18/...'`).

Deleting it was also the remedy for two standing live-system exposures recorded in the
programme's debt register: the **High**-severity M1 session-revocation hole and the
unfixed `_lock_or_create` throttle defect, both of which production ran for as long as
`addons18/` served the live stack.

## Database isolation

The productive configs `odoo/odoo19.conf` and `odoo/odoo19-lager2.conf` each set
`db_name`, not just `dbfilter`. `dbfilter` is an HTTP-layer filter only; Odoo's cron
master enumerates every database on the cluster regardless of it. See the comments in
those files and `docs/superpowers/plans/2026-07-31-odoo19-cutover.md` §0.0.4, where the
behaviour is recorded from the live stack's own logs.
