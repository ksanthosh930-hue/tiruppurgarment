document.addEventListener('DOMContentLoaded', () => {
    const samForm = document.getElementById('sam-form');
    if (samForm) {
        samForm.addEventListener('submit', (e) => {
            e.preventDefault();
            calculateSAM();
        });
        
        samForm.addEventListener('reset', () => {
            document.getElementById('result-placeholder').style.display = 'block';
            document.getElementById('result-output').style.display = 'none';
        });
    }
    
    function calculateSAM() {
        const smvInput = document.getElementById('smv');
        const allowanceInput = document.getElementById('allowance');
        const efficiencyInput = document.getElementById('efficiency');
        
        const smv = parseFloat(smvInput.value);
        const allowance = parseFloat(allowanceInput.value) || 0;
        const efficiency = parseFloat(efficiencyInput.value) || 100;
        
        if (isNaN(smv) || smv <= 0) {
            alert('Please enter a valid SMV value greater than 0.');
            return;
        }
        
        // Calculate SAM = SMV * (1 + Allowance / 100)
        const sam = smv * (1 + (allowance / 100));
        
        // Target per operator per hour = (60 / SAM) * (Efficiency / 100)
        const targetPerHour = (60 / sam) * (efficiency / 100);
        
        // Display results
        document.getElementById('result-placeholder').style.display = 'none';
        
        const outputDiv = document.getElementById('result-output');
        outputDiv.style.display = 'block';
        
        document.getElementById('calc-sam-val').innerText = sam.toFixed(3) + ' mins';
        document.getElementById('calc-target-val').innerText = targetPerHour.toFixed(1) + ' pcs/hr';
    }
});
