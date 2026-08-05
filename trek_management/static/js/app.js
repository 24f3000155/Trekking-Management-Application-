/**
 * Trek Management System — Shared JavaScript (app.js)
 *
 * Features:
 *   1. Mobile sidebar toggle (off-canvas)
 *   2. Auto-dismiss flash alerts
 *   3. Confirmation dialogs for destructive actions
 *   4. Loading button spinner state
 *   5. Password strength indicator
 *   6. CSRF token injection for AJAX
 *   7. Show/hide password toggle
 */

document.addEventListener('DOMContentLoaded', function () {

    // ── 1. Sidebar Toggle ──────────────────────────────
    const sidebarToggle = document.getElementById('sidebarToggle');
    const sidebar = document.getElementById('tmSidebar');
    const backdrop = document.getElementById('sidebarBackdrop');

    if (sidebarToggle && sidebar) {
        sidebarToggle.addEventListener('click', function (e) {
            e.stopPropagation();
            sidebar.classList.toggle('show');
            if (backdrop) backdrop.classList.toggle('show');
        });
    }

    if (backdrop) {
        backdrop.addEventListener('click', function () {
            sidebar.classList.remove('show');
            backdrop.classList.remove('show');
        });
    }

    // Close sidebar on nav link click (mobile)
    document.querySelectorAll('.tm-sidebar .nav-link').forEach(function (link) {
        link.addEventListener('click', function () {
            if (window.innerWidth <= 992 && sidebar) {
                sidebar.classList.remove('show');
                if (backdrop) backdrop.classList.remove('show');
            }
        });
    });


    // ── 2. Auto-dismiss Flash Alerts ──────────────────────
    document.querySelectorAll('.alert-dismissible').forEach(function (alert) {
        setTimeout(function () {
            alert.classList.add('alert-dismissing');
            setTimeout(function () {
                if (alert.parentNode) alert.parentNode.removeChild(alert);
            }, 400);
        }, 5000);
    });


    // ── 3. Confirmation Dialogs ──────────────────────────
    // Usage: <form data-confirm="Are you sure you want to delete this?">
    document.querySelectorAll('[data-confirm]').forEach(function (el) {
        el.addEventListener('submit', function (e) {
            e.preventDefault();
            var message = el.getAttribute('data-confirm');
            showConfirmDialog(message, function () {
                // Re-submit without triggering the event listener
                el.removeAttribute('data-confirm');
                el.submit();
            });
        });
    });

    // Confirmation dialog for links
    document.querySelectorAll('a[data-confirm]').forEach(function (el) {
        el.addEventListener('click', function (e) {
            e.preventDefault();
            var message = el.getAttribute('data-confirm');
            var href = el.getAttribute('href');
            showConfirmDialog(message, function () {
                window.location.href = href;
            });
        });
    });


    // ── 4. Loading Buttons ──────────────────────────────
    // Forms with data-loading-text attribute on submit button
    document.querySelectorAll('form[data-loading]').forEach(function (form) {
        form.addEventListener('submit', function () {
            var btn = form.querySelector('button[type="submit"]');
            if (btn) {
                btn.setAttribute('data-loading', 'true');
                btn.disabled = true;
            }
        });
    });


    // ── 5. Password Strength Indicator ────────────────────
    document.querySelectorAll('.password-strength').forEach(function (input) {
        var container = input.closest('.mb-3') || input.parentElement;
        // Create bar if not already present
        if (!container.querySelector('.password-strength-bar')) {
            var barWrapper = document.createElement('div');
            barWrapper.className = 'password-strength-bar';
            barWrapper.innerHTML = '<div class="bar-fill"></div>';
            container.appendChild(barWrapper);

            var textEl = document.createElement('div');
            textEl.className = 'password-strength-text';
            container.appendChild(textEl);
        }

        input.addEventListener('input', function () {
            var val = input.value;
            var score = 0;
            var label = '';
            var color = '';

            if (val.length >= 8) score++;
            if (val.length >= 12) score++;
            if (/[A-Z]/.test(val)) score++;
            if (/[a-z]/.test(val)) score++;
            if (/\d/.test(val)) score++;
            if (/[!@#$%^&*(),.?":{}|<>]/.test(val)) score++;

            if (val.length === 0) {
                label = '';
                color = 'transparent';
            } else if (score <= 2) {
                label = 'Weak';
                color = '#ef476f';
            } else if (score <= 4) {
                label = 'Fair';
                color = '#f8961e';
            } else {
                label = 'Strong';
                color = '#06d6a0';
            }

            var fill = container.querySelector('.bar-fill');
            var text = container.querySelector('.password-strength-text');
            if (fill) {
                fill.style.width = val.length === 0 ? '0' : (Math.min(score / 6, 1) * 100) + '%';
                fill.style.background = color;
            }
            if (text) {
                text.textContent = label;
                text.style.color = color;
            }
        });
    });


    // ── 6. CSRF Token Injection for AJAX ─────────────────
    var csrfMeta = document.querySelector('meta[name="csrf-token"]');
    if (csrfMeta) {
        var csrfToken = csrfMeta.getAttribute('content');
        // Intercept XMLHttpRequest
        var origOpen = XMLHttpRequest.prototype.open;
        XMLHttpRequest.prototype.open = function () {
            var result = origOpen.apply(this, arguments);
            var method = arguments[0].toUpperCase();
            if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
                this.setRequestHeader('X-CSRFToken', csrfToken);
            }
            return result;
        };

        // Intercept fetch
        var origFetch = window.fetch;
        window.fetch = function (url, options) {
            options = options || {};
            var method = (options.method || 'GET').toUpperCase();
            if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
                options.headers = options.headers || {};
                if (options.headers instanceof Headers) {
                    if (!options.headers.has('X-CSRFToken')) {
                        options.headers.set('X-CSRFToken', csrfToken);
                    }
                } else {
                    if (!options.headers['X-CSRFToken']) {
                        options.headers['X-CSRFToken'] = csrfToken;
                    }
                }
            }
            return origFetch.call(this, url, options);
        };
    }


    // ── 7. Show/Hide Password Toggle ─────────────────────
    document.querySelectorAll('.password-toggle').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var target = document.getElementById(btn.getAttribute('data-target'));
            if (target) {
                var isPassword = target.type === 'password';
                target.type = isPassword ? 'text' : 'password';
                var icon = btn.querySelector('i');
                if (icon) {
                    icon.className = isPassword ? 'bi bi-eye-slash' : 'bi bi-eye';
                }
            }
        });
    });

});


/**
 * Show a custom confirmation dialog.
 * @param {string} message  — The message to display
 * @param {function} onConfirm — Callback on confirm
 */
function showConfirmDialog(message, onConfirm) {
    // Remove any existing dialog
    var existing = document.querySelector('.confirm-overlay');
    if (existing) existing.remove();

    var overlay = document.createElement('div');
    overlay.className = 'confirm-overlay';
    overlay.innerHTML =
        '<div class="confirm-dialog">' +
            '<div class="text-center mb-3">' +
                '<i class="bi bi-exclamation-triangle-fill text-warning" style="font-size:2.5rem;"></i>' +
            '</div>' +
            '<h5 class="text-center mb-3">Confirm Action</h5>' +
            '<p class="text-center text-muted mb-4">' + message + '</p>' +
            '<div class="d-flex gap-2 justify-content-center">' +
                '<button class="btn btn-outline-secondary px-4 confirm-cancel">Cancel</button>' +
                '<button class="btn btn-danger px-4 confirm-yes">Yes, Proceed</button>' +
            '</div>' +
        '</div>';

    document.body.appendChild(overlay);

    overlay.querySelector('.confirm-cancel').addEventListener('click', function () {
        overlay.remove();
    });

    overlay.querySelector('.confirm-yes').addEventListener('click', function () {
        overlay.remove();
        if (onConfirm) onConfirm();
    });

    // Close on backdrop click
    overlay.addEventListener('click', function (e) {
        if (e.target === overlay) overlay.remove();
    });

    // Close on Escape key
    var escHandler = function (e) {
        if (e.key === 'Escape') {
            overlay.remove();
            document.removeEventListener('keydown', escHandler);
        }
    };
    document.addEventListener('keydown', escHandler);
}
