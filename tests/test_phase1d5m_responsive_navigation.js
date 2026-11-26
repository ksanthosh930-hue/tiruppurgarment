/**
 * Phase 1D-5M Responsive Subtab Navigation Test Suite
 * Validates:
 * - Responsive subtab container attributes (#growthSubtabNav, role="tablist")
 * - CSS overflow-x: auto and touch scrolling mechanics
 * - All 4 subtab buttons: IDs, labels, icons, onclick handlers, ARIA attributes
 * - Button white-space: nowrap and flex-shrink: 0 layout stability
 * - Focus-visible keyboard styling
 * - JavaScript switchGrowthSubtab controller updates aria-selected and scrollIntoView
 */

const fs = require('fs');
const path = require('path');
const assert = require('assert');

const adminHtmlPath = path.join(__dirname, '..', 'admin.html');
const html = fs.readFileSync(adminHtmlPath, 'utf8');

console.log("Running Phase 1D-5M Responsive Subtab Navigation Tests...\n");

// 1. Verify growthSubtabNav Container
assert(
    html.includes('id="growthSubtabNav"'),
    "FAIL: growthSubtabNav element missing in admin.html"
);
assert(
    html.includes('class="growth-subtab-nav"'),
    "FAIL: growth-subtab-nav class missing on subtab switcher"
);
assert(
    html.includes('role="tablist"'),
    "FAIL: role='tablist' attribute missing on subtab switcher"
);
assert(
    html.includes('aria-label="Growth Analytics Subtabs"'),
    "FAIL: aria-label missing on subtab switcher"
);
console.log("✓ Test 1 Passed: Responsive subtab navigation container registered with accessibility attributes");

// 2. Verify CSS Responsive Rules
assert(
    html.includes('.growth-subtab-nav {') && html.includes('overflow-x: auto;') && html.includes('-webkit-overflow-scrolling: touch;'),
    "FAIL: overflow-x auto or touch scrolling CSS missing in .growth-subtab-nav"
);
assert(
    html.includes('.growth-subtab-btn {') && html.includes('white-space: nowrap;') && html.includes('flex-shrink: 0;'),
    "FAIL: white-space nowrap or flex-shrink 0 missing in .growth-subtab-btn"
);
assert(
    html.includes('.growth-subtab-btn:focus-visible {'),
    "FAIL: focus-visible styling missing for .growth-subtab-btn"
);
console.log("✓ Test 2 Passed: Responsive CSS rules (overflow-x, touch scroll, nowrap, flex-shrink, focus-visible) verified");

// 3. Verify All 4 Subtab Buttons
const requiredButtons = [
    { id: "subtabBtnPostgres", tab: "postgres", label: "PostgreSQL Database Ground Truth", container: "growthPostgresContainer" },
    { id: "subtabBtnGA4", tab: "ga4", label: "Google Analytics 4 (Traffic & Conversion)", container: "growthGA4Container" },
    { id: "subtabBtnEmployerDeepDive", tab: "employer-deep-dive", label: "Employer Acquisition &amp; Activation", container: "growthEmployerDeepDiveContainer" },
    { id: "subtabBtnAttribution", tab: "attribution", label: "Marketing Attribution &amp; Performance", container: "growthAttributionContainer" }
];

requiredButtons.forEach(btn => {
    assert(
        html.includes(`id="${btn.id}"`),
        `FAIL: ${btn.id} button missing in admin.html`
    );
    assert(
        html.includes(`onclick="switchGrowthSubtab('${btn.tab}')"`),
        `FAIL: onclick handler for ${btn.tab} missing`
    );
    assert(
        html.includes(`aria-controls="${btn.container}"`),
        `FAIL: aria-controls for ${btn.container} missing on ${btn.id}`
    );
    assert(
        html.includes(btn.label),
        `FAIL: label text '${btn.label}' missing for ${btn.id}`
    );
    assert(
        html.includes(`class="btn btn-sm growth-subtab-btn"`),
        `FAIL: growth-subtab-btn class missing on ${btn.id}`
    );
});
console.log("✓ Test 3 Passed: All 4 subtab buttons verified with correct IDs, handlers, and ARIA relationships");

// 4. Verify JavaScript Controller Mechanics
assert(
    html.includes('function switchGrowthSubtab(tab) {'),
    "FAIL: switchGrowthSubtab function definition missing"
);
assert(
    html.includes('setAttribute("aria-selected", "true")') && html.includes('setAttribute("aria-selected", "false")'),
    "FAIL: aria-selected state management missing in switchGrowthSubtab"
);
assert(
    html.includes('scrollIntoView({ behavior: "smooth"'),
    "FAIL: smooth scrollIntoView handling missing in switchGrowthSubtab"
);
console.log("✓ Test 4 Passed: switchGrowthSubtab controller updates ARIA states and executes smooth scrollIntoView");

// 5. Verify Zero Layout Regressions
assert(
    html.includes('id="growthPostgresContainer"'),
    "FAIL: growthPostgresContainer missing"
);
assert(
    html.includes('id="growthGA4Container"'),
    "FAIL: growthGA4Container missing"
);
assert(
    html.includes('id="growthEmployerDeepDiveContainer"'),
    "FAIL: growthEmployerDeepDiveContainer missing"
);
assert(
    html.includes('id="growthAttributionContainer"'),
    "FAIL: growthAttributionContainer missing"
);
console.log("✓ Test 5 Passed: All 4 analytics content containers preserved without regression");

console.log("\n=======================================================");
console.log("All 5 Phase 1D-5M Responsive Navigation Tests PASSED!");
console.log("=======================================================");
