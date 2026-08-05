/**
 * api-client.js
 *
 * Lightweight API client for making fetch requests with automatic retries,
 * error handling, and JSON parsing.
 */

class ApiClient {
    /**
     * @param {string} baseUrl - Base URL for API requests. Default is empty string as we use relative URLs.
     */
    constructor(baseUrl = '') {
        this.baseUrl = baseUrl;
        this.activeRequests = new Set();
    }

    /**
     * Shows a loading spinner on the specified container if elementId is provided.
     */
    _showLoading(elementId) {
        if (!elementId) return;
        const el = document.getElementById(elementId);
        if (el) {
            this.activeRequests.add(elementId);
            const spinner = document.createElement('div');
            spinner.className = 'spinner-border spinner-border-sm text-primary ms-2 api-loading-spinner';
            spinner.setAttribute('role', 'status');
            el.appendChild(spinner);
        }
    }

    /**
     * Hides the loading spinner.
     */
    _hideLoading(elementId) {
        if (!elementId) return;
        const el = document.getElementById(elementId);
        if (el && this.activeRequests.has(elementId)) {
            const spinners = el.querySelectorAll('.api-loading-spinner');
            spinners.forEach(s => s.remove());
            this.activeRequests.delete(elementId);
        }
    }

    /**
     * Performs a fetch request with retry logic and standard error handling.
     */
    async request(url, options = {}, retries = 3, backoff = 300, loadingElementId = null) {
        const fullUrl = this.baseUrl + url;
        
        // Setup default headers for JSON
        const headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            ...options.headers
        };

        const fetchOptions = {
            ...options,
            headers
        };

        this._showLoading(loadingElementId);

        try {
            const response = await fetch(fullUrl, fetchOptions);
            const isJson = response.headers.get('content-type')?.includes('application/json');
            
            let data = null;
            if (isJson) {
                data = await response.json();
            } else {
                data = await response.text();
            }

            if (!response.ok) {
                // If it's a 500 or rate limit (429), we might want to retry
                if ((response.status >= 500 || response.status === 429) && retries > 0) {
                    console.warn(`API request failed with status ${response.status}. Retrying in ${backoff}ms...`);
                    await new Promise(resolve => setTimeout(resolve, backoff));
                    return this.request(url, options, retries - 1, backoff * 2, loadingElementId);
                }
                
                throw {
                    status: response.status,
                    data: data,
                    message: data?.message || response.statusText || 'API Request Failed'
                };
            }

            return data;
        } catch (error) {
            // Network errors (e.g. CORS, offline)
            if (error.name === 'TypeError' && retries > 0) {
                console.warn(`Network error. Retrying in ${backoff}ms...`);
                await new Promise(resolve => setTimeout(resolve, backoff));
                return this.request(url, options, retries - 1, backoff * 2, loadingElementId);
            }
            throw error;
        } finally {
            this._hideLoading(loadingElementId);
        }
    }

    async get(url, options = {}, loadingElementId = null) {
        return this.request(url, { ...options, method: 'GET' }, 3, 300, loadingElementId);
    }

    async post(url, data, options = {}, loadingElementId = null) {
        return this.request(url, {
            ...options,
            method: 'POST',
            body: JSON.stringify(data)
        }, 1, 300, loadingElementId); // Fewer retries for state-changing operations
    }

    async put(url, data, options = {}, loadingElementId = null) {
        return this.request(url, {
            ...options,
            method: 'PUT',
            body: JSON.stringify(data)
        }, 1, 300, loadingElementId);
    }

    async delete(url, options = {}, loadingElementId = null) {
        return this.request(url, { ...options, method: 'DELETE' }, 1, 300, loadingElementId);
    }
}

// Global instance for reuse
window.api = new ApiClient();
