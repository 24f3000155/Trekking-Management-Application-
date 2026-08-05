/**
 * validation.js
 *
 * Client-side validation library for Bootstrap 5 forms.
 * Provides real-time feedback using 'is-valid' and 'is-invalid' classes.
 */

class FormValidator {
    constructor(formId, config = {}) {
        this.form = document.getElementById(formId);
        if (!this.form) return;
        
        this.config = config;
        this.preventEmpty = config.preventEmpty !== false;
        
        this.init();
    }

    init() {
        // Disable default browser validation UI
        this.form.setAttribute('novalidate', '');

        // Add event listeners to all inputs
        const inputs = this.form.querySelectorAll('input, select, textarea');
        inputs.forEach(input => {
            // Validate on blur
            input.addEventListener('blur', () => this.validateInput(input));
            // Validate on change (for selects and checkboxes)
            input.addEventListener('change', () => this.validateInput(input));
            // Remove error styling on input
            input.addEventListener('input', () => {
                input.classList.remove('is-invalid');
                const feedback = input.nextElementSibling;
                if (feedback && feedback.classList.contains('invalid-feedback')) {
                    feedback.style.display = 'none';
                }
            });
        });

        // Handle form submission
        this.form.addEventListener('submit', (e) => {
            let isValid = true;
            let firstInvalid = null;

            inputs.forEach(input => {
                if (!this.validateInput(input)) {
                    isValid = false;
                    if (!firstInvalid) firstInvalid = input;
                }
            });

            if (!isValid) {
                e.preventDefault();
                e.stopPropagation();
                if (firstInvalid) firstInvalid.focus();
            }
        });
    }

    validateInput(input) {
        // Skip hidden or disabled inputs
        if (input.type === 'hidden' || input.disabled) return true;

        let isValid = true;
        let errorMessage = '';
        
        // 1. Required check
        if (input.required && !input.value.trim()) {
            isValid = false;
            errorMessage = 'This field is required.';
        }
        
        // 2. Type-specific validation (only if not empty or if it's required)
        if (isValid && input.value.trim()) {
            if (input.type === 'email') {
                const pattern = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
                if (!pattern.test(input.value.trim())) {
                    isValid = false;
                    errorMessage = 'Please enter a valid email address.';
                }
            } else if (input.type === 'tel' || input.classList.contains('phone-input')) {
                const pattern = /^\+?[\d\s\-\(\)]{7,20}$/;
                if (!pattern.test(input.value.trim())) {
                    isValid = false;
                    errorMessage = 'Please enter a valid phone number.';
                }
            } else if (input.type === 'password' && input.classList.contains('password-strength')) {
                if (input.value.length < 6) {
                    isValid = false;
                    errorMessage = 'Password must be at least 6 characters long.';
                }
            } else if (input.type === 'number') {
                const val = parseFloat(input.value);
                if (input.hasAttribute('min') && val < parseFloat(input.getAttribute('min'))) {
                    isValid = false;
                    errorMessage = `Value must be at least ${input.getAttribute('min')}.`;
                }
                if (input.hasAttribute('max') && val > parseFloat(input.getAttribute('max'))) {
                    isValid = false;
                    errorMessage = `Value must not exceed ${input.getAttribute('max')}.`;
                }
            }
        }
        
        // 3. Custom config validation
        if (isValid && this.config.customRules && this.config.customRules[input.name]) {
            const ruleObj = this.config.customRules[input.name];
            const ruleResult = ruleObj.validate(input.value, this.form);
            if (!ruleResult.valid) {
                isValid = false;
                errorMessage = ruleResult.message;
            }
        }

        this.setValidationState(input, isValid, errorMessage);
        return isValid;
    }

    setValidationState(input, isValid, errorMessage) {
        let feedbackEl = input.nextElementSibling;
        
        // Ensure feedback element exists
        if (!feedbackEl || !feedbackEl.classList.contains('invalid-feedback')) {
            feedbackEl = document.createElement('div');
            feedbackEl.className = 'invalid-feedback';
            input.parentNode.insertBefore(feedbackEl, input.nextSibling);
        }

        if (isValid) {
            input.classList.remove('is-invalid');
            if (input.value.trim()) {
                input.classList.add('is-valid');
            }
            feedbackEl.style.display = 'none';
        } else {
            input.classList.remove('is-valid');
            input.classList.add('is-invalid');
            feedbackEl.textContent = errorMessage;
            feedbackEl.style.display = 'block';
        }
    }
}

// Auto-initialize standard forms if marked
document.addEventListener('DOMContentLoaded', () => {
    const autoForms = document.querySelectorAll('.needs-validation');
    autoForms.forEach(form => {
        new FormValidator(form.id || form.getAttribute('name') || form.className);
        // Ensure it has an ID, if not auto-assign one so class can mount properly
        if (!form.id) {
            form.id = 'form-' + Math.random().toString(36).substr(2, 9);
            new FormValidator(form.id);
        } else {
            new FormValidator(form.id);
        }
    });
});
