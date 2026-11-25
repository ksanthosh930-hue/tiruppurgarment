/**
 * DigiGarment – Universal Marketing Attribution Engine
 * Authoritative, Zero-PII deterministic attribution tracking for Job Seekers and Employers.
 * Phase 1D-4C Frontend Integration (Remediated in Phase 1D-4C-Fix)
 * 
 * Features:
 * - Deterministic First-Touch & Last-Touch campaign tracking
 * - Double-inclusion protection guard (REV-05)
 * - Captures UTM parameters (utm_source, utm_medium, utm_campaign, utm_content, utm_term)
 * - Captures click IDs (gclid, fbclid)
 * - Identifies external organic & social referrers (Google, Instagram, Facebook, WhatsApp)
 * - Supports Android App Intent referrers (com.instagram.android, com.whatsapp, etc.)
 * - Protects against internal navigation corrupting acquisition touchpoints
 * - Canonical visitor ID persistence matching existing dg_visitor_id
 * - Zero-PII enforcement, strict parameter sanitization, and graceful storage failure
 * - Universal getMarketingAttributionPayload() function matching FastAPI schema
 */

(function () {
    "use strict";

    // Double-Inclusion Guard (REV-05)
    if (typeof window !== "undefined") {
        if (window.__dg_attribution_initialized) return;
        window.__dg_attribution_initialized = true;
    }

    // Storage Keys
    const STORAGE_KEY_VID = "dg_visitor_id";
    const STORAGE_KEY_FIRST_TOUCH = "dg_first_touch";
    const STORAGE_KEY_LAST_TOUCH = "dg_last_touch";
    const COOKIE_EXPIRY_DAYS = 365;

    // Field Length Limits (aligned with backend schemas/attribution.py)
    const MAX_SOURCE_LEN = 100;
    const MAX_MEDIUM_LEN = 50;
    const MAX_CAMPAIGN_LEN = 150;
    const MAX_CONTENT_LEN = 150;
    const MAX_TERM_LEN = 150;
    const MAX_URL_LEN = 2048;
    const MAX_VISITOR_ID_LEN = 64;

    // PII Detection Regexes
    const EMAIL_REGEX = /[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+/;
    const SENSITIVE_QUERY_PARAMS = new Set([
        "password", "token", "access_token", "id_token", "code", "state",
        "otp", "email", "mobile", "phone", "candpassword", "userpassword"
    ]);

    // Internal Hosts
    const INTERNAL_HOSTS = new Set([
        "tirupurgarment.in",
        "www.tirupurgarment.in",
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "testserver"
    ]);
    if (typeof window !== "undefined" && window.location && window.location.hostname) {
        INTERNAL_HOSTS.add(window.location.hostname.toLowerCase());
    }

    // In-memory fallback if storage is restricted
    const memoryStorage = {};

    // --- Safe Storage Helpers ---
    function safeGetItem(key) {
        try {
            const val = localStorage.getItem(key);
            if (val !== null) return val;
        } catch (e) {}
        try {
            const match = document.cookie.match(new RegExp("(?:^|; )" + key.replace(/([\.$?*|{}\(\)\[\]\\\/\+^])/g, "\\$1") + "=([^;]*)"));
            if (match) return decodeURIComponent(match[1]);
        } catch (e) {}
        return memoryStorage[key] || null;
    }

    function safeSetItem(key, value, days) {
        if (!days) days = COOKIE_EXPIRY_DAYS;
        try {
            localStorage.setItem(key, value);
        } catch (e) {}
        try {
            const expires = new Date(Date.now() + days * 864e5).toUTCString();
            const isSecure = window.location.protocol === "https:";
            document.cookie = key + "=" + encodeURIComponent(value) +
                "; expires=" + expires +
                "; path=/" +
                "; SameSite=Lax" +
                (isSecure ? "; Secure" : "");
        } catch (e) {}
        memoryStorage[key] = value;
    }

    // --- Text & PII Sanitization ---
    function containsPhonePii(text) {
        if (!text || typeof text !== "string") return false;
        // Search for Indian phone patterns with optional spaces, dashes, dots, parens, country code
        const phoneMatch = text.match(/(?:\+?91|0)?[\s\-\.\(\)]*[6-9](?:[\s\-\.\(\)]*\d){9}/);
        if (!phoneMatch) return false;
        let cleaned = phoneMatch[0].replace(/[\s\-\.\(\)]/g, "");
        if (cleaned.startsWith("+91")) cleaned = cleaned.slice(3);
        else if (cleaned.startsWith("91") && cleaned.length === 12) cleaned = cleaned.slice(2);
        else if (cleaned.startsWith("0") && cleaned.length === 11) cleaned = cleaned.slice(1);
        return cleaned.length === 10 && /^[6-9]\d{9}$/.test(cleaned);
    }

    function sanitizeString(val, maxLen) {
        if (val === null || val === undefined) return null;
        let s = String(val).trim();
        if (!s) return null;
        // Strip script tags and HTML
        s = s.replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, "");
        s = s.replace(/<[^>]+>/g, "").trim();
        if (!s) return null;
        // PII redaction
        if (EMAIL_REGEX.test(s) || containsPhonePii(s)) {
            return null;
        }
        return s.slice(0, maxLen);
    }

    function cleanUrl(rawUrl, maxLen) {
        if (!rawUrl) return null;
        try {
            const parsed = new URL(rawUrl, window.location.origin);
            // Remove sensitive query params
            const cleanParams = new URLSearchParams();
            parsed.searchParams.forEach((v, k) => {
                const kLower = k.toLowerCase();
                if (!SENSITIVE_QUERY_PARAMS.has(kLower)) {
                    // Also check for PII in param value
                    const sanitizedVal = sanitizeString(v, 200);
                    if (sanitizedVal !== null) {
                        cleanParams.set(k, sanitizedVal);
                    }
                }
            });
            const searchStr = cleanParams.toString();
            const result = parsed.origin + parsed.pathname + (searchStr ? "?" + searchStr : "");
            return result.slice(0, maxLen || MAX_URL_LEN);
        } catch (e) {
            return sanitizeString(rawUrl, maxLen || MAX_URL_LEN);
        }
    }

    function extractHost(urlStr) {
        if (!urlStr) return null;
        try {
            // Support android-app:// URLs
            if (urlStr.startsWith("android-app://")) {
                const stripped = urlStr.replace("android-app://", "").split("/")[0];
                return stripped.toLowerCase().trim() || null;
            }
            const parsed = new URL(urlStr, window.location.origin);
            return parsed.hostname.toLowerCase().trim() || null;
        } catch (e) {
            return null;
        }
    }

    function isMatchingDomain(host, targetDomain) {
        if (!host || !targetDomain) return false;
        const h = host.toLowerCase().trim();
        const t = targetDomain.toLowerCase().trim();
        return h === t || h.endsWith("." + t);
    }

    function isInternalHost(host) {
        if (!host) return true;
        const h = host.toLowerCase().trim();
        if (INTERNAL_HOSTS.has(h)) return true;
        const curr = window.location.hostname.toLowerCase();
        return h === curr || h.endsWith("." + curr);
    }

    // --- Visitor ID Management ---
    function getVisitorId() {
        let vid = safeGetItem(STORAGE_KEY_VID);
        const vidPattern = /^[a-zA-Z0-9_\-\.]{4,64}$/;
        if (vid && vidPattern.test(vid)) {
            return vid;
        }
        // Generate compatible visitor ID: v_uuid
        let newVid = null;
        if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
            newVid = "v_" + crypto.randomUUID();
        } else {
            newVid = "v_" + Math.random().toString(36).substring(2, 12) + Date.now().toString(36);
        }
        newVid = newVid.slice(0, MAX_VISITOR_ID_LEN);
        safeSetItem(STORAGE_KEY_VID, newVid, COOKIE_EXPIRY_DAYS);
        return newVid;
    }

    // --- Touch Extraction & Channel Derivation ---
    function extractTouchFromCurrentVisit() {
        let searchParams = null;
        try {
            searchParams = new URLSearchParams(window.location.search);
        } catch (e) {
            searchParams = new URLSearchParams();
        }

        const utmSource = sanitizeString(searchParams.get("utm_source"), MAX_SOURCE_LEN);
        const utmMedium = sanitizeString(searchParams.get("utm_medium"), MAX_MEDIUM_LEN);
        const utmCampaign = sanitizeString(searchParams.get("utm_campaign"), MAX_CAMPAIGN_LEN);
        const utmContent = sanitizeString(searchParams.get("utm_content"), MAX_CONTENT_LEN);
        const utmTerm = sanitizeString(searchParams.get("utm_term"), MAX_TERM_LEN);
        const gclid = sanitizeString(searchParams.get("gclid"), 100);
        const fbclid = sanitizeString(searchParams.get("fbclid"), 100);
        const refParam = sanitizeString(searchParams.get("ref"), 100);

        const currentLanding = cleanUrl(window.location.href, MAX_URL_LEN);
        const rawReferrer = document.referrer ? document.referrer.trim() : null;
        const refHost = extractHost(rawReferrer);
        const isInternalRef = isInternalHost(refHost);
        const cleanRef = isInternalRef ? null : cleanUrl(rawReferrer, MAX_URL_LEN);

        const nowIso = new Date().toISOString();

        // 1. Google Ads (gclid present or explicit google + cpc)
        if (gclid || (utmSource === "google" && ["cpc", "ppc", "paidsearch", "adwords"].includes((utmMedium || "").toLowerCase()))) {
            return {
                source: "google",
                medium: "cpc",
                campaign: utmCampaign || "(google_ads)",
                content: utmContent || null,
                term: utmTerm || null,
                landing_page: currentLanding,
                referrer: cleanRef,
                visit_at: nowIso,
                is_campaign: true
            };
        }

        // 2. Facebook (fbclid present or explicit facebook)
        if (fbclid || utmSource === "facebook" || isMatchingDomain(refHost, "facebook.com") || refHost === "com.facebook.katana" || refHost === "com.facebook.orca") {
            const med = utmMedium ? utmMedium.toLowerCase() : "social";
            return {
                source: "facebook",
                medium: ["paid_social", "cpc", "ad"].includes(med) ? med : "social",
                campaign: utmCampaign || null,
                content: utmContent || null,
                term: utmTerm || null,
                landing_page: currentLanding,
                referrer: cleanRef,
                visit_at: nowIso,
                is_campaign: Boolean(fbclid || utmSource || utmCampaign)
            };
        }

        // 3. Instagram
        if (utmSource === "instagram" || isMatchingDomain(refHost, "instagram.com") || refHost === "com.instagram.android") {
            const med = utmMedium ? utmMedium.toLowerCase() : "social";
            return {
                source: "instagram",
                medium: ["paid_social", "story", "reel", "cpc", "ad"].includes(med) ? med : "social",
                campaign: utmCampaign || null,
                content: utmContent || null,
                term: utmTerm || null,
                landing_page: currentLanding,
                referrer: cleanRef,
                visit_at: nowIso,
                is_campaign: Boolean(utmSource || utmCampaign)
            };
        }

        // 4. WhatsApp
        if (utmSource === "whatsapp" || isMatchingDomain(refHost, "whatsapp.com") || refHost === "com.whatsapp") {
            const med = utmMedium ? utmMedium.toLowerCase() : "chat_share";
            return {
                source: "whatsapp",
                medium: ["chat_share", "job_alert", "broadcast", "cpc"].includes(med) ? med : "chat_share",
                campaign: utmCampaign || null,
                content: utmContent || null,
                term: utmTerm || null,
                landing_page: currentLanding,
                referrer: cleanRef,
                visit_at: nowIso,
                is_campaign: Boolean(utmSource || utmCampaign)
            };
        }

        // 5. Generic UTM Campaign
        if (utmSource || utmMedium || utmCampaign) {
            return {
                source: utmSource || "direct",
                medium: utmMedium || "(none)",
                campaign: utmCampaign || null,
                content: utmContent || null,
                term: utmTerm || null,
                landing_page: currentLanding,
                referrer: cleanRef,
                visit_at: nowIso,
                is_campaign: true
            };
        }

        // 6. Google Organic Search
        if (isMatchingDomain(refHost, "google.com") || isMatchingDomain(refHost, "google.co.in") || isMatchingDomain(refHost, "google.in") || refHost === "com.google.android.googlequicksearchbox") {
            return {
                source: "google",
                medium: "organic",
                campaign: "(organic)",
                content: null,
                term: null,
                landing_page: currentLanding,
                referrer: cleanRef,
                visit_at: nowIso,
                is_campaign: false,
                is_external_referrer: true
            };
        }

        // 7. Generic External Referral
        if (refHost && !isInternalRef) {
            return {
                source: sanitizeString(refHost, MAX_SOURCE_LEN),
                medium: "referral",
                campaign: null,
                content: null,
                term: null,
                landing_page: currentLanding,
                referrer: cleanRef,
                visit_at: nowIso,
                is_campaign: false,
                is_external_referrer: true
            };
        }

        // 8. Internal Navigation or Direct Visit
        return {
            source: "direct",
            medium: "(none)",
            campaign: null,
            content: null,
            term: null,
            landing_page: currentLanding,
            referrer: null,
            visit_at: nowIso,
            is_campaign: false,
            is_internal: isInternalRef
        };
    }

    // --- State Storage Helpers ---
    function getStoredTouch(storageKey) {
        try {
            const raw = safeGetItem(storageKey);
            if (!raw) return null;
            const parsed = JSON.parse(raw);
            if (parsed && typeof parsed === "object") {
                return parsed;
            }
        } catch (e) {}
        return null;
    }

    function saveStoredTouch(storageKey, touchObj) {
        if (!touchObj) return;
        const cleanTouch = {
            source: sanitizeString(touchObj.source, MAX_SOURCE_LEN) || "direct",
            medium: sanitizeString(touchObj.medium, MAX_MEDIUM_LEN) || "(none)",
            campaign: sanitizeString(touchObj.campaign, MAX_CAMPAIGN_LEN),
            content: sanitizeString(touchObj.content, MAX_CONTENT_LEN),
            term: sanitizeString(touchObj.term, MAX_TERM_LEN),
            landing_page: sanitizeString(touchObj.landing_page, MAX_URL_LEN),
            referrer: sanitizeString(touchObj.referrer, MAX_URL_LEN),
            visit_at: touchObj.visit_at || new Date().toISOString()
        };
        safeSetItem(storageKey, JSON.stringify(cleanTouch), COOKIE_EXPIRY_DAYS);
    }

    // --- Main Attribution Processor ---
    function processAttribution() {
        try {
            // Ensure visitor ID is established
            getVisitorId();

            const currentTouch = extractTouchFromCurrentVisit();
            const existingFirstTouch = getStoredTouch(STORAGE_KEY_FIRST_TOUCH);
            const existingLastTouch = getStoredTouch(STORAGE_KEY_LAST_TOUCH);

            // 1. FIRST-TOUCH LOGIC
            // If first-touch does NOT exist, record it immediately.
            // First-touch is NEVER overwritten on subsequent page loads or sources.
            if (!existingFirstTouch) {
                saveStoredTouch(STORAGE_KEY_FIRST_TOUCH, currentTouch);
                saveStoredTouch(STORAGE_KEY_LAST_TOUCH, currentTouch);
                return;
            }

            // 2. LAST-TOUCH LOGIC
            // Only update last touch if this visit represents a genuine new external marketing touch:
            // - Has explicit UTM / click ID parameters (is_campaign === true)
            // - OR has an identifiable external referrer (is_external_referrer === true)
            // Internal navigation (from / to /jobs to /signup) must NEVER overwrite last touch.
            if (currentTouch.is_campaign || currentTouch.is_external_referrer) {
                saveStoredTouch(STORAGE_KEY_LAST_TOUCH, currentTouch);
            } else if (!existingLastTouch) {
                // In case last touch was somehow missing but first touch exists
                saveStoredTouch(STORAGE_KEY_LAST_TOUCH, existingFirstTouch);
            }
        } catch (e) {
            // Never disrupt page execution on attribution failure
            if (typeof console !== "undefined" && console.warn) {
                console.warn("[dg-attribution] Non-fatal initialization error:", e);
            }
        }
    }

    // --- Public API ---
    function getMarketingAttributionPayload() {
        try {
            const vid = getVisitorId();
            let first = getStoredTouch(STORAGE_KEY_FIRST_TOUCH);
            let last = getStoredTouch(STORAGE_KEY_LAST_TOUCH);

            // If user somehow registers before processAttribution ran, run extraction now
            if (!first || !last) {
                processAttribution();
                first = getStoredTouch(STORAGE_KEY_FIRST_TOUCH);
                last = getStoredTouch(STORAGE_KEY_LAST_TOUCH);
            }

            const cleanTouchForPayload = (t) => {
                if (!t) return null;
                return {
                    source: sanitizeString(t.source, MAX_SOURCE_LEN) || "direct",
                    medium: sanitizeString(t.medium, MAX_MEDIUM_LEN) || "(none)",
                    campaign: sanitizeString(t.campaign, MAX_CAMPAIGN_LEN),
                    content: sanitizeString(t.content, MAX_CONTENT_LEN),
                    term: sanitizeString(t.term, MAX_TERM_LEN),
                    landing_page: sanitizeString(t.landing_page, MAX_URL_LEN),
                    referrer: sanitizeString(t.referrer, MAX_URL_LEN),
                    visit_at: t.visit_at || new Date().toISOString()
                };
            };

            return {
                visitor_id: vid || null,
                first_touch: cleanTouchForPayload(first),
                last_touch: cleanTouchForPayload(last || first),
                raw_metadata: {
                    client_captured: true,
                    viewport: typeof window !== "undefined" ? `${window.innerWidth}x${window.innerHeight}` : null,
                    tz: typeof Intl !== "undefined" && Intl.DateTimeFormat ? Intl.DateTimeFormat().resolvedOptions().timeZone : null
                }
            };
        } catch (e) {
            // Graceful fallback payload
            return {
                visitor_id: (typeof getVisitorId === "function" ? getVisitorId() : null),
                first_touch: null,
                last_touch: null,
                raw_metadata: { client_captured: false, error: String(e) }
            };
        }
    }

    // Expose Global Functions
    window.getMarketingAttributionPayload = getMarketingAttributionPayload;
    window.getVisitorId = getVisitorId;
    window.dgGetVisitorId = getVisitorId;

    window.dgAttribution = {
        getPayload: getMarketingAttributionPayload,
        getVisitorId: getVisitorId,
        getFirstTouch: () => getStoredTouch(STORAGE_KEY_FIRST_TOUCH),
        getLastTouch: () => getStoredTouch(STORAGE_KEY_LAST_TOUCH),
        refresh: processAttribution
    };

    // Auto-run immediately so initial URL parameters and referrer are captured before any redirect or router modification
    processAttribution();

})();
