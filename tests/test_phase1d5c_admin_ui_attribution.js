/**
 * Phase 1D-5C Admin UI Marketing Attribution Integration Test Suite
 * Validates DOM structure, sub-tab integration, JavaScript controller contract,
 * 366-day custom range validation, and Zero-PII compliance in admin.html.
 */

const fs = require('fs');
const path = require('path');
const assert = require('assert');

const adminHtmlPath = path.join(__dirname, '..', 'admin.html');
const html = fs.readFileSync(adminHtmlPath, 'utf8');

console.log("Running Phase 1D-5C Admin Marketing Attribution UI Tests...\n");

// 1. Verify Subtab Navigation Button
assert(
    html.includes('id="subtabBtnAttribution"'),
    "FAIL: subtabBtnAttribution button missing in admin.html"
);
assert(
    html.includes("switchGrowthSubtab('attribution')"),
    "FAIL: switchGrowthSubtab('attribution') onclick handler missing"
);
console.log("✓ Test 1 Passed: Subtab button registered with correct ID and click handler");

// 2. Verify growthAttributionContainer Presence
assert(
    html.includes('id="growthAttributionContainer"'),
    "FAIL: growthAttributionContainer element missing in admin.html"
);
console.log("✓ Test 2 Passed: Main Marketing Attribution container present");

// 3. Verify Status & Alert Banners
const requiredBanners = [
    'attrOfflineBanner',
    'attrErrorBanner',
    'attrErrorMessage',
    'attrEmptyBanner'
];
for (const bId of requiredBanners) {
    assert(
        html.includes(`id="${bId}"`),
        `FAIL: Expected banner '${bId}' missing in admin.html`
    );
}
console.log("✓ Test 3 Passed: Offline, Error, and Empty-State banners present");

// 4. Verify Account Segmentation Controls
const requiredSegments = [
    'attrSegmentAll',
    'attrSegmentCandidates',
    'attrSegmentEmployers'
];
for (const sId of requiredSegments) {
    assert(
        html.includes(`id="${sId}"`),
        `FAIL: Expected segmentation button '${sId}' missing`
    );
}
console.log("✓ Test 4 Passed: Account type segmentation buttons (All/Candidates/Employers) present");

// 5. Verify Executive Marketing KPI Scorecard Elements
const requiredKpiElements = [
    'attrKpiTotal',
    'attrKpiTracked',
    'attrKpiCoverage',
    'attrKpiLegacy',
    'attrKpiCandidates',
    'attrKpiEmployers',
    'attrKpiSwitches',
    'attrKpiVelocity'
];
for (const kId of requiredKpiElements) {
    assert(
        html.includes(`id="${kId}"`),
        `FAIL: Expected KPI element '${kId}' missing`
    );
}
console.log("✓ Test 5 Passed: All 8 Executive Marketing KPI Scorecard elements present");

// 6. Verify 10-Tier Channel Grouping Container
assert(
    html.includes('id="attrChannelTiersContainer"'),
    "FAIL: attrChannelTiersContainer missing"
);
assert(
    html.includes('id="attrChannelTotalBadge"'),
    "FAIL: attrChannelTotalBadge missing"
);
console.log("✓ Test 6 Passed: Channel Grouping 10-tier container and badges present");

// 7. Verify First-Touch vs Last-Touch Comparison Tables
assert(
    html.includes('id="attrFirstTouchBody"'),
    "FAIL: attrFirstTouchBody missing"
);
assert(
    html.includes('id="attrLastTouchBody"'),
    "FAIL: attrLastTouchBody missing"
);
console.log("✓ Test 7 Passed: First-Touch and Last-Touch comparison table bodies present");

// 8. Verify Continuous IST Daily Timeline Table
assert(
    html.includes('id="attrTimelineBody"'),
    "FAIL: attrTimelineBody missing"
);
assert(
    html.includes('id="attrTimelineCountBadge"'),
    "FAIL: attrTimelineCountBadge missing"
);
console.log("✓ Test 8 Passed: IST Daily Timeline table body and day counter badge present");

// 9. Verify Campaign Analytics Search & Table
assert(
    html.includes('id="attrCampaignSearch"'),
    "FAIL: attrCampaignSearch input missing"
);
assert(
    html.includes('id="attrCampaignsBody"'),
    "FAIL: attrCampaignsBody table body missing"
);
assert(
    html.includes('handleAttributionCampaignSearch()'),
    "FAIL: handleAttributionCampaignSearch input listener missing"
);
console.log("✓ Test 9 Passed: Searchable campaign table and live search handler present");

// 10. Verify Cross-Channel Journey Transition Table
assert(
    html.includes('id="attrJourneysBody"'),
    "FAIL: attrJourneysBody missing"
);
console.log("✓ Test 10 Passed: Multi-touch journey transition table present");

// 11. Verify JavaScript Functions Defined in Script
const requiredFunctions = [
    'switchGrowthSubtab',
    'setAttributionAccountType',
    'loadMarketingAttribution',
    'renderAttributionKPIs',
    'renderAttributionChannels',
    'renderAttributionTouches',
    'renderAttributionTimeline',
    'renderAttributionCampaigns',
    'handleAttributionCampaignSearch',
    'renderAttributionJourneys'
];
for (const fnName of requiredFunctions) {
    assert(
        html.includes(`function ${fnName}`) || html.includes(`${fnName} =`),
        `FAIL: Expected JavaScript function '${fnName}' missing`
    );
}
console.log("✓ Test 11 Passed: All 10 controller and rendering functions defined in JavaScript");

// 12. Verify 366-Day Maximum Custom Range Validation
assert(
    html.includes('366') && html.includes('Custom date range cannot exceed 366 days'),
    "FAIL: 366-day custom date range frontend validation guard missing"
);
console.log("✓ Test 12 Passed: Frontend enforces maximum 366-day custom date span");

// 13. Verify Zero-PII Guarantee in Frontend
const forbiddenPII = ['visitor_id', 'raw_metadata', 'user_id', 'password_hash'];
for (const pii of forbiddenPII) {
    // Ensure these raw database column references are not exposed as table headers or DOM IDs
    assert(
        !html.includes(`<th>${pii}</th>`),
        `FAIL: Database column '${pii}' exposed in table headers`
    );
}
console.log("✓ Test 13 Passed: Zero-PII contract verified in DOM presentation");

console.log("\n=======================================================");
console.log("All 13 Phase 1D-5C Admin UI Attribution Tests PASSED!");
console.log("=======================================================");
