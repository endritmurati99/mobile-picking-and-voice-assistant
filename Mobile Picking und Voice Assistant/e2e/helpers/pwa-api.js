function jsonResponse(route, status, body) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

function createPickingList() {
  return [
    {
      id: 1001,
      name: 'WH/INT/00007',
      partner_id: [7, 'Lager intern'],
      scheduled_date: '2026-03-22T08:30:00',
      state: 'assigned',
    },
  ];
}

function createPickingDetail() {
  return {
    id: 1001,
    name: 'WH/INT/00007',
    move_lines: [
      {
        id: 501,
        product_id: 11,
        product_name: 'Brick 2x2 orange',
        product_barcode: '4006381333931',
        quantity_demand: 4,
        location_src: 'WH/Stock/Lager Links/L-E1-P1',
      },
      {
        id: 502,
        product_id: 12,
        product_name: 'Brick 2x2 hellgruen',
        product_barcode: '9780201379624',
        quantity_demand: 3,
        location_src: 'WH/Stock/Lager Rechts/L-E2-P4',
      },
    ],
    route_plan: {
      strategy: 'zone-first-shortest-walk',
      total_stops: 2,
      completed_stops: 0,
      remaining_stops: 2,
      estimated_travel_steps: 5,
      next_move_line_id: 501,
      next_location_src: 'WH/Stock/Lager Links/L-E1-P1',
      next_product_name: 'Brick 2x2 orange',
      zone_sequence: ['Lager Links', 'Lager Rechts'],
      stops: [
        {
          sequence: 1,
          move_line_id: 501,
          product_name: 'Brick 2x2 orange',
          location_src: 'WH/Stock/Lager Links/L-E1-P1',
          estimated_steps_from_previous: 0,
        },
        {
          sequence: 2,
          move_line_id: 502,
          product_name: 'Brick 2x2 hellgruen',
          location_src: 'WH/Stock/Lager Rechts/L-E2-P4',
          estimated_steps_from_previous: 5,
        },
      ],
    },
  };
}

function createPickers() {
  return [
    {
      id: 17,
      name: 'Max Picker',
    },
  ];
}

async function mockPwaApi(page, options = {}) {
  const pickers = options.pickers || createPickers();
  const pickings = options.pickings || createPickingList();
  const detail = options.detail || createPickingDetail();
  const confirmResponses = options.confirmResponses || [
    {
      success: true,
      message: 'Zeile bestaetigt',
      picking_complete: false,
    },
    {
      success: true,
      message: 'Auftrag abgeschlossen',
      picking_complete: true,
    },
  ];

  let confirmCalls = 0;
  let lastConfirmRequest = null;
  let lastQualityRequest = null;

  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;

    if (path === '/api/health' && request.method() === 'GET') {
      return jsonResponse(route, 200, { status: 'ok' });
    }

    if (path === '/api/pickings' && request.method() === 'GET') {
      return jsonResponse(route, 200, pickings);
    }

    if (path === '/api/pickers' && request.method() === 'GET') {
      return jsonResponse(route, 200, pickers);
    }

    if (path === `/api/pickings/${detail.id}` && request.method() === 'GET') {
      return jsonResponse(route, 200, detail);
    }

    if (path === `/api/pickings/${detail.id}/claim` && request.method() === 'POST') {
      return jsonResponse(route, 200, {
        success: true,
        status: 'claimed',
        picking_id: detail.id,
        claimed_by_user_id: pickers[0]?.id || 17,
        claimed_by_name: pickers[0]?.name || 'Max Picker',
        device_id: 'test-device',
        claim_expires_at: '2026-03-24 10:02:00',
      });
    }

    if (path === `/api/pickings/${detail.id}/heartbeat` && request.method() === 'POST') {
      return jsonResponse(route, 200, {
        success: true,
        status: 'claimed',
        picking_id: detail.id,
      });
    }

    if (path === `/api/pickings/${detail.id}/release` && request.method() === 'POST') {
      return jsonResponse(route, 200, {
        success: true,
        status: 'released',
        picking_id: detail.id,
      });
    }

    if (path === `/api/pickings/${detail.id}/confirm-line` && request.method() === 'POST') {
      confirmCalls += 1;
      lastConfirmRequest = JSON.parse(request.postData() || '{}');
      const response = confirmResponses[Math.min(confirmCalls - 1, confirmResponses.length - 1)];
      return jsonResponse(route, 200, response);
    }

    if (path === '/api/quality-alerts' && request.method() === 'POST') {
      const headers = request.headers();
      const buffer = request.postDataBuffer();
      lastQualityRequest = {
        contentType: headers['content-type'] || '',
        size: buffer ? buffer.length : 0,
      };
      return jsonResponse(route, 200, {
        alert_id: 42,
        name: 'QA-100',
        photo_count: 0,
      });
    }

    return jsonResponse(route, 404, {
      detail: `${request.method()} ${path} nicht gemockt`,
    });
  });

  return {
    getConfirmCalls() {
      return confirmCalls;
    },
    getLastConfirmRequest() {
      return lastConfirmRequest;
    },
    getLastQualityRequest() {
      return lastQualityRequest;
    },
  };
}

module.exports = {
  createPickingDetail,
  createPickingList,
  createPickers,
  mockPwaApi,
};
