function jsonResponse(route, status, body) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function createProductImageSvg(productId) {
  const palettes = [
    ['#F59E0B', '#F97316'],
    ['#22C55E', '#14B8A6'],
    ['#38BDF8', '#2563EB'],
    ['#F472B6', '#DB2777'],
  ];
  const [base, shade] = palettes[Math.abs(Number(productId) || 0) % palettes.length];
  return `
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 160" role="img" aria-label="Produktbild">
      <defs>
        <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stop-color="#ffffff"/>
          <stop offset="100%" stop-color="#eef2f7"/>
        </linearGradient>
        <linearGradient id="brick" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stop-color="${base}"/>
          <stop offset="100%" stop-color="${shade}"/>
        </linearGradient>
      </defs>
      <rect width="160" height="160" rx="28" fill="url(#bg)"/>
      <g transform="translate(28 36)">
        <path d="M16 20C16 11.163 23.163 4 32 4H72C80.837 4 88 11.163 88 20V68C88 76.837 80.837 84 72 84H32C23.163 84 16 76.837 16 68Z" fill="url(#brick)"/>
        <rect x="0" y="24" width="104" height="52" rx="20" fill="url(#brick)"/>
        <circle cx="26" cy="24" r="12" fill="${shade}"/>
        <circle cx="52" cy="18" r="12" fill="${shade}"/>
        <circle cx="78" cy="24" r="12" fill="${shade}"/>
      </g>
    </svg>
  `.trim();
}

function createPickingList() {
  return [
    {
      id: 1001,
      name: 'WH/INT/00007',
      reference_code: 'WH/INT/00007',
      kit_name: 'LEGO Ente',
      has_human_context: true,
      primary_product_id: 11,
      primary_item_display: '4x Brick 2x2 orange',
      primary_item_sku: 'BR-22-OR',
      next_location_short: 'L-E1-P1',
      open_line_count: 2,
      total_line_count: 6,
      completed_line_count: 1,
      progress_ratio: 0.1667,
      primary_zone_key: 'lager-links',
      voice_instruction_short: 'L-E1-P1. 4 Stueck. Brick 2x2 orange.',
      partner_id: [7, 'Lager intern'],
      scheduled_date: '2026-03-22T08:30:00',
      state: 'assigned',
      picking_type_id: [5, 'My Company: Internal Transfers'],
      priority: '1',
    },
    {
      id: 1002,
      name: 'WH/INT/00008',
      reference_code: 'WH/INT/00008',
      kit_name: '',
      has_human_context: false,
      primary_product_id: 12,
      primary_item_display: '2x Brick 1x4 blau',
      primary_item_sku: 'BR-14-BL',
      next_location_short: 'L-E2-P4',
      open_line_count: 1,
      total_line_count: 3,
      completed_line_count: 2,
      progress_ratio: 0.6667,
      primary_zone_key: 'lager-rechts',
      voice_instruction_short: 'L-E2-P4. 2 Stueck. Brick 1x4 blau.',
      partner_id: [8, 'Warenausgang'],
      scheduled_date: '2026-03-22T10:00:00',
      state: 'assigned',
      picking_type_id: [5, 'My Company: Internal Transfers'],
      priority: '0',
    },
    {
      id: 1003,
      name: 'WH/INT/00009',
      reference_code: 'WH/INT/00009',
      kit_name: '',
      has_human_context: false,
      primary_product_id: 13,
      primary_item_display: '1x Motorblock',
      primary_item_sku: 'MT-900',
      next_location_short: 'A-12',
      open_line_count: 4,
      total_line_count: 4,
      completed_line_count: 0,
      progress_ratio: 0,
      primary_zone_key: 'halle-a',
      voice_instruction_short: 'A-12. 1 Stueck. Motorblock.',
      partner_id: [9, 'Produktion'],
      scheduled_date: '2026-03-23T07:15:00',
      state: 'assigned',
      picking_type_id: [5, 'My Company: Internal Transfers'],
      priority: '1',
    },
  ];
}

function createPickingDetail() {
  return {
    id: 1001,
    name: 'WH/INT/00007',
    reference_code: 'WH/INT/00007',
    kit_name: 'LEGO Ente',
    voice_intro: 'LEGO Ente. Start an Platz L-E1-P1.',
    has_human_context: true,
    primary_item_display: '4x Brick 2x2 orange',
    primary_item_sku: 'BR-22-OR',
    next_location_short: 'L-E1-P1',
    open_line_count: 2,
    total_line_count: 6,
    completed_line_count: 1,
    progress_ratio: 0.1667,
    primary_zone_key: 'lager-links',
    voice_instruction_short: 'L-E1-P1. 4 Stueck. Brick 2x2 orange.',
    partner_id: [7, 'Lager intern'],
    move_lines: [
      {
        id: 501,
        product_id: 11,
        product_name: 'Brick 2x2 orange',
        product_short_name: 'Brick 2x2 orange',
        product_sku: 'BR-22-OR',
        ui_display: 'Brick 2x2 orange',
        product_barcode: '4006381333931',
        quantity_demand: 4,
        location_src: 'WH/Stock/Lager Links/L-E1-P1',
        location_src_short: 'L-E1-P1',
        location_src_zone: 'Lager Links',
        voice_instruction_short: 'L-E1-P1. 4 Stueck. Brick 2x2 orange.',
      },
      {
        id: 502,
        product_id: 12,
        product_name: 'Brick 2x2 hellgruen',
        product_short_name: 'Brick 2x2 hellgruen',
        product_sku: 'BR-22-GR',
        ui_display: 'Brick 2x2 hellgruen',
        product_barcode: '9780201379624',
        quantity_demand: 3,
        location_src: 'WH/Stock/Lager Rechts/L-E2-P4',
        location_src_short: 'L-E2-P4',
        location_src_zone: 'Lager Rechts',
        voice_instruction_short: 'L-E2-P4. 3 Stueck. Brick 2x2 hellgruen.',
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
      name: 'Administrator',
    },
    {
      id: 18,
      name: 'Endrit Murati',
    },
    {
      id: 19,
      name: 'Max Picker',
    },
  ];
}

async function mockPwaApi(page, options = {}) {
  const pickers = clone(options.pickers || createPickers());
  let pickingsState = clone(options.pickings || createPickingList());
  let detailState = clone(options.detail || createPickingDetail());
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
  let pickingsRequests = 0;
  let detailRequests = 0;

  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const pickerHeader = request.headers()['x-picker-user-id'];
    const activePicker = pickers.find((picker) => String(picker.id) === String(pickerHeader)) || pickers[0];

    if (path === '/api/health' && request.method() === 'GET') {
      return jsonResponse(route, 200, { status: 'ok' });
    }

    if (/^\/api\/products\/\d+\/image$/.test(path) && request.method() === 'GET') {
      const productId = path.split('/')[3];
      return route.fulfill({
        status: 200,
        contentType: 'image/svg+xml',
        body: createProductImageSvg(productId),
      });
    }

    if (path === '/api/pickings' && request.method() === 'GET') {
      if (!pickerHeader) {
        return jsonResponse(route, 400, { detail: 'X-Picker-User-Id ist erforderlich.' });
      }
      pickingsRequests += 1;
      return jsonResponse(route, 200, pickingsState);
    }

    if (path === '/api/pickers' && request.method() === 'GET') {
      return jsonResponse(route, 200, pickers);
    }

    if (path === `/api/pickings/${detailState.id}` && request.method() === 'GET') {
      if (!pickerHeader) {
        return jsonResponse(route, 400, { detail: 'X-Picker-User-Id ist erforderlich.' });
      }
      detailRequests += 1;
      return jsonResponse(route, 200, detailState);
    }

    if (path === `/api/pickings/${detailState.id}/claim` && request.method() === 'POST') {
      return jsonResponse(route, 200, {
        success: true,
        status: 'claimed',
        picking_id: detailState.id,
        claimed_by_user_id: activePicker?.id || 17,
        claimed_by_name: activePicker?.name || 'Max Picker',
        device_id: 'test-device',
        claim_expires_at: '2026-03-24 10:02:00',
      });
    }

    if (path === `/api/pickings/${detailState.id}/heartbeat` && request.method() === 'POST') {
      return jsonResponse(route, 200, {
        success: true,
        status: 'claimed',
        picking_id: detailState.id,
      });
    }

    if (path === `/api/pickings/${detailState.id}/release` && request.method() === 'POST') {
      return jsonResponse(route, 200, {
        success: true,
        status: 'released',
        picking_id: detailState.id,
      });
    }

    if (path === `/api/pickings/${detailState.id}/confirm-line` && request.method() === 'POST') {
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
    getPickingsRequests() {
      return pickingsRequests;
    },
    getDetailRequests() {
      return detailRequests;
    },
    getLastConfirmRequest() {
      return lastConfirmRequest;
    },
    getLastQualityRequest() {
      return lastQualityRequest;
    },
    getPickings() {
      return clone(pickingsState);
    },
    setPickings(nextPickings) {
      pickingsState = clone(typeof nextPickings === 'function' ? nextPickings(clone(pickingsState)) : nextPickings);
      return clone(pickingsState);
    },
    getDetail() {
      return clone(detailState);
    },
    setDetail(nextDetail) {
      detailState = clone(typeof nextDetail === 'function' ? nextDetail(clone(detailState)) : nextDetail);
      return clone(detailState);
    },
  };
}

module.exports = {
  createPickingDetail,
  createPickingList,
  createPickers,
  mockPwaApi,
};
