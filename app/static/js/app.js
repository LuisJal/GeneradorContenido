/* GeneradorContenido - Minimal JS (HTMX handles most interactivity) */
document.addEventListener('DOMContentLoaded', function() {

    // Auto-dismiss flash messages after 5 seconds
    document.querySelectorAll('.flash-success, .flash-error').forEach(function(el) {
        setTimeout(function() {
            el.style.transition = 'opacity 0.5s';
            el.style.opacity = '0';
            setTimeout(function() { el.remove(); }, 500);
        }, 5000);
    });

    // HTMX: loading state for buttons with .btn-loading-trigger or .approve-btn
    document.body.addEventListener('htmx:beforeRequest', function(event) {
        var btn = event.detail.elt;
        if (!btn) return;

        if (btn.classList.contains('btn-loading-trigger') || btn.classList.contains('approve-btn')) {
            btn.disabled = true;
            btn.classList.add('is-loading');
            var textEl = btn.querySelector('.btn-text');
            var spinnerEl = btn.querySelector('.btn-spinner');
            if (textEl && spinnerEl) {
                textEl.style.display = 'none';
                spinnerEl.style.display = 'inline';
            } else {
                btn.dataset.originalText = btn.textContent;
                btn.textContent = 'Procesando...';
            }
        }
    });

    document.body.addEventListener('htmx:afterRequest', function(event) {
        var btn = event.detail.elt;
        if (!btn) return;

        if (btn.classList.contains('btn-loading-trigger') || btn.classList.contains('approve-btn')) {
            btn.disabled = false;
            btn.classList.remove('is-loading');
            var textEl = btn.querySelector('.btn-text');
            var spinnerEl = btn.querySelector('.btn-spinner');
            if (textEl && spinnerEl) {
                textEl.style.display = 'inline';
                spinnerEl.style.display = 'none';
            } else if (btn.dataset.originalText) {
                btn.textContent = btn.dataset.originalText;
                delete btn.dataset.originalText;
            }
        }
    });

    // Scroll to result after HTMX swap
    document.body.addEventListener('htmx:afterSwap', function(event) {
        var target = event.detail.target;
        if (target && (target.id === 'approval-result' || target.id === 'action-result')) {
            target.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
    });
});
