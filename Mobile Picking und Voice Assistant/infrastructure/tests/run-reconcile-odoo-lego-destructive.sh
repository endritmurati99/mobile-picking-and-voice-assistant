#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

suffix="$(date +%s)-$$"
pg_container="pwr-reconcile-pg-$suffix"
pg_alias="pwr-reconcile-pg-$suffix"
odoo_volume="pwr_reconcile_odoo_$suffix"
network="mobilepickingundvoiceassistant_core-net"
fixture="$ROOT/infrastructure/fixtures/lego-catalog-o19.json"
script="$ROOT/infrastructure/scripts/reconcile-odoo-lego.py"
fixture_mount="$(wslpath -w "$fixture")"
addons_mount="$(wslpath -w "$ROOT/odoo/addons")"
pg_image="$(docker inspect "$(docker compose ps -q db)" --format '{{.Config.Image}}')"
odoo_image="$(docker inspect "$(docker compose ps -q odoo)" --format '{{.Config.Image}}')"

cleanup() {
    docker rm -f "$pg_container" >/dev/null 2>&1 || true
    docker volume rm "$odoo_volume" >/dev/null 2>&1 || true
    echo "CLEANUP container=$pg_container volume=$odoo_volume removed"
}
trap cleanup EXIT

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

psql_clone() {
    local database="$1"
    shift
    docker exec -i "$pg_container" psql -v ON_ERROR_STOP=1 -U odoo -d "$database" "$@"
}

state() {
    local database="$1"
    psql_clone "$database" -At -c "
        SELECT md5(jsonb_build_object(
            'products', (SELECT jsonb_agg(to_jsonb(x) ORDER BY x.id) FROM product_product x),
            'templates', (SELECT count(*) FROM product_template),
            'pickings', (SELECT jsonb_agg(to_jsonb(x) ORDER BY x.id) FROM stock_picking x),
            'moves', (SELECT jsonb_agg(to_jsonb(x) ORDER BY x.id) FROM stock_move x),
            'lines', (SELECT jsonb_agg(to_jsonb(x) ORDER BY x.id) FROM stock_move_line x),
            'quants', (SELECT jsonb_agg(to_jsonb(x) ORDER BY x.id) FROM stock_quant x)
        )::text);"
}

run_reconcile() {
    local database="$1"
    local apply="$2"
    local args=()
    if [ "$apply" = apply ]; then
        args+=(--env RECONCILE_ARGS=--apply)
    fi
    docker run --rm -i \
        --network "$network" \
        --env RECONCILE_FIXTURE=/tmp/lego-catalog-o19.json \
        --env HOST="$pg_alias" --env PORT=5432 --env USER=odoo \
        --env PASSWORD=disposable-test \
        "${args[@]}" \
        --mount "type=bind,src=$fixture_mount,dst=/tmp/lego-catalog-o19.json,readonly" \
        --mount "type=bind,src=$addons_mount,dst=/mnt/extra-addons,readonly" \
        --mount "type=volume,src=$odoo_volume,dst=/var/lib/odoo" \
        "$odoo_image" \
        odoo shell --no-http -d "$database" --db_host "$pg_alias" \
        --db_port 5432 --db_user odoo --db_password disposable-test \
        < "$script" 2>&1
}

docker volume create "$odoo_volume" >/dev/null
docker run -d --name "$pg_container" --network "$network" --network-alias "$pg_alias" \
    -e POSTGRES_USER=odoo -e POSTGRES_PASSWORD=disposable-test "$pg_image" >/dev/null

ready=0
for _ in $(seq 1 120); do
    if docker exec "$pg_container" pg_isready -U odoo >/dev/null 2>&1; then
        ready=$((ready + 1))
        [ "$ready" -ge 3 ] && break
    else
        ready=0
    fi
    sleep 0.5
done
docker exec "$pg_container" pg_isready -U odoo >/dev/null 2>&1 \
    || fail "temporary PostgreSQL did not become ready"

for database in masterfischer_o19 lager2_o19; do
    docker exec "$pg_container" createdb -U odoo "$database"
    docker compose exec -T db pg_dump -U odoo --no-owner --no-acl "$database" \
        | psql_clone "$database" >/dev/null
    echo "CLONED $database"
done

# A clone-only trigger corrupts one newly created Lager-2 SKU after INSERT.
# The reconciler must observe it after cache invalidation, fail its exact
# postcondition and roll the entire product/stock mutation back.
psql_clone lager2_o19 >/dev/null <<'SQL'
CREATE FUNCTION pwr_corrupt_reconcile_insert() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.default_code = '173057' THEN
        UPDATE product_product SET barcode = 'ROLLBACK-PROBE' WHERE id = NEW.id;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER pwr_corrupt_reconcile_insert
AFTER INSERT ON product_product
FOR EACH ROW EXECUTE FUNCTION pwr_corrupt_reconcile_insert();
SQL

before_failure="$(state lager2_o19)"
set +e
failure_output="$(run_reconcile lager2_o19 apply)"
failure_status=$?
set -e
[ "$failure_status" -ne 0 ] || fail "forced postcondition failure unexpectedly committed"
if ! echo "$failure_output" | grep -q "postcondition failed"; then
    echo "$failure_output" >&2
    fail "forced run did not fail at the postcondition"
fi
[ "$(state lager2_o19)" = "$before_failure" ] \
    || fail "Lager-2 clone changed despite failed postcondition"
echo "ROLLBACK-PROBE postcondition failure rolled back exactly"

psql_clone lager2_o19 >/dev/null <<'SQL'
DROP TRIGGER pwr_corrupt_reconcile_insert ON product_product;
DROP FUNCTION pwr_corrupt_reconcile_insert();
SQL

for database in lager2_o19 masterfischer_o19; do
    first="$(run_reconcile "$database" apply)"
    echo "$first" | grep -q "COMMIT: exact 47-SKU parity verified" \
        || fail "$database first apply did not verify and commit"
    hashes="$(echo "$first" | grep -o 'protected_history=sha256:[0-9a-f]*' | sort -u | wc -l)"
    [ "$hashes" -eq 1 ] || fail "$database protected history changed during apply"

    parity="$(psql_clone "$database" -At -c "
        SELECT count(*), count(*) FILTER (WHERE pp.active),
               count(*) FILTER (WHERE pt.is_storable),
               count(*) FILTER (WHERE EXISTS (
                   SELECT 1 FROM ir_attachment a
                    WHERE a.res_model = 'product.template' AND a.res_id = pt.id
                      AND a.res_field = 'image_1920'
                      AND (a.store_fname IS NOT NULL OR a.db_datas IS NOT NULL)
               )),
               count(*) FILTER (WHERE pt.ai_reference_description IS NOT NULL)
          FROM product_product pp JOIN product_template pt ON pt.id=pp.product_tmpl_id;")"
    [ "$parity" = "47|47|47|47|19" ] \
        || fail "$database parity mismatch: $parity"

    second="$(run_reconcile "$database" apply)"
    echo "$second" | grep -q "changed=False" \
        || fail "$database second apply was not a no-op"
    echo "$second" | grep -q "delete_products=0 update_products=0 create_products=0" \
        || fail "$database second apply planned mutations"
    echo "APPLY $database parity=$parity; second apply no-op"
done

echo "DESTRUCTIVE CLONE INTEGRATION OK"
