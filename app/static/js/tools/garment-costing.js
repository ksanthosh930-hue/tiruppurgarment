document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('garment-cost-form');
    if (!form) return;

    form.addEventListener('submit', (e) => {
        e.preventDefault();
        
        const fabricCost = parseFloat(document.getElementById('fabric-cost-input').value) || 0;
        const cmCost = parseFloat(document.getElementById('cm-cost-input').value) || 0;
        const trimsCost = parseFloat(document.getElementById('trims-cost-input').value) || 0;
        const accessoriesCost = parseFloat(document.getElementById('acc-cost-input').value) || 0;
        const logisticsCost = parseFloat(document.getElementById('log-cost-input').value) || 0;
        const margin = parseFloat(document.getElementById('margin-percent').value) || 0;
        
        if (fabricCost < 0 || cmCost < 0 || trimsCost < 0 || accessoriesCost < 0 || logisticsCost < 0) {
            alert('Cost parameters cannot be negative numbers.');
            return;
        }
        if (isNaN(margin) || margin < -50 || margin > 200) {
            alert('Margin percentage must be between -50% and 200%.');
            return;
        }
        
        const totalBaseCost = fabricCost + cmCost + trimsCost + accessoriesCost + logisticsCost;
        const fobPrice = totalBaseCost * (1 + (margin / 100));
        const profitValue = fobPrice - totalBaseCost;
        
        document.getElementById('calc-base-val').innerText = '$' + totalBaseCost.toFixed(2);
        document.getElementById('calc-profit-val').innerText = '$' + profitValue.toFixed(2);
        document.getElementById('calc-fob-val').innerText = '$' + fobPrice.toFixed(2);
        
        document.getElementById('result-placeholder').style.display = 'none';
        document.getElementById('result-output').style.display = 'block';
    });
    
    form.addEventListener('reset', () => {
        document.getElementById('result-placeholder').style.display = 'flex';
        document.getElementById('result-output').style.display = 'none';
    });
});
