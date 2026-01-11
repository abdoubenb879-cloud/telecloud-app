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
     * Shows a premium countdown modal with celebration animation
     * @param {string} title 
     * @param {string} message 
     * @param {number} seconds 
     * @param {Function} onComplete 
     */
    countdown: function (title, message, seconds, onComplete) {
        const modalId = 'modal-' + Date.now();
        const modalHtml = `
            <div class="modal-overlay active" id="${modalId}" style="z-index: 10000;">
                <div class="modal-content animate-scale-up text-center" style="max-width: 380px; overflow: hidden; position: relative;">
                    <!-- Celebration particles -->
                    <div class="celebration-particles" id="particles-${modalId}">
                        ${Array(12).fill().map((_, i) => `
                            <div class="particle" style="--delay: ${i * 0.08}s; --x: ${Math.random() * 200 - 100}px; --y: ${Math.random() * -150 - 50}px;"></div>
                        `).join('')}
                    </div>
                    
                    <!-- Animated checkmark -->
                    <div class="modal-success-icon mb-4">
                        <svg class="m-checkmark" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 52 52">
                            <circle class="m-checkmark-circle" cx="26" cy="26" r="25" fill="none"/>
                            <path class="m-checkmark-check" fill="none" d="m14.1 27.2l7.1 7.2 16.7-16.8"/>
                        </svg>
                    </div>
                    
                    <h3 class="modal-title mb-2" style="font-size: 1.4rem;">${title}</h3>
                    <p class="text-secondary mb-4" style="font-size: 1rem;">${message}</p>
                    
                    <!-- Countdown ring -->
                    <div class="countdown-ring mb-4" id="ring-${modalId}">
                        <svg width="80" height="80" viewBox="0 0 80 80">
                            <circle class="countdown-bg" cx="40" cy="40" r="36" fill="none" stroke="var(--border)" stroke-width="4"/>
                            <circle class="countdown-progress" cx="40" cy="40" r="36" fill="none" stroke="var(--success)" stroke-width="4" 
                                stroke-dasharray="226.2" stroke-dashoffset="0" style="transition: stroke-dashoffset 1s linear;"/>
                        </svg>
                        <span class="countdown-number" id="counter-${modalId}">${seconds}</span>
                    </div>
                    
                    <button class="btn btn-ghost text-muted" id="skip-${modalId}" style="font-size: 0.85rem;">
                        Skip <i class="fas fa-arrow-right" style="margin-left: 4px;"></i>
                    </button>
                </div>
            </div>
        `;

        document.body.insertAdjacentHTML('beforeend', modalHtml);

        const modal = document.getElementById(modalId);
        const counterEl = document.getElementById(`counter-${modalId}`);
        const progressCircle = modal.querySelector('.countdown-progress');
        const skipBtn = document.getElementById(`skip-${modalId}`);
        const circumference = 226.2;

        let remaining = seconds;
        let interval;

        const complete = () => {
            clearInterval(interval);
            modal.classList.remove('active');
            onComplete();
        };

        skipBtn.onclick = complete;

        // Animate progress ring
        progressCircle.style.strokeDashoffset = 0;

        interval = setInterval(() => {
            remaining--;
            if (counterEl) counterEl.textContent = remaining;

            // Update ring
            const offset = circumference * (1 - remaining / seconds);
            progressCircle.style.strokeDashoffset = offset;

            if (remaining <= 0) {
                complete();
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
    },

    /**
     * Shows a modal to select a target folder
     * @param {Array} folders - List of {id, filename} objects
     * @returns {Promise<number|string|null>} - Resolves with folder ID, 'root', or null
     */
    folderSelect: function (folders) {
        return new Promise((resolve) => {
            const modalId = 'modal-' + Date.now();
            const modalHtml = `
            <div class="modal-overlay active" id="${modalId}" style="z-index: 9999;">
                <div class="modal-content animate-scale-up" style="max-width: 450px;">
                    <div class="modal-header">
                        <h3 class="modal-title">Move items to...</h3>
                        <button class="modal-close" id="close-${modalId}">
                            <i class="fas fa-times"></i>
                        </button>
                    </div>
                    <div class="modal-body mb-6" style="max-height: 400px; overflow-y: auto;">
                        <div class="folder-list">
                            <label class="folder-item" style="display: flex; align-items: center; gap: 12px; padding: 12px; border-radius: 8px; cursor: pointer; transition: background 0.2s;">
                                <input type="radio" name="target-folder" value="root" checked style="accent-color: var(--primary);">
                                <i class="fas fa-home" style="color: var(--primary); font-size: 1.1rem;"></i>
                                <div style="flex: 1;">
                                    <div style="font-weight: 500;">Root / Home</div>
                                    <div class="text-xs text-muted">Primary directory</div>
                                </div>
                            </label>

                            ${folders.map(f => `
                                <label class="folder-item" style="display: flex; align-items: center; gap: 12px; padding: 12px; border-radius: 8px; cursor: pointer; transition: background 0.2s;">
                                    <input type="radio" name="target-folder" value="${f.id}" style="accent-color: var(--primary);">
                                    <i class="fas fa-folder" style="color: #fbbf24; font-size: 1.1rem;"></i>
                                    <div style="flex: 1;">
                                        <div style="font-weight: 500;">${f.filename}</div>
                                    </div>
                                </label>
                            `).join('')}

                            ${folders.length === 0 ? '<p class="text-center text-muted py-4">No folders available. You can create one first.</p>' : ''}
                        </div>
                    </div>
                    <div class="modal-footer flex gap-3 justify-between items-center pt-4 border-t border-dashed border-border">
                        <button class="btn btn-ghost btn-sm" id="new-folder-${modalId}">
                            <i class="fas fa-folder-plus"></i> New Folder
                        </button>
                        <div class="flex gap-2">
                            <button class="btn btn-secondary" id="cancel-${modalId}">Cancel</button>
                            <button class="btn btn-primary" id="confirm-${modalId}">Move Here</button>
                        </div>
                    </div>
                </div>
            </div>
            `;

            document.body.insertAdjacentHTML('beforeend', modalHtml);

            // Add styles for hover effect
            const style = document.createElement('style');
            style.innerHTML = `
                .folder-item:hover { background: rgba(255,255,255,0.05); }
                .folder-item input:checked + i + div { color: var(--primary); }
            `;
            document.head.appendChild(style);

            const modal = document.getElementById(modalId);
            const confirmBtn = document.getElementById(`confirm-${modalId}`);
            const cancelBtn = document.getElementById(`cancel-${modalId}`);
            const closeBtn = document.getElementById(`close-${modalId}`);
            const newFolderBtn = document.getElementById(`new-folder-${modalId}`);

            const cleanup = () => {
                modal.classList.remove('active');
                setTimeout(() => {
                    modal.remove();
                    style.remove();
                }, 200);
            };

            confirmBtn.onclick = () => {
                const selected = modal.querySelector('input[name="target-folder"]:checked');
                const value = selected ? selected.value : null;
                cleanup();
                resolve(value);
            };

            newFolderBtn.onclick = () => {
                cleanup();
                resolve('create_new');
            };

            const cancel = () => {
                cleanup();
                resolve(null);
            };

            cancelBtn.onclick = cancel;
            closeBtn.onclick = cancel;
            modal.onclick = (e) => { if (e.target === modal) cancel(); };
        });
    }
};
