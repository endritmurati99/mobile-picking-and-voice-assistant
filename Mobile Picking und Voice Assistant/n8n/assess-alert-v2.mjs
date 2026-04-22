/**
 * V2 Quality Alert Assessment — weighted scoring heuristic.
 *
 * Extracted from the n8n "Assess Alert" function node so it can be
 * unit-tested outside of n8n.  The n8n node embeds a copy of this
 * logic; keep both in sync.
 */

const CATALOG = {
  scrap: [
    ['totalschaden',10],['zerstoert',10],['zerbrochen',9],['bruch',8],['gebrochen',8],
    ['eingedrueckt',7],['explodiert',10],['durchgebrochen',9],['gesplittert',8],['zerquetscht',9],
  ],
  quarantine: [
    ['defekt',6],['gerissen',6],['feucht',5],['nass',5],['beschaedigt',5],
    ['offen',4],['schimmel',7],['rost',6],['undicht',5],['verformt',5],
    ['kontaminiert',7],['fremdkoerper',6],['locker',4],['abgeloest',5],
  ],
  rework: [
    ['kratzer',3],['etikett',3],['verpackung',2],['kleber',2],['nacharbeit',3],
    ['delle',3],['verfaerbt',3],['verschmutzt',2],['falsch etikettiert',4],
    ['schief',2],['lose',2],['abgerieben',3],
  ],
};

const NEGATIONS = /\b(nicht|kein|keine|ohne|kaum|weder)\b/g;

const ACTIONS = {
  scrap:      'Ware sperren, aussondern und Schichtleitung informieren.',
  quarantine: 'Ware sperren und manuelle Prüfung anfordern.',
  rework:     'Nacharbeit prüfen und Verpackung korrigieren.',
  sellable:   'Sichtprüfung durch Qualitätsteam.',
};

export function assessAlert({ description = '', priority = '0', photo_count = 0 }) {
  const descLower = description.trim().toLowerCase();
  const photoCount = Number(photo_count || 0);

  // Normalise umlauts so "beschädigt" matches catalog entry "beschaedigt"
  let cleaned = descLower
    .replace(/ä/g, 'ae').replace(/ö/g, 'oe')
    .replace(/ü/g, 'ue').replace(/ß/g, 'ss');

  // Strip negation + the next word only (up to 15 chars after the negation)
  const negPattern = /\b(nicht|kein|keine|ohne|kaum|weder)\s+\S+/g;
  cleaned = cleaned.replace(negPattern, '');

  // Score per category
  const scores = { scrap: 0, quarantine: 0, rework: 0 };
  let totalMatches = 0;
  let maxPossible = 0;
  for (const [cat, keywords] of Object.entries(CATALOG)) {
    for (const [word, weight] of keywords) {
      maxPossible += weight;
      if (cleaned.includes(word)) {
        scores[cat] += weight;
        totalMatches++;
      }
    }
  }

  // Priority multiplier (Odoo only has '0' normal and '1' urgent)
  if (priority === '1') {
    scores.quarantine += 4;
    scores.scrap += 2;
  }

  // Photos raise severity
  if (photoCount > 0) scores.quarantine += 3;
  if (photoCount > 2) scores.scrap += 2;

  // Determine disposition — pick the category with the highest score
  const topScore = Math.max(scores.scrap, scores.quarantine, scores.rework);
  let disposition = 'sellable';
  if (topScore >= 3) {
    if (scores.scrap >= scores.quarantine && scores.scrap >= scores.rework) disposition = 'scrap';
    else if (scores.quarantine >= scores.rework) disposition = 'quarantine';
    else disposition = 'rework';
  }

  // Dynamic confidence — scale by top score relative to a practical ceiling (not maxPossible)
  const descLen = description.trim().length;
  const lenFactor = descLen < 10 ? 0.7 : descLen < 30 ? 0.85 : 1.0;
  const matchFactor = totalMatches === 0 ? 0.5 : Math.min(1.0, 0.6 + totalMatches * 0.1);
  const PRACTICAL_CEILING = 25; // a description rarely scores above this
  let confidence;
  if (disposition === 'sellable') {
    confidence = Math.round(Math.min(0.65, 0.4 + matchFactor * 0.2) * lenFactor * 100) / 100;
  } else {
    const scoreFactor = Math.min(1.0, topScore / PRACTICAL_CEILING);
    confidence = Math.round(Math.min(0.95, 0.5 + scoreFactor * 0.45) * lenFactor * matchFactor * 100) / 100;
  }
  confidence = Math.max(0.1, Math.min(0.95, confidence));

  return {
    disposition,
    confidence,
    scores: { ...scores },
    totalMatches,
    topScore,
    action: ACTIONS[disposition],
  };
}
