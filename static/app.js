/**
 * CloudVault Global Application Logic
 * Shared across Dashboard, Trash, and Settings
 */

// Global State
const csrfToken = document.querySelector('meta[name="csrf-token"]') ? document.querySelector('meta[name="csrf-token"]').content : '';

// --- Navigation & UI ---

function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    if (sidebar) sidebar.classList.toggle('open');
}

function toggleUserMenu() {
    const menu = document.getElementById('userMenu');
    if (menu) {
        menu.style.display = menu.style.display === 'block' ? 'none' : 'block';
    }
}

// Close user menu on clicking outside
document.addEventListener('click', (e) => {
    if (!e.target.closest('.user-card')) {
        const userMenu = document.getElementById('userMenu');
        if (userMenu) userMenu.style.display = 'none';
    }
});

// --- SPA-lite Navigation Manager ---

async function navigateSPA(url, pushState = true) {
    const navBar = document.getElementById('navLoadingBar');
    const mainContent = document.getElementById('main-content-area');

    if (navBar) navBar.style.width = '30%';

    try {
        const response = await fetch(url + (url.includes('?') ? '&' : '?') + 'ajax=true', {
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        });

        if (!response.ok) throw new Error('Navigation failed');

        if (navBar) navBar.style.width = '70%';
        const htmlText = await response.text();

        const parser = new DOMParser();
        const doc = parser.parseFromString(htmlText, 'text/html');
        const newContent = doc.getElementById('spa-content-container');

        if (!newContent) {
            console.warn('No spa-content-container found, performing full reload');
            window.location.href = url;
            return;
        }

        // Transition: Fade out
        const oldBody = mainContent.querySelector('.content-body');
        if (oldBody) oldBody.classList.add('fade-out');

        setTimeout(() => {
            const currentContainer = document.getElementById('spa-content-container');
            if (currentContainer) {
                currentContainer.innerHTML = newContent.innerHTML;
            } else {
                mainContent.innerHTML = newContent.outerHTML;
            }

            // Transition: Fade in
            const newBody = document.querySelector('#spa-content-container .content-body');
            if (newBody) newBody.classList.add('fade-in');

            if (pushState) {
                window.history.pushState({ url }, '', url);
            }

            // Update UI State
            updateActiveNavItem(url);

            const newTitle = doc.querySelector('title');
            if (newTitle) document.title = newTitle.textContent;

            if (navBar) {
                navBar.style.width = '100%';
                setTimeout(() => { navBar.style.width = '0'; }, 300);
            }

            // Re-initialize any page-specific listeners if needed
            // (Page specific logic should ideally be triggered by custom events)
            document.dispatchEvent(new CustomEvent('spa:navigated', { detail: { url } }));

        }, 250);

    } catch (error) {
        console.error('SPA Navigation Error:', error);
        window.location.href = url;
    }
}

function updateActiveNavItem(url) {
    const path = new URL(url, window.location.origin).pathname;
    document.querySelectorAll('.nav-item').forEach(item => {
        const itemPath = new URL(item.href, window.location.origin).pathname;
        if (path === itemPath) {
            item.classList.add('active');
        } else {
            item.classList.remove('active');
        }
    });
}

// Intercept all internal link clicks for SPA
document.addEventListener('click', (e) => {
    const link = e.target.closest('a');
    if (link) {
        const url = link.getAttribute('href');
        if (url && !url.startsWith('http') && !url.startsWith('#') && !url.includes('logout')) {
            if (e.ctrlKey || e.shiftKey || e.metaKey || link.target === '_blank') return;

            e.preventDefault();
            navigateSPA(url);

            const sidebar = document.getElementById('sidebar');
            if (sidebar) sidebar.classList.remove('open');
        }
    }
});

// Handle browser Back/Forward
window.addEventListener('popstate', (e) => {
    if (e.state && e.state.url) {
        navigateSPA(e.state.url, false);
    } else {
        window.location.reload();
    }
});

// --- Trash Logic ---

async function restoreFile(fileId) {
    try {
        const response = await fetch(`/restore/${fileId}`, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken }
        });
        if (response.ok) {
            const card = document.getElementById(`file-${fileId}`);
            if (card) card.remove();
            if (!document.querySelector('.file-card')) navigateSPA('/trash', false);
            if (window.Modal) await Modal.alert('Success', 'File restored successfully');
        } else {
            const data = await response.json();
            if (window.Modal) await Modal.alert('Error', data.error || 'Failed to restore');
        }
    } catch (e) { console.error(e); }
}

async function permanentDelete(fileId) {
    if (!window.Modal) {
        if (!confirm('Permanently delete this file?')) return;
    } else {
        const confirmed = await Modal.confirm('Permanently Delete?', 'This cannot be undone. Are you sure?', 'Delete', 'Cancel', true);
        if (!confirmed) return;
    }

    try {
        const response = await fetch(`/delete/permanent/${fileId}`, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken }
        });
        if (response.ok) {
            const card = document.getElementById(`file-${fileId}`);
            if (card) card.remove();
            if (!document.querySelector('.file-card')) navigateSPA('/trash', false);
        } else {
            const data = await response.json();
            if (window.Modal) await Modal.alert('Error', data.error || 'Delete failed');
        }
    } catch (e) { console.error(e); }
}

async function emptyTrash() {
    if (window.Modal) {
        const confirmed = await Modal.confirm('Empty Trash?', 'Delete ALL files permanently? This cannot be undone.', 'Empty Trash', 'Cancel', true);
        if (!confirmed) return;
    }

    try {
        const response = await fetch('/trash/empty', {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken }
        });
        if (response.ok) navigateSPA('/trash', false);
        else if (window.Modal) await Modal.alert('Error', 'Failed to empty trash');
    } catch (e) { console.error(e); }
}

// --- Settings Logic ---

function showToast(msg, isError = false) {
    const toast = document.getElementById('toast');
    const msgEl = document.getElementById('toastMsg');
    if (!toast || !msgEl) return;

    msgEl.textContent = msg;
    toast.classList.remove('hidden', 'error');
    if (isError) toast.classList.add('error');
    setTimeout(() => { toast.classList.add('hidden'); }, 3000);
}

function editField(field) {
    const editRow = document.getElementById(`${field}EditRow`);
    if (!editRow) return;
    const valueRow = editRow.previousElementSibling;
    if (valueRow) valueRow.style.display = 'none';
    editRow.classList.remove('hidden');
    const input = document.getElementById(`${field}Input`);
    if (input) input.focus();
}

function cancelEdit(field) {
    const editRow = document.getElementById(`${field}EditRow`);
    if (!editRow) return;
    const valueRow = editRow.previousElementSibling;
    if (valueRow) valueRow.style.display = 'flex';
    editRow.classList.add('hidden');
    if (field === 'password') {
        const oldPass = document.getElementById('oldPasswordInput');
        const newPass = document.getElementById('passwordInput');
        if (oldPass) oldPass.value = '';
        if (newPass) newPass.value = '';
    }
}

async function saveField(field) {
    const input = document.getElementById(`${field}Input`);
    if (!input) return;
    const value = input.value.trim();
    if (!value) { showToast(`Please enter a ${field}`, true); return; }

    const formData = new FormData();
    formData.append('field', field);
    formData.append('value', value);
    if (field === 'password') {
        const oldPass = document.getElementById('oldPasswordInput');
        if (oldPass && !oldPass.value) { showToast('Please enter current password', true); return; }
        formData.append('old_password', oldPass.value);
    }

    try {
        const response = await fetch('/settings/update', {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken },
            body: formData
        });
        const data = await response.json();
        if (response.ok) {
            showToast(data.message || 'Updated successfully');
            const valEl = document.getElementById(`${field}Value`);
            if (valEl) valEl.textContent = value;
            if (field === 'username') {
                document.querySelectorAll('.user-name').forEach(el => el.textContent = value);
            }
            cancelEdit(field);
        } else {
            showToast(data.error || 'Update failed', true);
        }
    } catch (e) { showToast('An error occurred', true); }
}

async function deleteAccount() {
    if (window.Modal) {
        const confirmed = await Modal.confirm('Delete Account?', 'Are you sure? All files will be deleted permanently.', 'Delete Account', 'Cancel', true);
        if (!confirmed) return;
    }

    try {
        const response = await fetch('/settings/delete_account', {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken }
        });
        const data = await response.json();
        if (response.ok) {
            if (window.Modal) await Modal.alert('Goodbye', data.message);
            window.location.href = '/login';
        } else {
            showToast(data.error || 'Failed', true);
        }
    } catch (e) { showToast('Error occurred', true); }
}
