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

    // HTMX: loading state on approve button
    document.body.addEventListener('htmx:beforeRequest', function(event) {
        var trigger = event.detail.elt;
        if (trigger && trigger.classList.contains('approve-btn')) {
            trigger.setAttribute('aria-busy', 'true');
            trigger.disabled = true;
        }
    });

    document.body.addEventListener('htmx:afterRequest', function(event) {
        var trigger = event.detail.elt;
        if (trigger && trigger.classList.contains('approve-btn')) {
            trigger.removeAttribute('aria-busy');
            trigger.disabled = false;
        }
    });

    // Scroll to result after HTMX swap
    document.body.addEventListener('htmx:afterSwap', function(event) {
        var target = event.detail.target;
        if (target && target.id === 'approval-result') {
            target.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
    });
});
