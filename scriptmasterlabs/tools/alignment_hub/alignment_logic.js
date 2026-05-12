
/**
 * SML Alignment Hub — Perpetual Calendar Engine
 * Handles: Julian/Gregorian offset, 666-day cycle detection, T+35 cluster math
 */

// ─── Julian Calendar ────────────────────────────────────────────────────────

/**
 * Returns the Julian calendar equivalent of a Gregorian date.
 * Current Julian offset from Gregorian: 13 days (valid from 1900 AD onward)
 */
function getJulianDate(gregorianDate = new Date()) {
  const JULIAN_OFFSET_DAYS = 13;
  const offsetMs = JULIAN_OFFSET_DAYS * 24 * 60 * 60 * 1000;
  return new Date(gregorianDate.getTime() - offsetMs);
}

function formatDate(d) {
  return d.toLocaleDateString("en-US", {
    month: "long", day: "numeric", year: "numeric", timeZone: "America/New_York"
  });
}

// ─── 666-Day Cycle Engine ────────────────────────────────────────────────────

const ANCHOR_DATE = new Date("2020-10-14T00:00:00-05:00"); // GME/AMC Oct 2020

function getDaysSinceAnchor(from = new Date()) {
  return Math.floor((from - ANCHOR_DATE) / (1000 * 60 * 60 * 24));
}

function checkCycleCompletion(from = new Date()) {
  const days = getDaysSinceAnchor(from);
  const cycleNum = Math.floor(days / 666);
  const remainder = days % 666;
  const nextIgnition = 666 - remainder;

  return {
    totalDays: days,
    cycleNumber: cycleNum,
    remainder: remainder,
    status: remainder === 0 ? "IGNITION" : "COILING",
    daysToNextIgnition: nextIgnition,
    nextIgnitionDate: new Date(from.getTime() + nextIgnition * 86400000)
  };
}

// ─── T+35 FTD Settlement Math ─────────────────────────────────────────────────

/**
 * Given an FTD date, returns the T+35 settlement deadline.
 * SEC Rule: FTDs must close within 35 calendar days (or 13 trading days for CNS).
 * We use the 35-calendar-day window here.
 */
function getT35Date(ftdDate) {
  const d = new Date(ftdDate);
  d.setDate(d.getDate() + 35);
  return d;
}

/**
 * Checks if today falls within a T+35 cluster window (±2 days of a settlement).
 * Returns cluster metadata for display.
 */
function checkT35Cluster(ftdDates = [], windowDays = 2, today = new Date()) {
  const todayMs = today.getTime();
  const clusters = [];

  for (const ftd of ftdDates) {
    const t35 = getT35Date(ftd);
    const diff = Math.floor((t35 - today) / 86400000);
    if (Math.abs(diff) <= windowDays) {
      clusters.push({
        ftdDate: new Date(ftd).toISOString().split("T")[0],
        settlementDate: t35.toISOString().split("T")[0],
        daysOut: diff,
        status: diff === 0 ? "SETTLEMENT_DAY" : diff > 0 ? `T+35 IN ${diff}d` : `${Math.abs(diff)}d OVERDUE`
      });
    }
  }

  return {
    clusterDetected: clusters.length > 0,
    clusters
  };
}

// ─── Pre-Market Window ────────────────────────────────────────────────────────

/**
 * Returns true if current ET time is within the 4:00 AM pre-market window (4:00–5:30 AM ET).
 */
function isPreMarketWindow(now = new Date()) {
  const etNow = new Date(now.toLocaleString("en-US", { timeZone: "America/New_York" }));
  const h = etNow.getHours();
  const m = etNow.getMinutes();
  const totalMin = h * 60 + m;
  return totalMin >= 240 && totalMin <= 330; // 4:00 AM–5:30 AM ET
}

// ─── Master State Export ──────────────────────────────────────────────────────

function getAlignmentState(ftdDates = []) {
  const now = new Date();
  const gregorian = now;
  const julian = getJulianDate(now);
  const cycle = checkCycleCompletion(now);
  const t35 = checkT35Cluster(ftdDates, 2, now);
  const preMarket = isPreMarketWindow(now);

  return {
    timestamp: now.toISOString(),
    gregorianDate: formatDate(gregorian),
    julianDate: formatDate(julian),
    julianOffset: 13,
    cycle,
    t35,
    preMarket,
    beastMode: cycle.status === "IGNITION" || t35.clusterDetected ? "ENGAGED" : "MONITORING"
  };
}

// ─── Node / Browser export ───────────────────────────────────────────────────
if (typeof module !== "undefined") {
  module.exports = { getJulianDate, checkCycleCompletion, getT35Date, checkT35Cluster, isPreMarketWindow, getAlignmentState, ANCHOR_DATE };
}
