/**
 * DigiGarment - Global Auth Navbar Controller
 * Dynamically updates header navigation based on user session status.
 * Replaces Login/Signup with a rich User Profile Pill & Settings Dropdown when authenticated.
 */

(function () {
    async function initAuthNav() {
        try {
            const res = await fetch("/api/auth/me");
            if (!res.ok) {
                // Not authenticated (guest) - leave default Login / Sign Up buttons
                return;
            }

            const data = await res.json();
            if (!data || !data.logged_in || !data.user) {
                return;
            }

            const user = data.user;
            const accountType = user.account_type || "individual";
            const profile = user.profile || {};
            
            // Determine display name
            let displayName = "";
            if (accountType === "individual") {
                displayName = (profile.full_name || "").trim() || user.email.split("@")[0];
            } else {
                displayName = (profile.company_name || profile.contact_person || "").trim() || user.email.split("@")[0];
            }

            // Initials (max 2 characters)
            const initials = displayName
                .split(" ")
                .filter(Boolean)
                .map(part => part[0])
                .slice(0, 2)
                .join("")
                .toUpperCase() || "U";

            const roleBadge = accountType === "individual" ? "👤 Job Seeker" : "🏢 Employer";
            const dashboardUrl = accountType === "individual" ? "/dashboard/individual" : "/dashboard/company";
            const email = user.email || "";

            // Find all nav containers (desktop / mobile)
            const navs = document.querySelectorAll(".nav, #mainNav");
            if (!navs.length) return;

            navs.forEach(nav => {
                // Hide guest links (Login & Sign Up)
                const links = nav.querySelectorAll("a");
                links.forEach(link => {
                    const href = (link.getAttribute("href") || "").toLowerCase();
                    const text = (link.textContent || "").trim().toLowerCase();
                    if (
                        href.includes("/login") || 
                        href.includes("login.html") || 
                        href.includes("/signup") || 
                        href.includes("signup.html") ||
                        link.classList.contains("nav-cta") ||
                        text === "login" ||
                        text === "sign up"
                    ) {
                        link.style.display = "none";
                    }
                });

                // Remove existing user dropdown if any
                const existingDropdown = nav.querySelector(".dg-user-dropdown-wrap");
                if (existingDropdown) {
                    existingDropdown.remove();
                }

                // Create user dropdown element
                const userDropdownWrap = document.createElement("div");
                userDropdownWrap.className = "dg-user-dropdown-wrap";
                userDropdownWrap.innerHTML = `
                    <button type="button" class="dg-user-pill-btn" aria-expanded="false" aria-haspopup="true">
                        <span class="dg-user-avatar">${escapeHtml(initials)}</span>
                        <span class="dg-user-name">${escapeHtml(displayName)}</span>
                        <svg class="dg-chevron-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                            <polyline points="6 9 12 15 18 9"></polyline>
                        </svg>
                    </button>
                    <div class="dg-user-menu">
                        <div class="dg-user-menu-header">
                            <div class="dg-user-menu-avatar">${escapeHtml(initials)}</div>
                            <div class="dg-user-menu-info">
                                <div class="dg-user-menu-name">${escapeHtml(displayName)}</div>
                                <div class="dg-user-menu-email">${escapeHtml(email)}</div>
                                <span class="dg-user-menu-badge">${roleBadge}</span>
                            </div>
                        </div>
                        <div class="dg-user-menu-divider"></div>
                        <div class="dg-user-menu-links">
                            <a href="${dashboardUrl}" class="dg-user-menu-item">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <rect x="3" y="3" width="7" height="9"></rect>
                                    <rect x="14" y="3" width="7" height="5"></rect>
                                    <rect x="14" y="12" width="7" height="9"></rect>
                                    <rect x="3" y="16" width="7" height="5"></rect>
                                </svg>
                                <span>My Dashboard</span>
                            </a>
                            <a href="${dashboardUrl}#profile" class="dg-user-menu-item">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                                    <circle cx="12" cy="7" r="4"></circle>
                                </svg>
                                <span>Profile & Settings</span>
                            </a>
                            <a href="/jobs" class="dg-user-menu-item">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <rect x="2" y="7" width="20" height="14" rx="2" ry="2"></rect>
                                    <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"></path>
                                </svg>
                                <span>Browse Jobs</span>
                            </a>
                            ${accountType === "individual" ? `
                            <a href="/dashboard/individual#recommended" class="dg-user-menu-item">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <circle cx="12" cy="12" r="10"></circle>
                                    <polygon points="12 8 8 12 12 16 16 12 12 8"></polygon>
                                </svg>
                                <span>Recommended Jobs</span>
                            </a>
                            <a href="/dashboard/individual#saved" class="dg-user-menu-item">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"></path>
                                </svg>
                                <span>Saved Jobs</span>
                            </a>
                            <a href="/dashboard/individual#job-alerts" class="dg-user-menu-item">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path>
                                    <path d="M13.73 21a2 2 0 0 1-3.46 0"></path>
                                </svg>
                                <span>Job Alerts</span>
                            </a>` : ""}
                            ${accountType === "company" ? `
                            <a href="/dashboard/company#post-job" class="dg-user-menu-item">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <line x1="12" y1="5" x2="12" y2="19"></line>
                                    <line x1="5" y1="12" x2="19" y2="12"></line>
                                </svg>
                                <span>Post a New Job</span>
                            </a>` : ""}
                        </div>
                        <div class="dg-user-menu-divider"></div>
                        <div class="dg-user-menu-footer">
                            <button type="button" class="dg-user-logout-btn" onclick="window.dgHandleUserLogout()">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
                                    <polyline points="16 17 21 12 16 7"></polyline>
                                    <line x1="21" y1="12" x2="9" y2="12"></line>
                                </svg>
                                <span>Sign Out</span>
                            </button>
                        </div>
                    </div>
                `;

                nav.appendChild(userDropdownWrap);

                // Setup toggle
                const pillBtn = userDropdownWrap.querySelector(".dg-user-pill-btn");
                const menu = userDropdownWrap.querySelector(".dg-user-menu");

                pillBtn.addEventListener("click", (e) => {
                    e.stopPropagation();
                    const isOpen = userDropdownWrap.classList.contains("active");
                    
                    // Close any other open dropdowns
                    document.querySelectorAll(".dg-user-dropdown-wrap.active").forEach(el => {
                        el.classList.remove("active");
                        const btn = el.querySelector(".dg-user-pill-btn");
                        if (btn) btn.setAttribute("aria-expanded", "false");
                    });

                    if (!isOpen) {
                        userDropdownWrap.classList.add("active");
                        pillBtn.setAttribute("aria-expanded", "true");
                    }
                });
            });

            // Global click outside to close dropdowns
            document.addEventListener("click", (e) => {
                if (!e.target.closest(".dg-user-dropdown-wrap")) {
                    document.querySelectorAll(".dg-user-dropdown-wrap.active").forEach(el => {
                        el.classList.remove("active");
                        const btn = el.querySelector(".dg-user-pill-btn");
                        if (btn) btn.setAttribute("aria-expanded", "false");
                    });
                }
            });

            // Escape key to close
            document.addEventListener("keydown", (e) => {
                if (e.key === "Escape") {
                    document.querySelectorAll(".dg-user-dropdown-wrap.active").forEach(el => {
                        el.classList.remove("active");
                        const btn = el.querySelector(".dg-user-pill-btn");
                        if (btn) btn.setAttribute("aria-expanded", "false");
                    });
                }
            });

        } catch (err) {
            console.error("Auth navbar initialization error:", err);
        }
    }

    function escapeHtml(str) {
        if (!str) return "";
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    // Global Logout Handler
    window.dgHandleUserLogout = async function () {
        try {
            await fetch("/api/auth/logout", { method: "POST" });
        } catch (e) {
            console.error("Logout request error:", e);
        } finally {
            window.location.href = "/";
        }
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initAuthNav);
    } else {
        initAuthNav();
    }
})();
