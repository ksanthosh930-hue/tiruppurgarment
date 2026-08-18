document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('cm-form');
    if (!form) return;

    form.addEventListener('submit', (e) => {
        e.preventDefault();
        
        const operators = parseInt(document.getElementById('operators-count').value) || 0;
        const wage = parseFloat(document.getElementById('operator-wage').value) || 0;
        const overhead = parseFloat(document.getElementById('line-overhead').value) || 0;
        const target = parseFloat(document.getElementById('target-output').value) || 0;
        const efficiency = parseFloat(document.getElementById('line-efficiency').value) || 0;
        
        if (operators <= 0 || target <= 0 || efficiency <= 0) {
            alert('Operators count, daily target output, and expected efficiency must be positive numbers.');
            return;
        }
        if (wage < 0 || overhead < 0) {
            alert('Wages and overheads cannot be negative.');
            return;
        }
        if (efficiency > 150) {
            alert('Efficiency cannot exceed 150%.');
            return;
        }
        
        const totalDailyOperatingCost = overhead + (operators * wage);
        const actualExpectedOutput = target * (efficiency / 100);
        const cmCostPerGarment = totalDailyOperatingCost / actualExpectedOutput;
        
        document.getElementById('calc-daily-operating').innerText = totalDailyOperatingCost.toFixed(2);
        document.getElementById('calc-expected-target').innerText = actualExpectedOutput.toFixed(0) + ' pcs';
        document.getElementById('calc-cm-cost').innerText = cmCostPerGarment.toFixed(2);
        
        document.getElementById('result-placeholder').style.display = 'none';
        document.getElementById('result-output').style.display = 'block';
    });
    
    form.addEventListener('reset', () => {
        document.getElementById('result-placeholder').style.display = 'flex';
        document.getElementById('result-output').style.display = 'none';
    });
});
