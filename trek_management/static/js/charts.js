/**
 * charts.js
 *
 * Manages Chart.js instances and loads data from the API endpoints.
 */

class ChartManager {
    constructor() {
        this.charts = {}; // Store chart instances
        
        // Default configurations
        Chart.defaults.font.family = "'Inter', 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif";
        Chart.defaults.color = '#6c757d';
        
        // Standard chart options
        this.defaultOptions = {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { boxWidth: 12, padding: 15 }
                },
                tooltip: {
                    backgroundColor: 'rgba(33, 37, 41, 0.9)',
                    padding: 10,
                    cornerRadius: 4,
                    displayColors: true
                }
            }
        };
    }

    /**
     * Creates and renders a chart on the given canvas element.
     */
    async renderChart(canvasId, endpoint, type, customOptions = {}) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return;

        const container = canvas.parentElement;
        this._showLoading(container);

        try {
            // Fetch data from API
            const response = await window.api.get(endpoint);
            if (!response || !response.success || !response.data) {
                throw new Error("Invalid format returned from chart API.");
            }

            const chartData = response.data;
            
            // Destroy existing chart if it exists
            if (this.charts[canvasId]) {
                this.charts[canvasId].destroy();
            }

            // Merge options
            const options = { ...this.defaultOptions, ...customOptions };
            
            // For line charts, add some default dataset styling
            if (type === 'line' && chartData.datasets) {
                chartData.datasets.forEach(ds => {
                    if (!ds.borderColor) ds.borderColor = '#0d6efd';
                    if (!ds.backgroundColor) ds.backgroundColor = 'rgba(13, 110, 253, 0.1)';
                    ds.borderWidth = 2;
                    ds.tension = 0.3; // Make it smooth
                    ds.fill = true;
                });
            }

            this._hideLoading(container);

            this.charts[canvasId] = new Chart(canvas.getContext('2d'), {
                type: type,
                data: chartData,
                options: options
            });
            
        } catch (error) {
            console.error(`Failed to load chart data for ${canvasId}:`, error);
            this._showError(container, error.message || "Failed to load chart data");
        }
    }

    _showLoading(container) {
        if (!container) return;
        let loader = container.querySelector('.chart-loader');
        if (!loader) {
            loader = document.createElement('div');
            loader.className = 'chart-loader justify-content-center align-items-center position-absolute w-100 h-100 top-0 start-0 bg-white bg-opacity-75';
            loader.innerHTML = '<div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading...</span></div>';
            container.style.position = 'relative';
            container.appendChild(loader);
        }
        loader.classList.remove('d-none');
        loader.classList.add('d-flex');
    }

    _hideLoading(container) {
        if (!container) return;
        const loader = container.querySelector('.chart-loader');
        if (loader) {
            loader.classList.remove('d-flex');
            loader.classList.add('d-none');
        }
    }

    _showError(container, message) {
        this._hideLoading(container);
        let errEl = container.querySelector('.chart-error');
        if (!errEl) {
            errEl = document.createElement('div');
            errEl.className = 'chart-error d-flex justify-content-center align-items-center position-absolute w-100 h-100 top-0 start-0 bg-light text-muted small px-3 text-center';
            container.style.position = 'relative';
            container.appendChild(errEl);
        }
        errEl.innerHTML = `<i class="bi bi-exclamation-triangle me-2 text-warning"></i> ${message}`;
        errEl.style.display = 'flex';
        const canvas = container.querySelector('canvas');
        if (canvas) canvas.style.opacity = '0.1';
    }
}

// Global instance
window.chartManager = new ChartManager();
