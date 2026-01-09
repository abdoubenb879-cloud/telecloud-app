/**
 * CloudVault Modal System
 * Replaces native alert() and confirm() with custom UI
 */

const Modal = {
    /**
     * Shows a confirmation modal
     * @param {string} title - Modal title
     * @param {string} message - Modal body text
     * @param {string} confirmText - Text for confirm button (default: "Confirm")
     * @param {string} cancelText - Text for cancel button (default: "Cancel")
     * @param {boolean} isDanger - If true, confirm button will be red
     * @returns {Promise<boolean>} - Resolves true if confirmed, false if cancelled
     */
    confirm: function (title, message, confirmText = "Confirm", cancelText = "Cancel", isDanger = false) {
        return new Promise((resolve) => {
            // Create modal HTML
            const modalId = 'modal-' + Date.now();
            const modalHtml = `
                <div class="modal-overlay active" id="${modalId}" style="z-index: 9999;">
                    <div class="modal-content animate-scale-up" style="max-width: 400px;">
                        <div class="modal-header">
                            <h3 class="modal-title">${title}</h3>
                            <button class="modal-close" id="close-${modalId}">
                                <i class="fas fa-times"></i>
                            </button>
                        </div>
                        <div class="modal-body mb-6">
                            <p class="text-secondary">${message}</p>
                        </div>
                        <div class="flex gap-3 justify-end">
                            <button class="btn btn-secondary" id="cancel-${modalId}">${cancelText}</button>
                            <button class="btn ${isDanger ? 'btn-danger' : 'btn-primary'}" id="confirm-${modalId}">${confirmText}</button>
                        </div>
                    </div>
                </div>
            `;

            // Append to body
            document.body.insertAdjacentHTML('beforeend', modalHtml);

            const modal = document.getElementById(modalId);
            const confirmBtn = document.getElementById(`confirm-${modalId}`);
            const cancelBtn = document.getElementById(`cancel-${modalId}`);
            const closeBtn = document.getElementById(`close-${modalId}`);

            // cleanup function
            const cleanup = () => {
                modal.classList.remove('active');
                setTimeout(() => modal.remove(), 200); // Wait for transition
            };

            // Event listeners
            confirmBtn.onclick = () => {
                cleanup();
                resolve(true);
            };

            cancelBtn.onclick = () => {
                cleanup();
                resolve(false);
            };

            closeBtn.onclick = () => {
                cleanup();
                resolve(false);
            };

            // Close on click outside
            modal.onclick = (e) => {
                if (e.target === modal) {
                    cleanup();
                    resolve(false);
                }
            };

            // Focus confirm button for a11y
            confirmBtn.focus();
        });
    },

    /**
     * Shows an alert modal
     * @param {string} title 
     * @param {string} message 
     * @returns {Promise<void>}
     */
    alert: function (title, message) {
        return new Promise((resolve) => {
            const modalId = 'modal-' + Date.now();
            const modalHtml = `
                <div class="modal-overlay active" id="${modalId}" style="z-index: 9999;">
                    <div class="modal-content animate-scale-up" style="max-width: 400px;">
                        <div class="modal-header">
                            <h3 class="modal-title">${title}</h3>
                            <button class="modal-close" id="close-${modalId}">
                                <i class="fas fa-times"></i>
                            </button>
                        </div>
                        <div class="modal-body mb-6">
                            <p class="text-secondary">${message}</p>
                        </div>
                        <div class="flex gap-3 justify-end">
                            <button class="btn btn-primary" id="ok-${modalId}">OK</button>
                        </div>
                    </div>
                </div>
            `;

            document.body.insertAdjacentHTML('beforeend', modalHtml);

            const modal = document.getElementById(modalId);
            const okBtn = document.getElementById(`ok-${modalId}`);
            const closeBtn = document.getElementById(`close-${modalId}`);

            const cleanup = () => {
                modal.classList.remove('active');
                setTimeout(() => modal.remove(), 200);
            };

            okBtn.onclick = () => {
                cleanup();
                resolve();
            };

            closeBtn.onclick = () => {
                cleanup();
                resolve();
            };

            modal.onclick = (e) => {
                if (e.target === modal) {
                    cleanup();
                    resolve();
                }
            };

            okBtn.focus();
        });
    },

    /**
     * Shows a countdown modal (cannot be closed by user easily)
     * @param {string} title 
     * @param {string} message 
     * @param {number} seconds 
     * @param {Function} onComplete 
     */
    countdown: function (title, message, seconds, onComplete) {
        const modalId = 'modal-' + Date.now();
        const modalHtml = `
            <div class="modal-overlay active" id="${modalId}" style="z-index: 10000;">
                <div class="modal-content animate-scale-up text-center" style="max-width: 350px;">
                    <div class="mb-4">
                        <i class="fas fa-check-circle" style="font-size: 3rem; color: var(--success);"></i>
                    </div>
                    <h3 class="modal-title mb-2">${title}</h3>
                    <p class="text-secondary mb-4">${message}</p>
                    <div class="text-3xl font-bold text-primary mb-4" id="counter-${modalId}">${seconds}</div>
                    <p class="text-muted text-sm">Refreshing automatically...</p>
                </div>
            </div>
        `;

        document.body.insertAdjacentHTML('beforeend', modalHtml);
        const counterEl = document.getElementById(`counter-${modalId}`);

        let remaining = seconds;
        const interval = setInterval(() => {
            remaining--;
            if (counterEl) counterEl.textContent = remaining;

            if (remaining <= 0) {
                clearInterval(interval);
                onComplete();
                // Optionally remove modal here, but page reload will likely happen first
            }
        }, 1000);
    },
    /**
     * Shows a prompt modal with an input field
     * @param {string} title 
     * @param {string} message 
     * @param {string} defaultValue 
     * @param {string} placeholder 
     * @returns {Promise<string|null>} Resolves with input value or null if cancelled
     */
    prompt: function (title, message, defaultValue = '', placeholder = '') {
        return new Promise((resolve) => {
            const modalId = 'modal-' + Date.now();
            const modalHtml = `
            <div class="modal-overlay active" id="${modalId}" style="z-index: 9999;">
                <div class="modal-content animate-scale-up" style="max-width: 400px;">
                    <div class="modal-header">
                        <h3 class="modal-title">${title}</h3>
                        <button class="modal-close" id="close-${modalId}">
                            <i class="fas fa-times"></i>
                        </button>
                    </div>
                    <div class="modal-body mb-6">
                        <p class="text-secondary mb-4">${message}</p>
                        <input type="text" id="input-${modalId}" class="form-input w-full" value="${defaultValue}" placeholder="${placeholder}">
                    </div>
                    <div class="flex gap-3 justify-end">
                        <button class="btn btn-secondary" id="cancel-${modalId}">Cancel</button>
                        <button class="btn btn-primary" id="confirm-${modalId}">OK</button>
                    </div>
                </div>
            </div>
            `;

            document.body.insertAdjacentHTML('beforeend', modalHtml);

            const modal = document.getElementById(modalId);
            const input = document.getElementById(`input-${modalId}`);
            const confirmBtn = document.getElementById(`confirm-${modalId}`);
            const cancelBtn = document.getElementById(`cancel-${modalId}`);
            const closeBtn = document.getElementById(`close-${modalId}`);

            const cleanup = () => {
                modal.classList.remove('active');
                setTimeout(() => modal.remove(), 200);
            };

            const confirm = () => {
                const value = input.value;
                cleanup();
                resolve(value);
            };

            const cancel = () => {
                cleanup();
                resolve(null);
            };

            confirmBtn.onclick = confirm;
            cancelBtn.onclick = cancel;
            closeBtn.onclick = cancel;

            // Handle Enter key in input
            input.onkeyup = (e) => {
                if (e.key === 'Enter') confirm();
                if (e.key === 'Escape') cancel();
            };

            modal.onclick = (e) => {
                if (e.target === modal) cancel();
            };

            input.focus();
            input.select();
        });
    }
};
