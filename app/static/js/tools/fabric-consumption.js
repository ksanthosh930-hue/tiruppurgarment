document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('fabric-cons-form');
    if (!form) return;

    form.addEventListener('submit', (e) => {
        e.preventDefault();
        
        const chest = parseFloat(document.getElementById('chest-width').value);
        const bodyLength = parseFloat(document.getElementById('body-length').value);
        const gsm = parseFloat(document.getElementById('gsm').value);
        const wastage = parseFloat(document.getElementById('wastage').value) || 0;
        
        if (isNaN(chest) || chest <= 0 || isNaN(bodyLength) || bodyLength <= 0 || isNaN(gsm) || gsm <= 0) {
            alert('Please enter valid positive values for Chest, Body Length and GSM.');
            return;
        }
        if (isNaN(wastage) || wastage < 0 || wastage > 100) {
            alert('Wastage must be between 0% and 100%.');
            return;
        }
        
        const seamAllowance = 2; // Fixed defaults (+2cm)
        const hemAllowance = 4; // Fixed defaults (+4cm)
        
        const finalLength = bodyLength + hemAllowance;
        const finalWidth = chest + seamAllowance;
        
        // Single garment fabric weight in grams
        const rawWeight = (finalLength * finalWidth * 2 * gsm) / 10000;
        const totalWeight = rawWeight * (1 + (wastage / 100));
        
        // Weight per dozen in kg
        const dozenKg = (totalWeight * 12) / 1000;
        
        document.getElementById('calc-raw-weight').innerText = rawWeight.toFixed(1) + ' g';
        document.getElementById('calc-weight-val').innerText = totalWeight.toFixed(1) + ' grams';
        document.getElementById('calc-dozen-val').innerText = dozenKg.toFixed(2) + ' kg';
        
        document.getElementById('result-placeholder').style.display = 'none';
        document.getElementById('result-output').style.display = 'block';
    });
    
    form.addEventListener('reset', () => {
        document.getElementById('result-placeholder').style.display = 'flex';
        document.getElementById('result-output').style.display = 'none';
    });
});
