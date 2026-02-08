document.addEventListener('DOMContentLoaded', function() {
    var sidebarToggle = document.querySelector('.sidebar-toggle');
    var sidebar = document.querySelector('.sidebar');
    var documentViewer = document.querySelector('.document-viewer');

    // Toggle sidebar
    sidebarToggle.addEventListener('click', function() {
        sidebar.classList.toggle('active');
    });

    // Load default documents (e.g., General Comments from the CRC)
    function loadDefaultDocuments() {
        loadDocuments('CRC'); // Replace 'CRC' with the actual default committee identifier
    }

    loadDefaultDocuments();

});

    function sortDocuments(documents) {
    return documents.sort((a, b) => {
        const aMatch = a.name.match(/General Comment No\. (\d+)/);
        const bMatch = b.name.match(/General Comment No\. (\d+)/);
        const aNumber = aMatch ? parseInt(aMatch[1]) : -1;
        const bNumber = bMatch ? parseInt(bMatch[1]) : -1;
        return bNumber - aNumber; // Sort in descending order of GC number
    });
}

function loadDocuments(committee, viewFirstDocument = false) {
    if (!committee) return; // Do nothing if no committee is selected

    // Determine which endpoint to use based on current page
    const isEnhanced = window.location.pathname.includes('enhanced');
    const endpoint = isEnhanced ? '/enhanced_get_documents/' : '/get_documents/';

    fetch(endpoint + encodeURIComponent(committee))
        .then(response => response.json())
        .then(documents => {
            const sortedDocuments = sortDocuments(documents);
            const docListDiv = document.querySelector('.document-list');
            docListDiv.innerHTML = ''; // Clear existing list

            sortedDocuments.forEach(doc => {
                const docLink = document.createElement('a');
                docLink.href = '#';
                docLink.className = 'document-item'; // Add proper CSS class
                docLink.textContent = doc.name; // Assuming each document has a 'name' property
                docLink.onclick = () => {
                    viewDocument(doc.id); // Assuming each document has an 'id' property
                    return false;
                };

                const listItem = document.createElement('li');
                listItem.appendChild(docLink);
                docListDiv.appendChild(listItem);
            });

            assignDocumentLinkEventListeners();

            // Automatically view the first document if requested
            if (viewFirstDocument && sortedDocuments.length > 0) {
                viewDocument(sortedDocuments[0].id);
            }
        })
        .catch(error => console.error('Error loading documents:', error));
   }

    let currentDocumentId = null;

    function viewDocument(documentId) {
        currentDocumentId = documentId;

        // Determine which endpoint to use based on current page
        const isEnhanced = window.location.pathname.includes('enhanced');
        const endpoint = isEnhanced ? '/enhanced_get_document/' : '/get_document/';

        fetch(endpoint + encodeURIComponent(currentDocumentId))
            .then(response => response.json())
            .then(data => {
                const viewerDiv = document.querySelector('.document-viewer');
                viewerDiv.innerHTML = ''; // Clear existing content
                viewerDiv.scrollTop = 0;

                // Create document header with enhanced information
                const isEnhanced = window.location.pathname.includes('enhanced');

                if (isEnhanced) {
                    // Enhanced layout with citation and source links
                    const headerDiv = document.createElement('div');
                    headerDiv.className = 'document-header';
                    headerDiv.style.cssText = 'background: var(--card-background); padding: var(--spacing-lg); border-radius: var(--radius-md); margin-bottom: var(--spacing-lg); border: 1px solid var(--border-color);';

                    const title = document.createElement('h2');
                    title.textContent = data.title;
                    headerDiv.appendChild(title);

                    const infoRow = document.createElement('div');
                    infoRow.className = 'row';

                    const leftCol = document.createElement('div');
                    leftCol.className = 'col-md-6';

                    const yearP = document.createElement('p');
                    yearP.className = 'mb-1';
                    yearP.innerHTML = '<strong>Year of Adoption:</strong> ' + (data.adoption_year || 'N/A');
                    leftCol.appendChild(yearP);

                    const sigP = document.createElement('p');
                    sigP.className = 'mb-1';
                    sigP.innerHTML = '<strong>Signature:</strong> ' + (data.signature || 'N/A');
                    leftCol.appendChild(sigP);

                    const rightCol = document.createElement('div');
                    rightCol.className = 'col-md-6';

                    const actionsDiv = document.createElement('div');
                    actionsDiv.className = 'citation-actions';
                    actionsDiv.style.cssText = 'display: flex; gap: var(--spacing-sm); margin-top: var(--spacing-md);';

                    const copyBtn = document.createElement('button');
                    copyBtn.className = 'btn btn-sm btn-outline-primary';
                    copyBtn.innerHTML = '<i class="fas fa-copy mr-1"></i> Copy Citation';
                    copyBtn.onclick = () => copyCitation(data);
                    actionsDiv.appendChild(copyBtn);

                    if (data.link) {
                        const sourceBtn = document.createElement('a');
                        sourceBtn.className = 'btn btn-sm btn-outline-secondary';
                        sourceBtn.href = data.link;
                        sourceBtn.target = '_blank';
                        sourceBtn.innerHTML = '<i class="fas fa-external-link-alt mr-1"></i> View Source';
                        actionsDiv.appendChild(sourceBtn);
                    }

                    rightCol.appendChild(actionsDiv);
                    infoRow.appendChild(leftCol);
                    infoRow.appendChild(rightCol);
                    headerDiv.appendChild(infoRow);

                    viewerDiv.appendChild(headerDiv);
                } else {
                    // Standard layout
                    const title = document.createElement('h2');
                    title.textContent = data.title;
                    viewerDiv.appendChild(title);

                    const signature = document.createElement('p');
                    signature.textContent = 'Signature: ' + data.signature;
                    viewerDiv.appendChild(signature);

                    const adoptionYear = document.createElement('p');
                    adoptionYear.textContent = 'Year of Adoption: ' + data.adoption_year;
                    viewerDiv.appendChild(adoptionYear);
                }

                // Append paragraphs with numbers
                data.paragraphs.forEach((text, index) => {
                    const paragraph = document.createElement('p');
                    paragraph.innerHTML = text.replace(/^(\d+\.\s*)?/, `<strong>${index + 1}.</strong> `);
                    viewerDiv.appendChild(paragraph);
                });

                // Clear the existing original content attribute
                viewerDiv.removeAttribute('data-original');

                // Set the new original content for search functionality
                const content = viewerDiv.innerHTML;
                viewerDiv.setAttribute('data-original', content);

                const searchInput = document.getElementById('documentSearchInput');
                searchInput.value = '';
                searchInput.removeEventListener('input', handleSearch);
                const handleSearch = () => documentSearch(searchInput.value);
                searchInput.addEventListener('input', handleSearch);
            })
            .catch(error => console.error('Error loading document:', error));
    }


    // Function to escape special characters for regex
    function escapeRegex(string) {
        return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }

    // Function for dynamic search within the document
    function documentSearch(query) {
        const viewerDiv = document.querySelector('.document-viewer');
        let content = viewerDiv.getAttribute('data-original') || viewerDiv.innerHTML;
        viewerDiv.setAttribute('data-original', content);

        if (query.length >= 3) {
            const regex = new RegExp(escapeRegex(query), 'gi');
            viewerDiv.innerHTML = content.replace(regex, match => `<span class="highlight">${match}</span>`);
            Array.from(viewerDiv.children).forEach(child => {
                if (!child.innerHTML.match(regex)) {
                    child.style.display = 'none';
                }
            });
        } else {
            viewerDiv.innerHTML = content;
            Array.from(viewerDiv.children).forEach(child => {
                child.style.display = '';
            });
        }
    }

    // Event listener for dynamic search input
    const searchInput = document.getElementById('documentSearchInput');
    searchInput.addEventListener('input', () => documentSearch(searchInput.value));

// Function to set dark mode preference
function setDarkModePreference(isDarkMode) {
    localStorage.setItem('darkMode', isDarkMode ? 'enabled' : 'disabled');
}

// Function to apply dark mode based on preference
function applyDarkModePreference() {
    const isDarkMode = localStorage.getItem('darkMode') === 'enabled';
    const darkModeToggle = document.getElementById("dark-mode-toggle");

    if (isDarkMode) {
        document.body.classList.add('dark-mode');
        darkModeToggle.querySelector('i').classList.replace("fa-moon", "fa-sun");
        darkModeToggle.querySelector('i').classList.add("dark-mode-active");
    } else {
        document.body.classList.remove('dark-mode');
        darkModeToggle.querySelector('i').classList.replace("fa-sun", "fa-moon");
        darkModeToggle.querySelector('i').classList.remove("dark-mode-active");
    }
}

// Check if the user has a preference and apply it
applyDarkModePreference();

function toggleDarkMode() {
    const body = document.body;
    const darkModeToggle = document.getElementById("dark-mode-toggle");
    body.classList.toggle("dark-mode");

    if (body.classList.contains("dark-mode")) {
        darkModeToggle.querySelector('i').classList.replace("fa-moon", "fa-sun");
        darkModeToggle.querySelector('i').classList.add("dark-mode-active");
        setDarkModePreference(true);
    } else {
        darkModeToggle.querySelector('i').classList.replace("fa-sun", "fa-moon");
        darkModeToggle.querySelector('i').classList.remove("dark-mode-active");
        setDarkModePreference(false);
    }
}

// Event listener for the dark mode toggle click
const darkModeToggle = document.getElementById("dark-mode-toggle");
if (darkModeToggle) {
    darkModeToggle.addEventListener("click", toggleDarkMode);
}

document.addEventListener('DOMContentLoaded', function() {
    var sidebarToggle = document.querySelector('.sidebar-toggle');
    var sidebar = document.querySelector('.sidebar');

// Load default documents (e.g., General Comments from the CRC)
    function loadDefaultDocuments() {
        loadDocuments('CRC', true); // Replace 'CRC' with the actual default committee identifier
    }

    loadDefaultDocuments();
});

function assignDocumentLinkEventListeners() {
    var documentLinks = document.querySelectorAll('.document-list a');
    documentLinks.forEach(function(link) {
        link.addEventListener('click', function() {
            // Remove active class from all document links
            documentLinks.forEach(function(otherLink) {
                otherLink.classList.remove('active');
            });

            // Add active class to the clicked link
            link.classList.add('active');

            // Close sidebar on small screens by toggling the 'active' class
            if (window.innerWidth <= 767) { // Check if the screen is small
                var sidebar = document.querySelector('.sidebar');
                sidebar.classList.remove('active');
            }
        });
    });
}

document.addEventListener('DOMContentLoaded', function() {
        // Scroll to top button functionality
    const scrollToTopBtn = document.getElementById("scrollToTopBtn");
    if (scrollToTopBtn) {
        window.onscroll = function() {
            if (document.body.scrollTop > 20 || document.documentElement.scrollTop > 20) {
                scrollToTopBtn.style.display = "block";
            } else {
                scrollToTopBtn.style.display = "none";
            }
        };

        scrollToTopBtn.addEventListener('click', function() {
            window.scrollTo({top: 0, behavior: 'smooth'});
        });
    }
});

// Copy citation functionality
function copyCitation(data) {
    const citation = `${data.committee || 'UN Treaty Body'}. "${data.title}". ${data.signature || ''}. ${data.adoption_year || ''}.`;

    if (navigator.clipboard) {
        navigator.clipboard.writeText(citation).then(() => {
            showCopyFeedback();
        });
    } else {
        // Fallback for older browsers
        const textArea = document.createElement("textarea");
        textArea.value = citation;
        document.body.appendChild(textArea);
        textArea.select();
        document.execCommand("copy");
        document.body.removeChild(textArea);
        showCopyFeedback();
    }
}

function showCopyFeedback() {
    const button = document.querySelector('button[onclick*="copyCitation"]');
    if (button) {
        const originalHtml = button.innerHTML;
        button.innerHTML = '<i class="fas fa-check mr-1"></i> Copied!';
        button.classList.add('btn-success');
        button.classList.remove('btn-outline-primary');

        setTimeout(() => {
            button.innerHTML = originalHtml;
            button.classList.remove('btn-success');
            button.classList.add('btn-outline-primary');
        }, 2000);
    }
}