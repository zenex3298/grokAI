document.addEventListener('DOMContentLoaded', function() {
    const analyzeForm = document.querySelector('form[action="/analyze"]');
    const analyzeBtn = document.getElementById('analyze-btn');
    
    if (analyzeForm) {
        // Add loading state to form submission
        analyzeForm.addEventListener('submit', function() {
            // Validate form
            const vendorName = document.getElementById('vendor_name').value.trim();
            if (!vendorName) {
                return false;
            }
            
            // Show loading state
            analyzeBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Analyzing...';
            analyzeBtn.disabled = true;
            
            // Allow form submission
            return true;
        });
    }
    
    // Add copy function for results table if on results page
    const resultsTable = document.querySelector('.table');
    if (resultsTable) {
        addCopyFunctionality(resultsTable);
    }
});

// Function to add copy button to table
function addCopyFunctionality(table) {
    const copyBtn = document.createElement('button');
    copyBtn.className = 'btn btn-sm btn-outline-secondary mt-3';
    copyBtn.innerHTML = '<i class="fa fa-copy"></i> Copy Results';
    copyBtn.onclick = function() {
        copyTableToClipboard(table);
    };
    
    table.parentNode.insertBefore(copyBtn, table.nextSibling);
}

// Function to copy table data to clipboard
function copyTableToClipboard(table) {
    let data = [];
    const headers = [];
    
    // Get headers
    const headerCells = table.querySelectorAll('thead th');
    headerCells.forEach(cell => {
        headers.push(cell.textContent.trim());
    });
    data.push(headers);
    
    // Get rows
    const rows = table.querySelectorAll('tbody tr');
    rows.forEach(row => {
        const rowData = [];
        const cells = row.querySelectorAll('td');
        cells.forEach(cell => {
            // Get text content or link URL
            const link = cell.querySelector('a');
            rowData.push(link ? link.textContent.trim() : cell.textContent.trim());
        });
        data.push(rowData);
    });
    
    // Convert to CSV
    const csv = data.map(row => row.join('\t')).join('\n');
    
    // Copy to clipboard
    navigator.clipboard.writeText(csv).then(() => {
        alert('Results copied to clipboard!');
    }).catch(err => {
        console.error('Failed to copy: ', err);
        alert('Failed to copy results. Please try again.');
    });
}
