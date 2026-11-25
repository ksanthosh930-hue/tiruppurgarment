/**
 * DigiGarment – Phase 1D-4C Frontend Attribution Unit & Integration Test Suite
 * Tests static/dg-attribution.js and js/dg-attribution.js:
 * 1. Initial UTM capture (first touch & last touch)
 * 2. Navigation without campaign parameters (first touch survives, last touch not corrupted)
 * 3. Subsequent campaign arrival (last touch updates, first touch preserved)
 * 4. Internal navigation (last touch never overwritten by internal pages)
 * 5. Click IDs (gclid -> google cpc, fbclid -> facebook social)
 * 6. External organic and social referrers (Google, Instagram, Facebook, WhatsApp)
 * 7. Android App Intent referrers
 * 8. Zero-PII sanitization (phones with formatting, emails, script tags)
 * 9. Storage failure / restricted mode resilience
 * 10. getMarketingAttributionPayload() structure matching FastAPI schema
 * 11. Visitor ID consistency across calls
 */

const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const SCRIPT_PATH = path.join(__dirname, "..", "js", "dg-attribution.js");
const scriptCode = fs.readFileSync(SCRIPT_PATH, "utf8");

function createMockEnvironment(options = {}) {
    const memoryLocalStorage = {};
    let cookies = "";

    const window = {
        location: {
            origin: options.origin || "https://tirupurgarment.in",
            pathname: options.pathname || "/",
            search: options.search || "",
            protocol: options.protocol || "https:",
            hostname: options.hostname || "tirupurgarment.in",
            get href() {
                return this.origin + this.pathname + this.search;
            }
        },
        innerWidth: options.innerWidth || 1200,
        innerHeight: options.innerHeight || 800,
        crypto: {
            randomUUID: () => "mock-uuid-1234-5678-90ab"
        }
    };

    const document = {
        referrer: options.referrer !== undefined ? options.referrer : "",
        get cookie() {
            return cookies;
        },
        set cookie(val) {
            cookies += (cookies ? "; " : "") + val;
        }
    };

    const localStorage = {
        getItem: (k) => {
            if (options.storageThrows) throw new Error("SecurityError: Storage is disabled");
            return memoryLocalStorage[k] !== undefined ? memoryLocalStorage[k] : null;
        },
        setItem: (k, v) => {
            if (options.storageThrows) throw new Error("QuotaExceededError: Storage is full");
            memoryLocalStorage[k] = String(v);
        },
        removeItem: (k) => {
            delete memoryLocalStorage[k];
        }
    };

    const context = vm.createContext({
        window,
        document,
        localStorage,
        console,
        URL,
        URLSearchParams,
        Date,
        Intl,
        crypto: window.crypto,
        JSON,
        Set,
        RegExp,
        String,
        Math
    });

    // Make window self-referential
    context.window.window = context.window;
    context.window.document = context.document;
    context.window.localStorage = context.localStorage;

    return { context, window: context.window, localStorage };
}

function runScriptInContext(context) {
    const script = new vm.Script(scriptCode);
    script.runInContext(context);
}

// ========================== TEST CASES ==========================

console.log("Running Phase 1D-4C Frontend Attribution Tests...\n");

// Test 1: First Visit with UTM Parameters
{
    const { context, window } = createMockEnvironment({
        search: "?utm_source=instagram&utm_medium=paid_social&utm_campaign=garment_workers_nov&utm_content=reel_ad_1&utm_term=tailors",
        referrer: "https://l.instagram.com/"
    });
    runScriptInContext(context);

    const payload = window.getMarketingAttributionPayload();
    assert.ok(payload.visitor_id.startsWith("v_"), "Visitor ID must start with v_");
    assert.strictEqual(payload.first_touch.source, "instagram");
    assert.strictEqual(payload.first_touch.medium, "paid_social");
    assert.strictEqual(payload.first_touch.campaign, "garment_workers_nov");
    assert.strictEqual(payload.first_touch.content, "reel_ad_1");
    assert.strictEqual(payload.first_touch.term, "tailors");

    // Last touch should match first touch on initial visit
    assert.strictEqual(payload.last_touch.source, "instagram");
    assert.strictEqual(payload.last_touch.medium, "paid_social");
    console.log("✓ Test 1 Passed: First Visit with UTM Parameters captured correctly");
}

// Test 2: Internal Navigation preserves First Touch & Last Touch
{
    const { context, window } = createMockEnvironment({
        search: "?utm_source=instagram&utm_medium=paid_social&utm_campaign=garment_workers_nov",
        referrer: "https://l.instagram.com/"
    });
    runScriptInContext(context);

    // Simulate navigating to /jobs with internal referrer
    window.location.pathname = "/jobs";
    window.location.search = "";
    context.document.referrer = "https://tirupurgarment.in/";
    window.dgAttribution.refresh();

    const payload = window.getMarketingAttributionPayload();
    assert.strictEqual(payload.first_touch.source, "instagram", "First touch must not be overwritten by internal nav");
    assert.strictEqual(payload.first_touch.campaign, "garment_workers_nov");
    assert.strictEqual(payload.last_touch.source, "instagram", "Last touch must not be overwritten by internal nav");

    // Simulate navigating to /signup
    window.location.pathname = "/signup";
    window.location.search = "";
    context.document.referrer = "https://tirupurgarment.in/jobs";
    window.dgAttribution.refresh();

    const payloadSignup = window.getMarketingAttributionPayload();
    assert.strictEqual(payloadSignup.first_touch.source, "instagram");
    assert.strictEqual(payloadSignup.last_touch.source, "instagram");
    console.log("✓ Test 2 Passed: Internal navigation never corrupts first or last touch");
}

// Test 3: Subsequent Campaign arrival updates Last Touch, preserves First Touch
{
    const { context, window } = createMockEnvironment({
        search: "?utm_source=google&utm_medium=organic",
        referrer: "https://www.google.co.in/"
    });
    runScriptInContext(context);

    // Initial visit was Google Organic
    let payload = window.getMarketingAttributionPayload();
    assert.strictEqual(payload.first_touch.source, "google");
    assert.strictEqual(payload.first_touch.medium, "organic");
    assert.strictEqual(payload.last_touch.source, "google");

    // User later returns via a Facebook Ad (gclid / fbclid)
    window.location.pathname = "/hire";
    window.location.search = "?fbclid=IwAR2xyz987&utm_campaign=employer_hire_nov";
    context.document.referrer = "https://m.facebook.com/";
    window.dgAttribution.refresh();

    payload = window.getMarketingAttributionPayload();
    assert.strictEqual(payload.first_touch.source, "google", "First touch must remain google organic");
    assert.strictEqual(payload.first_touch.medium, "organic");
    assert.strictEqual(payload.last_touch.source, "facebook", "Last touch must update to facebook");
    assert.strictEqual(payload.last_touch.medium, "social");
    assert.strictEqual(payload.last_touch.campaign, "employer_hire_nov");
    console.log("✓ Test 3 Passed: Multi-touch (First-touch preserved, Last-touch updated)");
}

// Test 4: Google Ads via gclid
{
    const { context, window } = createMockEnvironment({
        search: "?gclid=Cj0KCQiA_testGoogleAdClick&utm_campaign=tirupur_tailor_jobs",
        referrer: "https://www.google.com/"
    });
    runScriptInContext(context);

    const payload = window.getMarketingAttributionPayload();
    assert.strictEqual(payload.first_touch.source, "google");
    assert.strictEqual(payload.first_touch.medium, "cpc");
    assert.strictEqual(payload.first_touch.campaign, "tirupur_tailor_jobs");
    console.log("✓ Test 4 Passed: Google Ads gclid parameter classified as google / cpc");
}

// Test 5: WhatsApp Chat Share
{
    const { context, window } = createMockEnvironment({
        search: "?utm_source=whatsapp&utm_medium=chat_share&utm_campaign=job_posting_123"
    });
    runScriptInContext(context);

    const payload = window.getMarketingAttributionPayload();
    assert.strictEqual(payload.first_touch.source, "whatsapp");
    assert.strictEqual(payload.first_touch.medium, "chat_share");
    assert.strictEqual(payload.first_touch.campaign, "job_posting_123");
    console.log("✓ Test 5 Passed: WhatsApp chat share attribution");
}

// Test 6: Android App Intent Referrer
{
    const { context, window } = createMockEnvironment({
        referrer: "android-app://com.instagram.android/"
    });
    runScriptInContext(context);

    const payload = window.getMarketingAttributionPayload();
    assert.strictEqual(payload.first_touch.source, "instagram");
    assert.strictEqual(payload.first_touch.medium, "social");
    console.log("✓ Test 6 Passed: Android App Intent (com.instagram.android) recognized");
}

// Test 7: PII Sanitization in Query Parameters
{
    const { context, window } = createMockEnvironment({
        search: "?utm_source=email_blast&utm_term=call 98421 98421 now&utm_content=user@example.com<script>alert(1)</script>"
    });
    runScriptInContext(context);

    const payload = window.getMarketingAttributionPayload();
    assert.strictEqual(payload.first_touch.source, "email_blast");
    assert.strictEqual(payload.first_touch.term, null, "Phone PII in term must be redacted to null");
    assert.strictEqual(payload.first_touch.content, null, "Email PII and script in content must be redacted to null");
    console.log("✓ Test 7 Passed: Formatted phone and email PII in campaign fields redacted");
}

// Test 8: Sensitive Query Parameters Stripped from Landing Page
{
    const { context, window } = createMockEnvironment({
        search: "?utm_source=google&token=secret_auth_token_xyz&password=mypassword&code=oauth_code_123"
    });
    runScriptInContext(context);

    const payload = window.getMarketingAttributionPayload();
    assert.ok(payload.first_touch.landing_page.includes("utm_source=google"), "Must retain marketing param");
    assert.ok(!payload.first_touch.landing_page.includes("secret_auth_token_xyz"), "Must strip auth token");
    assert.ok(!payload.first_touch.landing_page.includes("mypassword"), "Must strip password");
    assert.ok(!payload.first_touch.landing_page.includes("oauth_code_123"), "Must strip oauth code");
    console.log("✓ Test 8 Passed: Sensitive parameters stripped from landing_page URL");
}

// Test 9: Graceful Storage Failure (Private mode / disabled storage)
{
    const { context, window } = createMockEnvironment({
        search: "?utm_source=direct_search",
        storageThrows: true
    });
    runScriptInContext(context);

    // Should not throw and still return valid payload via in-memory fallback
    const payload = window.getMarketingAttributionPayload();
    assert.ok(payload, "Payload must be returned even if localStorage throws");
    assert.strictEqual(payload.first_touch.source, "direct_search");
    console.log("✓ Test 9 Passed: Graceful fallback when localStorage is disabled / throws");
}

// Test 10: Visitor ID Consistency
{
    const { context, window } = createMockEnvironment({});
    runScriptInContext(context);

    const vid1 = window.getVisitorId();
    const vid2 = window.getVisitorId();
    const payload = window.getMarketingAttributionPayload();

    assert.strictEqual(vid1, vid2, "Repeated getVisitorId() calls must return identical ID");
    assert.strictEqual(payload.visitor_id, vid1, "Payload visitor_id must match getVisitorId()");
    console.log("✓ Test 10 Passed: Visitor ID consistency maintained");
}

// Test 11: Double-Inclusion Protection Guard (REV-05)
{
    const { context, window } = createMockEnvironment({
        search: "?utm_source=instagram&utm_medium=paid_social&utm_campaign=initial_campaign"
    });
    runScriptInContext(context);
    assert.strictEqual(window.__dg_attribution_initialized, true, "Guard flag must be true after 1st execution");

    // Modify search to simulate a conflicting second inclusion attempt
    window.location.search = "?utm_source=malicious&utm_medium=spoof&utm_campaign=corrupt";
    // Execute script a 2nd time
    runScriptInContext(context);

    // Initial attribution must remain untouched because guard stopped re-initialization
    const payload = window.getMarketingAttributionPayload();
    assert.strictEqual(payload.first_touch.source, "instagram");
    assert.strictEqual(payload.first_touch.campaign, "initial_campaign");
    console.log("✓ Test 11 Passed: Double-inclusion guard prevents duplicate initialization and state corruption");
}

// Test 12: Script Copy Parity (REV-02)
{
    const staticPath = path.join(__dirname, "..", "static", "dg-attribution.js");
    const jsPath = path.join(__dirname, "..", "js", "dg-attribution.js");
    const staticCode = fs.readFileSync(staticPath, "utf8");
    const jsCode = fs.readFileSync(jsPath, "utf8");
    assert.strictEqual(staticCode, jsCode, "static/dg-attribution.js and js/dg-attribution.js must be identical");
    console.log("✓ Test 12 Passed: static/ and js/ script copies are 100% identical");
}

console.log("\n=======================================================");
console.log("All 12 Phase 1D-4C Frontend Attribution Tests PASSED!");
console.log("=======================================================");
