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
  };
}

async function mockPwaApi(page, options = {}) {
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

    if (path === `/api/pickings/${detail.id}` && request.method() === 'GET') {
      return jsonResponse(route, 200, detail);
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
  mockPwaApi,
};
