document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('fabric-cost-form');
    if (!form) return;

    form.addEventListener('submit', (e) => {
        e.preventDefault();
        
        const yarnCost = parseFloat(document.getElementById('yarn-cost').value) || 0;
        const knittingRate = parseFloat(document.getElementById('knitting-rate').value) || 0;
        const dyeingRate = parseFloat(document.getElementById('dyeing-rate').value) || 0;
        const wastage = parseFloat(document.getElementById('fabric-wastage').value) || 0;
        
        if (yarnCost < 0 || knittingRate < 0 || dyeingRate < 0) {
            alert('Rates cannot be negative.');
            return;
        }
        if (isNaN(wastage) || wastage < 0 || wastage >= 50) {
            alert('Fabric wastage must be between 0% and 50% (exclusive).');
            return;
        }
        
        const rawSum = yarnCost + knittingRate + dyeingRate;
        const totalCost = rawSum / (1 - (wastage / 100));
        const wastageCost = totalCost - rawSum;
        
        document.getElementById('calc-raw-sum').innerText = rawSum.toFixed(2);
        document.getElementById('calc-wastage-cost').innerText = wastageCost.toFixed(2);
        document.getElementById('calc-total-cost').innerText = totalCost.toFixed(2);
        
        document.getElementById('result-placeholder').style.display = 'none';
        document.getElementById('result-output').style.display = 'block';
    });
    
    form.addEventListener('reset', () => {
        document.getElementById('result-placeholder').style.display = 'flex';
        document.getElementById('result-output').style.display = 'none';
    });
});
