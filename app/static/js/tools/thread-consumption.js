document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('thread-form');
    if (!form) return;

    form.addEventListener('submit', (e) => {
        e.preventDefault();
        
        const seamLength = parseFloat(document.getElementById('seam-length').value);
        const stitchClass = document.getElementById('stitch-class').value;
        const wastage = parseFloat(document.getElementById('wastage').value) || 0;
        
        if (isNaN(seamLength) || seamLength <= 0) {
            alert('Please enter a valid positive seam length.');
            return;
        }
        if (isNaN(wastage) || wastage < 0 || wastage > 100) {
            alert('Wastage must be between 0% and 100%.');
            return;
        }
        
        let multiplier = 2.5; // Default 301
        if (stitchClass === '401') {
            multiplier = 4.5;
        } else if (stitchClass === '504') {
            multiplier = 14.0;
        }
        
        const rawThread = seamLength * multiplier;
        const totalThread = rawThread * (1 + (wastage / 100));
        
        document.getElementById('calc-multiplier').innerText = multiplier.toFixed(1) + 'x';
        document.getElementById('calc-raw-val').innerText = rawThread.toFixed(2) + ' m';
        document.getElementById('calc-thread-val').innerText = totalThread.toFixed(2) + ' meters';
        
        document.getElementById('result-placeholder').style.display = 'none';
        document.getElementById('result-output').style.display = 'block';
    });
    
    form.addEventListener('reset', () => {
        document.getElementById('result-placeholder').style.display = 'flex';
        document.getElementById('result-output').style.display = 'none';
    });
});
