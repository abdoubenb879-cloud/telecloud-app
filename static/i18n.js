/**
 * Khaznati Language Switcher & RTL Support
 * Handles dynamic language switching between English and Arabic
 */

const Translator = {
    translations: null,
    currentLang: localStorage.getItem('khaznati_lang') || 'en',

    async init() {
        try {
            const response = await fetch('/static/translations.json');
            this.translations = await response.json();
            this.applyLanguage(this.currentLang);
            this.createLanguageSwitcher();
        } catch (error) {
            console.error('Failed to load translations:', error);
        }
    },

    setLanguage(lang) {
        this.currentLang = lang;
        localStorage.setItem('khaznati_lang', lang);
        this.applyLanguage(lang);
    },

    applyLanguage(lang) {
        const isRTL = lang === 'ar';

        // Set document direction
        document.documentElement.dir = isRTL ? 'rtl' : 'ltr';
        document.documentElement.lang = lang;
        document.body.classList.toggle('rtl', isRTL);

        // Update all translatable elements
        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.getAttribute('data-i18n');
            const text = this.getText(key);
            if (text) {
                if (el.tagName === 'INPUT' && el.placeholder) {
                    el.placeholder = text;
                } else {
                    el.textContent = text;
                }
            }
        });

        // Update page title
        document.title = isRTL ? 'خزنتي - ملفاتك في أمان' : 'Khaznati - Your files, safe';

        // Update brand name
        const brandEl = document.querySelector('.logo-text, .brand-name');
        if (brandEl) {
            brandEl.textContent = isRTL ? 'خزنتي' : 'Khaznati';
        }
    },

    getText(key) {
        if (!this.translations) return null;

        const isArabic = this.currentLang === 'ar';
        const parts = key.split('.');
        let value = this.translations;

        for (const part of parts) {
            if (value[part] !== undefined) {
                value = value[part];
            } else {
                return null;
            }
        }

        // If it's a nested object, get the correct language version
        if (typeof value === 'object') {
            return isArabic ? value.ar : value.en;
        }

        // If key ends with _ar, we need to handle it differently
        const arKey = key + '_ar';
        const enKey = key.replace('_ar', '');

        if (isArabic) {
            // Try to get Arabic version
            let arValue = this.translations;
            for (const part of (arKey).split('.')) {
                if (arValue[part] !== undefined) {
                    arValue = arValue[part];
                } else {
                    return value; // Fallback to original
                }
            }
            return arValue;
        }

        return value;
    },

    t(section, key) {
        if (!this.translations) return key;

        const isArabic = this.currentLang === 'ar';
        const sectionData = this.translations[section];

        if (!sectionData) return key;

        const suffix = isArabic ? '_ar' : '';
        return sectionData[key + suffix] || sectionData[key] || key;
    },

    createLanguageSwitcher() {
        // Check if already exists
        if (document.getElementById('lang-switcher')) return;

        // Create language switcher button
        const switcher = document.createElement('button');
        switcher.id = 'lang-switcher';
        switcher.className = 'lang-switcher';
        switcher.innerHTML = this.currentLang === 'ar' ? '🇬🇧 EN' : '🇩🇿 AR';
        switcher.title = this.currentLang === 'ar' ? 'Switch to English' : 'التبديل إلى العربية';

        switcher.addEventListener('click', () => {
            const newLang = this.currentLang === 'en' ? 'ar' : 'en';
            this.setLanguage(newLang);
            switcher.innerHTML = newLang === 'ar' ? '🇬🇧 EN' : '🇩🇿 AR';
            switcher.title = newLang === 'ar' ? 'Switch to English' : 'التبديل إلى العربية';
        });

        // Try to add to sidebar header first (best placement)
        const sidebarHeader = document.querySelector('.sidebar-header');
        if (sidebarHeader) {
            sidebarHeader.appendChild(switcher);
            return;
        }

        // Fallback: add to body (will use fixed position)
        document.body.appendChild(switcher);
    }
};

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    Translator.init();
});

// Re-apply translations after SPA navigation
document.addEventListener('spa:navigated', () => {
    if (Translator.translations) {
        Translator.applyLanguage(Translator.currentLang);
    }
});

// Export for use in other scripts
window.Translator = Translator;
window.t = (section, key) => Translator.t(section, key);
