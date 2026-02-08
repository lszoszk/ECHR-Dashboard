function toggleDarkMode() {
    const body = document.body;
    const darkModeToggle = document.getElementById("dark-mode-toggle");
    body.classList.toggle("dark-mode");

    if (body.classList.contains("dark-mode")) {
        darkModeToggle.querySelector('i').classList.replace("fa-moon", "fa-sun");
        darkModeToggle.querySelector('i').classList.add("dark-mode-active");
        localStorage.setItem("darkMode", "enabled");
    } else {
        darkModeToggle.querySelector('i').classList.replace("fa-sun", "fa-moon");
        darkModeToggle.querySelector('i').classList.remove("dark-mode-active");
        localStorage.removeItem("darkMode");
    }
}


document.addEventListener("DOMContentLoaded", function () {
    const darkModeToggle = document.getElementById("dark-mode-toggle");

    // Initial check for saved dark mode setting
    if (localStorage.getItem("darkMode") === "enabled") {
        document.body.classList.add("dark-mode");
        darkModeToggle.classList.replace("fa-moon", "fa-sun");
    }

    // Event listener for the icon click
    darkModeToggle.addEventListener("click", toggleDarkMode);

document.addEventListener('DOMContentLoaded', function() {
    document.querySelector('form[action="/search"]').addEventListener('submit', function(e) {
        var searchQuery = document.querySelector('input[name="search_query"]').value;
        var labelsSelected = Array.from(document.querySelectorAll('select[name="labels[]"] option:checked')).map(option => option.value).join(', ');
        var treatyBodiesSelected = Array.from(document.querySelectorAll('input[name="treatyBodies[]"]:checked')).map(input => input.value).join(', ');

        // Combine labels and treaty bodies for a comprehensive filter description
        var filtersDescription = [labelsSelected, treatyBodiesSelected].filter(Boolean).join('; ');

        // Google Analytics event tracking with enhanced information
        gtag('event', 'search', {
            'event_category': 'Site Search',
            'event_label': searchQuery,
            'event_action': 'submit',
            'search_filters': filtersDescription  // Note: Custom dimensions might be required for additional parameters like this
        });
    });
});


document.addEventListener('DOMContentLoaded', function () {
    var selectElement = document.querySelector('select');

    selectElement.addEventListener('change', function () {
        // Remove any previously added 'selected' class
        this.querySelectorAll('option').forEach(option => option.classList.remove('selected'));

        // Add 'selected' class to the currently selected option
        this.querySelector('option:checked').classList.add('selected');
    });
});

        // Function to hide the cookie consent banner
        function hideCookieBanner() {
            document.getElementById("cookieConsentBanner").style.display = "none";
            localStorage.setItem("cookieConsent", "true");
        }

        // Check if cookie consent has already been given
        document.addEventListener("DOMContentLoaded", function () {
            if (localStorage.getItem("cookieConsent")) {
                document.getElementById("cookieConsentBanner").style.display = "none";
            }
        });
});
