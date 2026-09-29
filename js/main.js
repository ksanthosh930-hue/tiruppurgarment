document.addEventListener("DOMContentLoaded", () => {
    // --- Configurable Constants & Fallbacks ---
    const API_BASE = ""; // Relative to server
    
    // Toast helper
    function showToast(message, isSuccess = true) {
        const toast = document.getElementById("toast");
        if (!toast) return;
        
        toast.className = `toast-notify ${isSuccess ? 'toast-success' : 'toast-error'}`;
        toast.textContent = message;
        toast.style.display = "flex";
        
        setTimeout(() => {
            toast.style.display = "none";
        }, 5000);
    }

    // --- Dynamic Loading Functions ---

    async function loadSettings() {
        try {
            const res = await fetch(`${API_BASE}/api/public/settings`);
            if (!res.ok) throw new Error("Failed to fetch settings");
            const settings = await res.json();
            
            // SEO update
            if (settings.seo_meta_title) {
                document.title = settings.seo_meta_title;
                const metaTitle = document.getElementById("metaTitle");
                if (metaTitle) metaTitle.textContent = settings.seo_meta_title;
            }
            if (settings.seo_meta_description) {
                const metaDesc = document.querySelector('meta[name="description"]');
                if (metaDesc) metaDesc.setAttribute("content", settings.seo_meta_description);
            }
            
            // Site content updates
            if (settings.contact_email) {
                document.getElementById("contactEmail").textContent = settings.contact_email;
                document.getElementById("footerEmail").textContent = `✉ ${settings.contact_email}`;
            }
            if (settings.contact_phone) {
                document.getElementById("contactPhone").textContent = settings.contact_phone;
                document.getElementById("footerPhone").textContent = `📞 ${settings.contact_phone}`;
            }
            if (settings.address) {
                document.getElementById("contactAddress").textContent = settings.address;
                document.getElementById("footerAddress").textContent = `📍 ${settings.address}`;
            }
            if (settings.footer_text) {
                document.getElementById("footerCopyright").textContent = settings.footer_text;
            }
            if (settings.tagline) {
                document.getElementById("footerTagline").textContent = settings.tagline;
            }
            if (settings.logo_url) {
                document.getElementById("navLogo").src = settings.logo_url;
                document.getElementById("footerLogo").src = settings.logo_url;
            }
            
            // Social icons
            const socialWrap = document.getElementById("footerSocials");
            if (socialWrap) {
                socialWrap.innerHTML = "";
                if (settings.social_facebook) {
                    socialWrap.insertAdjacentHTML("beforeend", `<a href="${settings.social_facebook}" target="_blank">f</a>`);
                }
                if (settings.social_linkedin) {
                    socialWrap.insertAdjacentHTML("beforeend", `<a href="${settings.social_linkedin}" target="_blank">in</a>`);
                }
                if (settings.social_youtube) {
                    socialWrap.insertAdjacentHTML("beforeend", `<a href="${settings.social_youtube}" target="_blank">▶</a>`);
                }
                if (settings.social_instagram) {
                    socialWrap.insertAdjacentHTML("beforeend", `<a href="${settings.social_instagram}" target="_blank">◎</a>`);
                }
            }
        } catch (err) {
            console.error("Settings fallback applied:", err);
        }
    }

    async function loadHero() {
        try {
            const res = await fetch(`${API_BASE}/api/public/sections/hero`);
            if (!res.ok) return;
            const data = await res.json();
            
            const eyebrowEl = document.getElementById("heroEyebrow");
            if (eyebrowEl && data.eyebrow) eyebrowEl.textContent = data.eyebrow;
            
            const titleEl = document.getElementById("heroTitle");
            if (titleEl && data.heading && data.override_jobs_hero) titleEl.innerHTML = data.heading;
            
            const descEl = document.getElementById("heroDescription");
            if (descEl && data.description && data.override_jobs_hero) descEl.textContent = data.description;
            
            const imgEl = document.getElementById("heroImage");
            if (imgEl && data.image_url) imgEl.src = data.image_url;
            
            if (data.primary_btn_text) {
                const btn = document.getElementById("heroPrimaryBtn");
                if (btn) {
                    btn.textContent = data.primary_btn_text;
                    btn.href = data.primary_btn_url || "/jobs";
                }
            }
            if (data.secondary_btn_text) {
                const btn = document.getElementById("heroSecondaryBtn");
                if (btn) {
                    btn.textContent = data.secondary_btn_text;
                    btn.href = data.secondary_btn_url || "/post-a-job";
                }
            }
            
            // Render highlights
            const highlightsWrap = document.getElementById("heroHighlights");
            if (highlightsWrap && data.highlights) {
                highlightsWrap.innerHTML = "";
                data.highlights.forEach(h => {
                    highlightsWrap.insertAdjacentHTML("beforeend", `
                        <div class="highlight-item">
                            <span class="bullet">✓</span> <span>${h}</span>
                        </div>
                    `);
                });
            }
        } catch (err) {
            // Silently retain static jobs hero
        }
    }

    async function loadAbout() {
        try {
            const res = await fetch(`${API_BASE}/api/public/sections/about`);
            if (!res.ok) throw new Error("Failed to fetch about");
            const data = await res.json();
            
            if (data.heading) document.getElementById("aboutTitle").textContent = data.heading;
            if (data.description) document.getElementById("aboutDescription").textContent = data.description;
            if (data.image_url) document.getElementById("aboutImage").src = data.image_url;
            
            // Render points
            const pointsWrap = document.getElementById("aboutPoints");
            if (pointsWrap && data.key_points) {
                pointsWrap.innerHTML = "";
                data.key_points.forEach(p => {
                    pointsWrap.insertAdjacentHTML("beforeend", `
                        <div><span>✓</span> ${p}</div>
                    `);
                });
            }
        } catch (err) {
            console.error("About fallback applied:", err);
        }
    }

    async function loadTools() {
        const wrap = document.getElementById("toolsList");
        if (!wrap) return;
        
        try {
            const res = await fetch(`${API_BASE}/api/public/tools`);
            if (!res.ok) throw new Error("Failed to fetch tools");
            const tools = await res.json();
            
            wrap.innerHTML = "";
            tools.forEach(t => {
                const isComing = t.status === "COMING_SOON";
                const badgeText = isComing ? "Coming Soon" : "Available";
                const badgeClass = isComing ? "badge-coming" : "badge-active";
                const btnClass = isComing ? "tool-btn-disabled" : "tool-btn-primary";
                const btnText = isComing ? "Coming Soon" : "Open SAM Calculator";
                
                wrap.insertAdjacentHTML("beforeend", `
                    <div class="tool-card ${isComing ? 'coming-soon' : ''}">
                        <div>
                            <span class="tool-badge ${badgeClass}">${badgeText}</span>
                            <h3><span>${t.icon || '⚒'}</span> ${t.name}</h3>
                            <p>${t.description}</p>
                        </div>
                        <div>
                            ${isComing 
                                ? `<span class="tool-btn ${btnClass}">${btnText}</span>`
                                : `<a href="${t.url}" target="_blank" class="tool-btn ${btnClass}">${btnText}</a>`
                            }
                        </div>
                    </div>
                `);
            });
        } catch (err) {
            console.error("Tools fallback applied:", err);
        }
    }

    async function loadServices() {
        const wrap = document.getElementById("servicesList");
        if (!wrap) return;
        
        try {
            const res = await fetch(`${API_BASE}/api/public/services`);
            if (!res.ok) throw new Error("Failed to fetch services");
            const services = await res.json();
            
            wrap.innerHTML = "";
            services.forEach(s => {
                wrap.insertAdjacentHTML("beforeend", `
                    <div class="service-card">
                        <div class="service-icon">${s.icon || '⚙'}</div>
                        <h3>${s.name}</h3>
                        <p>${s.short_description}</p>
                    </div>
                `);
            });
        } catch (err) {
            console.error("Services fallback applied:", err);
        }
    }

    async function loadLatestJobs() {
        const wrap = document.getElementById("latestJobsGrid");
        if (!wrap) return;

        try {
            const res = await fetch(`${API_BASE}/api/public/jobs?limit=4`);
            if (!res.ok) return;
            const data = await res.json();
            if (!data || !data.jobs || !data.jobs.length) return;

            wrap.innerHTML = "";
            data.jobs.forEach(job => {
                const title = escapeHtml(job.title || "Garment Position");
                const company = escapeHtml(job.company_name || "Garment Manufacturing Unit");
                const location = escapeHtml(job.location || "Tirupur, Tamil Nadu");
                const dept = escapeHtml(job.department || "Garment Operations");
                const jobType = escapeHtml(job.job_type || "Full Time");
                const slug = job.slug || "";
                const detailUrl = slug ? `/jobs/${slug}` : `/jobs`;
                
                // Format relative date or published date
                let dateStr = "Recent";
                if (job.published_at) {
                    try {
                        const d = new Date(job.published_at);
                        dateStr = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
                    } catch (e) {}
                }

                wrap.insertAdjacentHTML("beforeend", `
                    <a href="${detailUrl}" class="home-job-card">
                        <div>
                            <div class="job-card-top">
                                <div>
                                    <h3 class="job-card-title">${title}</h3>
                                    <div class="job-card-company">${company}</div>
                                </div>
                                <span class="job-card-dept-tag">${dept}</span>
                            </div>
                            <div class="job-card-meta">
                                <span class="job-meta-item">📍 ${location}</span>
                                <span class="job-meta-item">💼 ${jobType}</span>
                            </div>
                        </div>
                        <div class="job-card-bottom">
                            <span class="job-card-date">Posted ${dateStr}</span>
                            <span class="job-card-cta">View Details &rsaquo;</span>
                        </div>
                    </a>
                `);
            });
        } catch (err) {
            // Retain static initial cards
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

    // --- Contact Form Submission ---

    const form = document.getElementById("enquiryForm");
    if (form) {
        form.addEventListener("submit", async (e) => {
            e.preventDefault();
            
            const submitBtn = document.getElementById("submitBtn");
            const originalText = submitBtn.textContent;
            submitBtn.textContent = "Sending...";
            submitBtn.disabled = true;
            
            const formData = new FormData(form);
            
            try {
                const res = await fetch(`${API_BASE}/api/public/enquiries`, {
                    method: "POST",
                    body: formData
                });
                
                const data = await res.json();
                if (res.ok && data.success) {
                    showToast(data.message, true);
                    form.reset();
                } else {
                    showToast(data.message || "Failed to submit enquiry. Please try again.", false);
                }
            } catch (err) {
                console.error("Error submitting enquiry:", err);
                showToast("Failed to connect to the server. Please try again later.", false);
            } finally {
                submitBtn.textContent = originalText;
                submitBtn.disabled = false;
            }
        });
    }

    // --- Mobile Menu Toggle ---
    const toggle = document.querySelector(".menu-toggle");
    const nav = document.getElementById("mainNav");
    if (toggle && nav) {
        toggle.addEventListener("click", () => {
            const open = nav.classList.toggle("open");
            toggle.setAttribute("aria-expanded", String(open));
        });

        nav.querySelectorAll("a").forEach(link => {
            link.addEventListener("click", () => nav.classList.remove("open"));
        });
    }

    // --- Bootstrapping ---
    Promise.all([
        loadSettings(),
        loadHero(),
        loadLatestJobs(),
        loadAbout(),
        loadTools(),
        loadServices()
    ]).catch(err => {
        console.error("Public rendering initialization error:", err);
    });
});
