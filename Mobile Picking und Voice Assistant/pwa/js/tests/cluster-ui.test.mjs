import test from 'node:test';
import assert from 'node:assert/strict';

import { buildClusterStops, resolveClusterScan } from '../ui.js';

const line = (overrides = {}) => ({
    id: 1,
    picking_id: 10,
    box_index: 1,
    product_id: 5,
    product_name: 'Brick 2x2 blau',
    location_src: 'WH/Stock/Regal B-01',
    tracking: 'none',
    quantity_demand: 2,
    picked: false,
    ...overrides,
});

test('buildClusterStops bundles one untracked product at one location across orders', () => {
    const stops = buildClusterStops([
        line(),
        line({ id: 2, picking_id: 20, box_index: 2 }),
    ]);

    assert.equal(stops.length, 1);
    assert.equal(stops[0].quantity_demand, 4);
    assert.equal(stops[0].quantity_remaining, 4);
    assert.equal(stops[0].stop_key, JSON.stringify(['5', 'WH/Stock/Regal B-01']));
    assert.deepEqual(stops[0].allocations.map((item) => item.id), [1, 2]);
});

test('buildClusterStops keeps the total and marks completed box allocations', () => {
    const initialStops = buildClusterStops([
        line({ id: 1, picking_id: 10, box_index: 1 }),
        line({ id: 2, picking_id: 20, box_index: 2 }),
    ]);
    const progressedStops = buildClusterStops([
        line({ id: 2, picking_id: 20, box_index: 2 }),
        line({ id: 1, picking_id: 10, box_index: 1, picked: true }),
    ]);

    assert.equal(progressedStops[0].quantity_demand, 4);
    assert.equal(progressedStops[0].quantity_done, 2);
    assert.equal(progressedStops[0].quantity_remaining, 2);
    assert.equal(progressedStops[0].stop_key, initialStops[0].stop_key);
    assert.deepEqual(progressedStops[0].allocations.map((item) => item.box_index), [1, 2]);
});

test('buildClusterStops does not bundle tracked, split, or differently located lines', () => {
    const trackedStops = buildClusterStops([
        line({ tracking: 'serial' }),
        line({ id: 2, picking_id: 20, box_index: 2, tracking: 'serial' }),
    ]);
    assert.equal(trackedStops.length, 2);
    assert.deepEqual(trackedStops.map((stop) => stop.stop_key), ['line:1', 'line:2']);

    const lotStops = buildClusterStops([
        line({ tracking: 'lot' }),
        line({ id: 2, picking_id: 20, box_index: 2, tracking: 'lot' }),
    ]);
    assert.equal(lotStops.length, 2);
    assert.deepEqual(lotStops.map((stop) => stop.stop_key), ['line:1', 'line:2']);

    const splitStops = buildClusterStops([
        line(),
        line({ id: 2 }),
    ]);
    assert.equal(splitStops.length, 2);
    assert.deepEqual(splitStops.map((stop) => stop.stop_key), ['line:1', 'line:2']);

    const locationStops = buildClusterStops([
        line(),
        line({ id: 2, picking_id: 20, box_index: 2, location_src: 'WH/Stock/Regal B-02' }),
    ]);
    assert.equal(locationStops.length, 2);
    assert.deepEqual(locationStops.map((stop) => stop.stop_key), ['line:1', 'line:2']);
});

test('resolveClusterScan verifies a trimmed, exact product barcode', () => {
    const stop = line({ product_barcode: '4006381333931' });

    assert.deepEqual(resolveClusterScan(stop, '  4006381333931  '), {
        kind: 'product_ok',
        barcode: '4006381333931',
    });
    assert.deepEqual(resolveClusterScan(stop, '4006381333932'), { kind: 'wrong_product' });
    assert.deepEqual(
        resolveClusterScan(line({ product_barcode: '  ' }), '4006381333931'),
        { kind: 'product_missing' },
    );
});

test('resolveClusterScan selects either open package allocation', () => {
    const firstAllocation = line({
        id: 1,
        package_id: 70,
        package_name: 'CLUSTER-BOX-A',
    });
    const secondAllocation = line({
        id: 2,
        picking_id: 20,
        package_id: 71,
        package_name: 'CLUSTER-BOX-B',
    });
    const stop = line({
        product_barcode: '4006381333931',
        allocations: [firstAllocation, secondAllocation],
    });

    assert.deepEqual(resolveClusterScan(stop, ' cluster-box-a ', '4006381333931'), {
        kind: 'allocation_ok',
        allocation: firstAllocation,
        scanned_package: 'cluster-box-a',
    });
    assert.deepEqual(resolveClusterScan(stop, ' 71 ', '4006381333931'), {
        kind: 'allocation_ok',
        allocation: secondAllocation,
        scanned_package: '71',
    });
});

test('resolveClusterScan ignores completed allocations and rejects wrong or duplicate boxes', () => {
    const stop = line({
        product_barcode: '4006381333931',
        allocations: [
            line({ package_id: 70, package_name: 'CLUSTER-BOX-A', picked: true }),
            line({ id: 2, picking_id: 20, package_id: 71, package_name: 'CLUSTER-BOX-B' }),
        ],
    });

    assert.deepEqual(resolveClusterScan(stop, 'CLUSTER-BOX-A', '4006381333931'), { kind: 'wrong_package' });
    assert.deepEqual(resolveClusterScan(stop, 'CLUSTER-BOX-X', '4006381333931'), { kind: 'wrong_package' });
    assert.deepEqual(resolveClusterScan(stop, '4006381333931', '4006381333931'), {
        kind: 'product_already_ok',
    });
});

test('resolveClusterScan leaves tracked products in their atomic flow', () => {
    assert.deepEqual(
        resolveClusterScan(line({ tracking: 'serial', product_barcode: 'SERIAL-PRODUCT' }), 'SERIAL-PRODUCT'),
        { kind: 'tracked' },
    );
    assert.deepEqual(
        resolveClusterScan(line({ tracking: 'lot', product_barcode: '' }), 'LOT-1'),
        { kind: 'tracked' },
    );
});
