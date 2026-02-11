/* GeneradorContenido - Minimal JS (HTMX handles most interactivity) */
document.addEventListener('DOMContentLoaded', function() {
    // HTMX event listeners for toast notifications
    document.body.addEventListener('htmx:afterSwap', function(event) {
        // Future: handle flash messages after HTMX swaps
    });
});
