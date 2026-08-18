document.addEventListener('DOMContentLoaded', () => {
    // Mobile navigation toggle
    const menuToggle = document.getElementById('menu-toggle');
    const navMenu = document.getElementById('nav-menu');
    
    if (menuToggle && navMenu) {
        menuToggle.addEventListener('click', () => {
            navMenu.classList.toggle('open');
            const isOpen = navMenu.classList.contains('open');
            menuToggle.innerHTML = isOpen ? '✕' : '☰';
        });
    }
    
    // Contact form AJAX submission
    const contactForm = document.getElementById('contact-form');
    if (contactForm) {
        contactForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const submitBtn = contactForm.querySelector('button[type="submit"]');
            const originalText = submitBtn.innerText;
            submitBtn.innerText = 'Sending...';
            submitBtn.disabled = true;
            
            const formData = new FormData(contactForm);
            const data = {};
            formData.forEach((value, key) => { data[key] = value; });
            
            try {
                const response = await fetch('/api/contact', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(data)
                });
                
                const result = await response.json();
                
                const messageAlert = document.getElementById('contact-alert');
                if (messageAlert) {
                    if (response.ok) {
                        messageAlert.className = 'alert alert-success';
                        messageAlert.innerText = 'Thank you! Your message has been sent successfully.';
                        contactForm.reset();
                    } else {
                        messageAlert.className = 'alert alert-error';
                        messageAlert.innerText = result.error || 'Failed to send message. Please try again.';
                    }
                    messageAlert.style.display = 'block';
                }
            } catch (error) {
                console.error('Error submitting form:', error);
                const messageAlert = document.getElementById('contact-alert');
                if (messageAlert) {
                    messageAlert.className = 'alert alert-error';
                    messageAlert.innerText = 'An error occurred. Please try again.';
                    messageAlert.style.display = 'block';
                }
            } finally {
                submitBtn.innerText = originalText;
                submitBtn.disabled = false;
            }
        });
    }
});
