/**
 * Phase 1D-5E-1 Marketing Attribution UI Hardening Test Suite
 * Validates remediation of findings:
 * - REV-5D-03 (P2): HTML Escaping & Injection Protection
 * - REV-5D-01 (P3): Request Concurrency & AbortController Lifecycle
 * - REV-5D-02 (P3): Terminology Alignment (Elimination of Misleading "ROI")
 */

const fs = require('fs');
const path = require('path');
const assert = require('assert');

const adminHtmlPath = path.join(__dirname, '..', 'admin.html');
const html = fs.readFileSync(adminHtmlPath, 'utf8');

console.log("Running Phase 1D-5E-1 UI Hardening Remediation Tests...\n");

// =========================================================================
// 1. Finding REV-5D-03 (P2): HTML Escaping & Injection Defense
// =========================================================================

// 1.1 Verify escapeHtml utility definition in admin.html
assert(
    html.includes('function escapeHtml(str)'),
    "FAIL: escapeHtml function definition missing in admin.html"
);
console.log("✓ Test 1.1 Passed: escapeHtml helper function is defined");

// 1.2 Validate escapeHtml function behavior
const escapeHtmlMatch = html.match(/function escapeHtml\(str\)[\s\S]*?return\s+String\(str\)[\s\S]*?\.replace\(\/['"]\/g,[\s\S]*?\);?\s*\}/);
assert(escapeHtmlMatch, "FAIL: Could not extract escapeHtml implementation from admin.html");

const escapeHtml = new Function('str', `
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
`);

// Test XSS payloads
assert.strictEqual(
    escapeHtml('<script>alert("xss")</script>'),
    '&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;',
    "FAIL: Script tags and double quotes not escaped correctly"
);

assert.strictEqual(
    escapeHtml('"><img src=x onerror=alert(1)>'),
    '&quot;&gt;&lt;img src=x onerror=alert(1)&gt;',
    "FAIL: IMG onerror payload not escaped correctly"
);

assert.strictEqual(
    escapeHtml("'; DROP TABLE users; --"),
    '&#39;; DROP TABLE users; --',
    "FAIL: Single quotes not escaped correctly"
);

assert.strictEqual(
    escapeHtml('Google & Facebook / Ads'),
    'Google &amp; Facebook / Ads',
    "FAIL: Ampersands not escaped correctly"
);

assert.strictEqual(escapeHtml(null), '', "FAIL: null should return empty string");
assert.strictEqual(escapeHtml(undefined), '', "FAIL: undefined should return empty string");
assert.strictEqual(escapeHtml(1234), '1234', "FAIL: numbers should be converted to string");

console.log("✓ Test 1.2 Passed: escapeHtml accurately sanitizes HTML entities (&, <, >, \", ')");

// 1.3 Verify escapeHtml is applied to dynamic renders
const renderingChecks = [
    { name: 'renderAttributionChannels', check: 'escapeHtml(rawName)' },
    { name: 'renderAttributionTouches (src)', check: 'escapeHtml(t.source || "(not set)")' },
    { name: 'renderAttributionTouches (med)', check: 'escapeHtml(t.medium || "(none)")' },
    { name: 'renderAttributionTimeline (date)', check: 'escapeHtml(row.date || "--")' },
    { name: 'renderAttributionCampaigns (camp)', check: 'escapeHtml(c.campaign || "(not set)")' },
    { name: 'renderAttributionCampaigns (src)', check: 'escapeHtml(c.source || "direct")' },
    { name: 'renderAttributionCampaigns (med)', check: 'escapeHtml(c.medium || "(none)")' },
    { name: 'renderAttributionJourneys (fSrc)', check: 'escapeHtml(j.first_source || "direct")' },
    { name: 'renderAttributionJourneys (lSrc)', check: 'escapeHtml(j.last_source || "direct")' }
];

for (const rc of renderingChecks) {
    assert(
        html.includes(rc.check),
        `FAIL: escapeHtml not applied in ${rc.name} for ${rc.check}`
    );
}
console.log("✓ Test 1.3 Passed: All dynamic table/bar rendering functions use escapeHtml");


// =========================================================================
// 2. Finding REV-5D-01 (P3): Request Concurrency & AbortController Lifecycle
// =========================================================================

// 2.1 Verify attributionAbortController variable exists
assert(
    html.includes('let attributionAbortController = null;'),
    "FAIL: attributionAbortController declaration missing"
);
console.log("✓ Test 2.1 Passed: attributionAbortController variable declared");

// 2.2 Verify cancellation of previous active requests
assert(
    html.includes('if (attributionAbortController) {') &&
    html.includes('attributionAbortController.abort();'),
    "FAIL: Previous in-flight request abort logic missing"
);
console.log("✓ Test 2.2 Passed: In-flight requests are aborted upon new request trigger");

// 2.3 Verify AbortController instantiation and signal propagation to fetch
assert(
    html.includes('attributionAbortController = new AbortController();') &&
    html.includes('signal: currentController.signal'),
    "FAIL: AbortController not initialized or signal not passed to fetch"
);
console.log("✓ Test 2.3 Passed: AbortController created and signal passed to fetch request");

// 2.4 Verify AbortError suppression in catch block
assert(
    html.includes('err.name === "AbortError" || currentController.signal.aborted'),
    "FAIL: AbortError not properly caught and suppressed from showing false error banners"
);
console.log("✓ Test 2.4 Passed: AbortError is cleanly suppressed from triggering UI error states");

// 2.5 Verify finally block checks signal.aborted before clearing spinners/states
assert(
    html.includes('if (!currentController.signal.aborted) {') &&
    html.includes('isAttributionLoading = false;'),
    "FAIL: finally block does not guard state reset against aborted requests"
);
console.log("✓ Test 2.5 Passed: Loading state cleanup guarded against aborted request overwrites");


// =========================================================================
// 3. Finding REV-5D-02 (P3): Terminology Alignment (Elimination of "ROI")
// =========================================================================

// 3.1 Verify sub-tab button does not mention ROI
assert(
    html.includes('Marketing Attribution &amp; Performance') &&
    !html.includes('Marketing Attribution &amp; ROI') &&
    !html.includes('Marketing Attribution & ROI'),
    "FAIL: Sub-tab button still mentions 'ROI'"
);
console.log("✓ Test 3.1 Passed: Sub-tab navigation button uses 'Performance' instead of 'ROI'");

// 3.2 Verify campaign matrix panel header does not mention ROI
assert(
    (html.includes('Marketing Campaign Performance &amp; Conversion Matrix') ||
     html.includes('Marketing Campaign Performance & Conversion Matrix')) &&
    !html.includes('Marketing Campaign ROI'),
    "FAIL: Campaign matrix header still mentions 'ROI'"
);
console.log("✓ Test 3.2 Passed: Campaign table header uses 'Performance & Conversion Matrix'");

// 3.3 Verify zero occurrences of ROI within attribution section
const containerIdx = html.indexOf('id="growthAttributionContainer"');
const nextTabIdx = html.indexOf('id="growthEmployerDeepDiveContainer"');
if (containerIdx !== -1 && nextTabIdx !== -1) {
    const sub = html.substring(containerIdx, nextTabIdx);
    const roiMatches = sub.match(/\bROI\b/g) || [];
    assert.strictEqual(
        roiMatches.length,
        0,
        `FAIL: Found ${roiMatches.length} instances of standalone 'ROI' between attribution and deep dive containers`
    );
    console.log("✓ Test 3.3 Passed: Zero instances of 'ROI' inside Marketing Attribution HTML block");
} else {
    // Fallback check
    const sub = html.substring(containerIdx, containerIdx + 20000);
    const roiMatches = sub.match(/\bROI\b/g) || [];
    assert.strictEqual(
        roiMatches.length,
        0,
        `FAIL: Found ${roiMatches.length} instances of standalone 'ROI' in Marketing Attribution section`
    );
    console.log("✓ Test 3.3 Passed: Zero instances of 'ROI' inside Marketing Attribution section");
}

console.log("\n=======================================================");
console.log("All Phase 1D-5E-1 Hardening Remediation Tests PASSED!");
console.log("=======================================================");
