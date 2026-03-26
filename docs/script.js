document.addEventListener('DOMContentLoaded', () => {
    const langToggle = document.getElementById('langToggle');
    const langLabels = document.querySelectorAll('.lang-label');
    const toggleSlider = document.querySelector('.toggle-slider');
    const techToggle = document.getElementById('techToggle');
    const techContent = document.getElementById('techContent');
    const techBtnText = document.getElementById('techBtnText');

    let currentLang = 'en';

    // Language Toggle Logic
    langToggle.addEventListener('click', () => {
        currentLang = currentLang === 'en' ? 'kn' : 'en';
        updateLanguage();
    });

    function updateLanguage() {
        // Update slider position
        if (currentLang === 'en') {
            toggleSlider.style.transform = 'translateX(0)';
            langLabels[0].classList.add('active');
            langLabels[1].classList.remove('active');
        } else {
            toggleSlider.style.transform = 'translateX(100%)';
            langLabels[0].classList.remove('active');
            langLabels[1].classList.add('active');
        }

        // Update all translated elements
        document.querySelectorAll('[data-en]').forEach(el => {
            el.textContent = el.getAttribute(`data-${currentLang}`);
        });

        // Update placeholders/titles if any
        document.title = currentLang === 'en' ? 
            'E-Zine Bot | Mayura, Sudha, Prajavani, Deccan Herald' : 
            'ಇ-ಪತ್ರಿಕೆ ಬಾಟ್ | ಮಯೂರ, ಸುಧಾ, ಪ್ರಜಾವಾಣಿ, ಡೆಕ್ಕನ್ ಹೆರಾಲ್ಡ್';
    }

    // Technical Details Toggle
    techToggle.addEventListener('click', () => {
        techContent.classList.toggle('show');
        const isShowing = techContent.classList.contains('show');
        techBtnText.textContent = isShowing ? 
            (currentLang === 'en' ? 'Hide Technical Details' : 'ತಾಂತ್ರಿಕ ವಿವರಗಳನ್ನು ಮರೆಮಾಡಿ') : 
            (currentLang === 'en' ? 'Show Technical Details' : 'ತಾಂತ್ರಿಕ ವಿವರಗಳನ್ನು ತೋರಿಸಿ');
        
        // Update techBtnText data attributes so it switches correctly on lang change
        techBtnText.setAttribute('data-en', isShowing ? 'Hide Technical Details' : 'Show Technical Details');
        techBtnText.setAttribute('data-kn', isShowing ? 'ತಾಂತ್ರಿಕ ವಿವರಗಳನ್ನು ಮರೆಮಾಡಿ' : 'ತಾಂತ್ರಿಕ ವಿವರಗಳನ್ನು ತೋರಿಸಿ');

        techToggle.querySelector('.arrow').style.transform = isShowing ? 'rotate(180deg)' : 'rotate(0deg)';
    });

    // Simple Reveal Animation on Scroll
    const observerOptions = {
        threshold: 0.1
    };

    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('revealed');
            }
        });
    }, observerOptions);

    document.querySelectorAll('.pub-card, .feature-text, .feature-visual').forEach(el => {
        el.classList.add('reveal-init');
        observer.observe(el);
    });
});

// Add CSS for Reveal Animations
const style = document.createElement('style');
style.textContent = `
    .reveal-init {
        opacity: 0;
        transform: translateY(30px);
        transition: opacity 0.8s ease-out, transform 0.8s ease-out;
    }
    .revealed {
        opacity: 1;
        transform: translateY(0);
    }
`;
document.head.appendChild(style);
