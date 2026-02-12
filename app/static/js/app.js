/* GeneradorContenido — App JS
   HTMX interactions + Alpine.js utilities */

document.addEventListener('DOMContentLoaded', function() {

    // ── Auto-dismiss flash messages ──
    document.querySelectorAll('.flash-success, .flash-error').forEach(function(el) {
        setTimeout(function() {
            el.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
            el.style.opacity = '0';
            el.style.transform = 'translateY(-4px)';
            setTimeout(function() { el.remove(); }, 300);
        }, 5000);
    });

    // ── HTMX: loading state for buttons ──
    document.body.addEventListener('htmx:beforeRequest', function(event) {
        var btn = event.detail.elt;
        if (!btn) return;

        if (btn.classList.contains('btn-loading-trigger') ||
            btn.classList.contains('approve-btn') ||
            btn.classList.contains('reject-btn')) {
            btn.disabled = true;
            btn.classList.add('is-loading');
            var textEl = btn.querySelector('.btn-text');
            var spinnerEl = btn.querySelector('.btn-spinner');
            if (textEl && spinnerEl) {
                textEl.style.display = 'none';
                spinnerEl.style.display = 'inline-flex';
            } else {
                btn.dataset.originalText = btn.textContent;
                btn.textContent = 'Procesando...';
            }
        }
    });

    document.body.addEventListener('htmx:afterRequest', function(event) {
        var btn = event.detail.elt;
        if (!btn) return;

        if (btn.classList.contains('btn-loading-trigger') ||
            btn.classList.contains('approve-btn') ||
            btn.classList.contains('reject-btn')) {
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

    // ── Scroll to result after HTMX swap ──
    document.body.addEventListener('htmx:afterSwap', function(event) {
        var target = event.detail.target;
        if (target && (target.id === 'approval-result' || target.id === 'action-result')) {
            target.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
    });

    // ── Character counter for textareas ──
    document.querySelectorAll('textarea[data-maxlength]').forEach(function(textarea) {
        var counter = document.createElement('span');
        counter.className = 'text-xs text-tertiary';
        counter.style.display = 'block';
        counter.style.textAlign = 'right';
        counter.style.marginTop = '-12px';
        counter.style.marginBottom = '16px';

        var max = parseInt(textarea.dataset.maxlength, 10);
        function update() {
            var len = textarea.value.length;
            counter.textContent = len + '/' + max;
            counter.style.color = len > max ? 'var(--color-danger)' : '';
        }
        update();
        textarea.addEventListener('input', update);
        textarea.parentNode.insertBefore(counter, textarea.nextSibling);
    });
});
