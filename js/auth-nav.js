/**
 * DigiGarment - Global Auth Navbar & Notification Controller
 * Dynamically updates header navigation based on user session status.
 * Renders the user-specific Notification Bell (🔔) + Unread Badge and User Profile Dropdown.
 */

(function () {
    let cachedNotifications = [];
    let cachedUnreadCount = 0;
    let currentAccountType = null;

    function ensureAuthNavStylesheet() {
        if (!document.querySelector('link[href*="auth-nav.css"]')) {
            const link = document.createElement("link");
            link.rel = "stylesheet";
            link.href = "/css/auth-nav.css";
            document.head.appendChild(link);
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

    function formatRelativeTime(dateInput) {
        if (!dateInput) return "";
        try {
            const dt = new Date(dateInput);
            if (isNaN(dt.getTime())) return "";
            const diffSec = Math.floor((Date.now() - dt.getTime()) / 1000);
            if (diffSec < 60) return "Just now";
            const diffMin = Math.floor(diffSec / 60);
            if (diffMin < 60) return `${diffMin}m ago`;
            const diffHr = Math.floor(diffMin / 60);
            if (diffHr < 24) return `${diffHr}h ago`;
            const diffDay = Math.floor(diffHr / 24);
            if (diffDay < 7) return `${diffDay}d ago`;
            return dt.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
        } catch (e) {
            return "";
        }
    }

    function getNotifIcon(eventType) {
        const t = String(eventType || "").toLowerCase();
        if (t.includes("applied")) return "📩";
        if (t.includes("milestone")) return "🎉";
        if (t.includes("published") || t.includes("repost")) return "✅";
        if (t.includes("verified") || t.includes("verif")) return "🛡️";
        if (t.includes("expir")) return "⏳";
        return "🔔";
    }

    function renderNotificationItemsHtml(items, maxItems) {
        const list = maxItems ? items.slice(0, maxItems) : items;
        if (!list.length) {
            return `
                <div class="dg-notif-empty">
                    <div class="dg-notif-empty-icon">🔔</div>
                    <div style="font-weight: 700; color: #334155; margin-bottom: 4px;">No notifications yet</div>
                    <div>You're all caught up! Updates on your jobs and applications will appear here.</div>
                </div>
            `;
        }
        return list.map(item => {
            const isUnread = !item.is_read;
            const icon = getNotifIcon(item.event_type);
            const timeStr = formatRelativeTime(item.created_at);
            const targetUrl = item.target_url || "/dashboard/company";
            return `
                <div class="dg-notif-item ${isUnread ? "unread" : ""}" data-notif-id="${item.id}" data-target-url="${escapeHtml(targetUrl)}" onclick="window.dgHandleNotificationClick(${item.id}, '${escapeHtml(targetUrl)}')">
                    <div class="dg-notif-icon">${icon}</div>
                    <div class="dg-notif-body">
                        <div class="dg-notif-title">${escapeHtml(item.title)}</div>
                        <div class="dg-notif-msg">${escapeHtml(item.message)}</div>
                        <div class="dg-notif-time">${escapeHtml(timeStr)}</div>
                    </div>
                    ${isUnread ? '<span class="dg-notif-dot" title="Unread"></span>' : ""}
                </div>
            `;
        }).join("");
    }

    function updateNotificationDomUI() {
        const badges = document.querySelectorAll(".dg-notif-badge");
        badges.forEach(b => {
            if (cachedUnreadCount > 0) {
                b.style.display = "inline-block";
                b.textContent = cachedUnreadCount > 99 ? "99+" : String(cachedUnreadCount);
            } else {
                b.style.display = "none";
                b.textContent = "0";
            }
        });

        const headerCounts = document.querySelectorAll(".dg-notif-header-count");
        headerCounts.forEach(hc => {
            hc.textContent = `${cachedUnreadCount} unread`;
            hc.style.display = cachedUnreadCount > 0 ? "inline-block" : "none";
        });

        const markAllBtns = document.querySelectorAll(".dg-notif-mark-all-btn");
        markAllBtns.forEach(btn => {
            btn.style.display = cachedUnreadCount > 0 ? "inline-block" : "none";
        });

        const dropdownLists = document.querySelectorAll(".dg-notif-list");
        dropdownLists.forEach(listEl => {
            listEl.innerHTML = renderNotificationItemsHtml(cachedNotifications, 8);
        });

        const modalBody = document.getElementById("dgNotifModalBody");
        if (modalBody) {
            modalBody.innerHTML = renderNotificationItemsHtml(cachedNotifications, null);
        }
    }

    async function fetchEmployerNotifications() {
        if (currentAccountType !== "company") return;
        try {
            const res = await fetch("/api/employer/notifications?limit=40");
            if (!res.ok) return;
            const data = await res.json();
            if (data && data.success) {
                cachedNotifications = Array.isArray(data.notifications) ? data.notifications : [];
                cachedUnreadCount = Number(data.unread_count || 0);
                updateNotificationDomUI();
            }
        } catch (err) {
            console.warn("Could not load employer notifications:", err);
        }
    }

    window.dgRefreshEmployerNotifications = fetchEmployerNotifications;

    window.dgMarkAllNotificationsRead = async function (e) {
        if (e) e.stopPropagation();
        try {
            const res = await fetch("/api/employer/notifications/read", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ mark_all: true })
            });
            if (res.ok) {
                cachedNotifications = cachedNotifications.map(n => ({ ...n, is_read: true }));
                cachedUnreadCount = 0;
                updateNotificationDomUI();
            }
        } catch (err) {
            console.warn("Failed to mark all notifications read:", err);
        }
    };

    window.dgHandleNotificationClick = async function (notifId, targetUrl) {
        try {
            const item = cachedNotifications.find(n => Number(n.id) === Number(notifId));
            if (item && !item.is_read) {
                item.is_read = true;
                cachedUnreadCount = Math.max(0, cachedUnreadCount - 1);
                updateNotificationDomUI();
                await fetch("/api/employer/notifications/read", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ notification_id: Number(notifId) })
                });
            }
        } catch (err) {
            console.warn("Error marking notification read:", err);
        }

        // Close open menus / modals
        document.querySelectorAll(".dg-notif-wrap.active").forEach(el => el.classList.remove("active"));
        const modal = document.getElementById("dgNotifModalBackdrop");
        if (modal) modal.classList.remove("open");

        const dest = targetUrl || "/dashboard/company";
        if (typeof window.dgHandleEmployerInternalNav === "function") {
            const handled = window.dgHandleEmployerInternalNav(dest);
            if (handled) return;
        }
        window.location.href = dest;
    };

    window.dgOpenAllNotificationsModal = function (e) {
        if (e) {
            e.preventDefault();
            e.stopPropagation();
        }
        document.querySelectorAll(".dg-notif-wrap.active, .dg-user-dropdown-wrap.active").forEach(el => {
            el.classList.remove("active");
        });

        let backdrop = document.getElementById("dgNotifModalBackdrop");
        if (!backdrop) {
            backdrop = document.createElement("div");
            backdrop.id = "dgNotifModalBackdrop";
            backdrop.className = "dg-notif-modal-backdrop";
            backdrop.innerHTML = `
                <div class="dg-notif-modal" onclick="event.stopPropagation()">
                    <div class="dg-notif-modal-head">
                        <div style="display:flex; align-items:center; gap:10px;">
                            <h3>🔔 All Notifications</h3>
                            <span class="dg-notif-header-count" style="display:none;">0 unread</span>
                        </div>
                        <div style="display:flex; align-items:center; gap:10px;">
                            <button type="button" class="dg-notif-mark-all-btn" onclick="window.dgMarkAllNotificationsRead(event)">Mark all as read</button>
                            <button type="button" class="dg-notif-modal-close" onclick="document.getElementById('dgNotifModalBackdrop').classList.remove('open')">&times;</button>
                        </div>
                    </div>
                    <div class="dg-notif-modal-body" id="dgNotifModalBody"></div>
                </div>
            `;
            backdrop.addEventListener("click", () => backdrop.classList.remove("open"));
            document.body.appendChild(backdrop);
        }
        updateNotificationDomUI();
        backdrop.classList.add("open");
    };

    async function initAuthNav() {
        ensureAuthNavStylesheet();
        try {
            const res = await fetch("/api/auth/me");
            if (!res.ok) {
                return;
            }

            const data = await res.json();
            if (!data || !data.logged_in || !data.user) {
                return;
            }

            const user = data.user;
            const accountType = user.account_type || "individual";
            currentAccountType = accountType;
            const profile = user.profile || {};

            let displayName = "";
            if (accountType === "individual") {
                displayName = (profile.full_name || "").trim() || user.email.split("@")[0];
            } else {
                displayName = (profile.company_name || profile.contact_person || "").trim() || user.email.split("@")[0];
            }

            const initials = displayName
                .split(" ")
                .filter(Boolean)
                .map(part => part[0])
                .slice(0, 2)
                .join("")
                .toUpperCase() || "U";

            const roleBadge = accountType === "individual" ? "👤 Job Seeker" : "🏢 Employer";
            const dashboardUrl = accountType === "individual" ? "/dashboard/individual" : "/dashboard/company";
            const profileSettingsUrl = accountType === "individual" ? "/dashboard/individual#profile" : "/employer/profile";
            const email = user.email || "";

            const navs = document.querySelectorAll(".nav, #mainNav, #employerDashNav");
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

                // Remove existing cluster or dropdown if any
                const existingCluster = nav.querySelector(".dg-auth-nav-cluster");
                if (existingCluster) existingCluster.remove();
                const existingDropdown = nav.querySelector(".dg-user-dropdown-wrap");
                if (existingDropdown) existingDropdown.remove();

                const cluster = document.createElement("div");
                cluster.className = "dg-auth-nav-cluster";

                // 1. Notification Bell (For Employers)
                if (accountType === "company") {
                    const notifWrap = document.createElement("div");
                    notifWrap.className = "dg-notif-wrap";
                    notifWrap.innerHTML = `
                        <button type="button" class="dg-notif-bell-btn" aria-label="Notifications" aria-expanded="false" title="Notifications">
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                                <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path>
                                <path d="M13.73 21a2 2 0 0 1-3.46 0"></path>
                            </svg>
                            <span class="dg-notif-badge" style="display: none;">0</span>
                        </button>
                        <div class="dg-notif-menu" onclick="event.stopPropagation()">
                            <div class="dg-notif-header">
                                <div class="dg-notif-header-title">
                                    <span>🔔 Notifications</span>
                                    <span class="dg-notif-header-count" style="display: none;">0 unread</span>
                                </div>
                                <button type="button" class="dg-notif-mark-all-btn" style="display: none;" onclick="window.dgMarkAllNotificationsRead(event)">Mark all read</button>
                            </div>
                            <div class="dg-notif-list">
                                <div class="dg-notif-empty">Loading notifications...</div>
                            </div>
                            <div class="dg-notif-footer">
                                <button type="button" class="dg-notif-view-all-btn" onclick="window.dgOpenAllNotificationsModal(event)">View All Notifications</button>
                            </div>
                        </div>
                    `;
                    cluster.appendChild(notifWrap);

                    const bellBtn = notifWrap.querySelector(".dg-notif-bell-btn");
                    bellBtn.addEventListener("click", (e) => {
                        e.stopPropagation();
                        const isOpen = notifWrap.classList.contains("active");
                        document.querySelectorAll(".dg-notif-wrap.active, .dg-user-dropdown-wrap.active").forEach(el => {
                            el.classList.remove("active");
                        });
                        if (!isOpen) {
                            notifWrap.classList.add("active");
                            bellBtn.setAttribute("aria-expanded", "true");
                            fetchEmployerNotifications();
                        }
                    });
                }

                // 2. User Profile Pill & Dropdown
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
                            <a href="${dashboardUrl}" class="dg-user-menu-item" data-dg-nav="dashboard">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <rect x="3" y="3" width="7" height="9"></rect>
                                    <rect x="14" y="3" width="7" height="5"></rect>
                                    <rect x="14" y="12" width="7" height="9"></rect>
                                    <rect x="3" y="16" width="7" height="5"></rect>
                                </svg>
                                <span>My Dashboard</span>
                            </a>
                            <a href="${profileSettingsUrl}" class="dg-user-menu-item" data-dg-nav="profile">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                                    <circle cx="12" cy="7" r="4"></circle>
                                </svg>
                                <span>Profile &amp; Settings</span>
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
                            <a href="#notifications" class="dg-user-menu-item" onclick="window.dgOpenAllNotificationsModal(event)">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path>
                                    <path d="M13.73 21a2 2 0 0 1-3.46 0"></path>
                                </svg>
                                <span>Notifications</span>
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

                // Intercept internal employer links when already on dashboard_company.html
                userDropdownWrap.querySelectorAll("a[data-dg-nav]").forEach(link => {
                    link.addEventListener("click", (e) => {
                        if (accountType === "company" && typeof window.dgHandleEmployerInternalNav === "function") {
                            const href = link.getAttribute("href");
                            if (window.dgHandleEmployerInternalNav(href)) {
                                e.preventDefault();
                                userDropdownWrap.classList.remove("active");
                            }
                        }
                    });
                });

                cluster.appendChild(userDropdownWrap);
                nav.appendChild(cluster);

                const pillBtn = userDropdownWrap.querySelector(".dg-user-pill-btn");
                pillBtn.addEventListener("click", (e) => {
                    e.stopPropagation();
                    const isOpen = userDropdownWrap.classList.contains("active");
                    document.querySelectorAll(".dg-notif-wrap.active, .dg-user-dropdown-wrap.active").forEach(el => {
                        el.classList.remove("active");
                        const btn = el.querySelector(".dg-user-pill-btn, .dg-notif-bell-btn");
                        if (btn) btn.setAttribute("aria-expanded", "false");
                    });
                    if (!isOpen) {
                        userDropdownWrap.classList.add("active");
                        pillBtn.setAttribute("aria-expanded", "true");
                    }
                });
            });

            if (accountType === "company") {
                fetchEmployerNotifications();
            }

            // Global click outside to close dropdowns
            document.addEventListener("click", (e) => {
                if (!e.target.closest(".dg-user-dropdown-wrap") && !e.target.closest(".dg-notif-wrap")) {
                    document.querySelectorAll(".dg-notif-wrap.active, .dg-user-dropdown-wrap.active").forEach(el => {
                        el.classList.remove("active");
                        const btn = el.querySelector(".dg-user-pill-btn, .dg-notif-bell-btn");
                        if (btn) btn.setAttribute("aria-expanded", "false");
                    });
                }
            });

            // Escape key to close
            document.addEventListener("keydown", (e) => {
                if (e.key === "Escape") {
                    document.querySelectorAll(".dg-notif-wrap.active, .dg-user-dropdown-wrap.active").forEach(el => {
                        el.classList.remove("active");
                        const btn = el.querySelector(".dg-user-pill-btn, .dg-notif-bell-btn");
                        if (btn) btn.setAttribute("aria-expanded", "false");
                    });
                    const modal = document.getElementById("dgNotifModalBackdrop");
                    if (modal) modal.classList.remove("open");
                }
            });

        } catch (err) {
            console.error("Auth navbar initialization error:", err);
        }
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
