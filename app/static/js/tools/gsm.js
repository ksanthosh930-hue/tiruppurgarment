document.addEventListener('DOMContentLoaded', () => {
    const gsmForm = document.getElementById('gsm-form');
    const swatchTypeSelect = document.getElementById('swatch-type');
    const rectangularFields = document.getElementById('rectangular-fields');
    
    if (swatchTypeSelect && rectangularFields) {
        swatchTypeSelect.addEventListener('change', () => {
            if (swatchTypeSelect.value === 'rectangular') {
                rectangularFields.style.display = 'block';
                document.getElementById('swatch-length').required = true;
                document.getElementById('swatch-width').required = true;
            } else {
                rectangularFields.style.display = 'none';
                document.getElementById('swatch-length').required = false;
                document.getElementById('swatch-width').required = false;
            }
        });
    }
    
    if (gsmForm) {
        gsmForm.addEventListener('submit', (e) => {
            e.preventDefault();
            calculateGSM();
        });
        
        gsmForm.addEventListener('reset', () => {
            document.getElementById('result-placeholder').style.display = 'block';
            document.getElementById('result-output').style.display = 'none';
            if (rectangularFields) {
                rectangularFields.style.display = 'none';
            }
        });
    }
    
    function calculateGSM() {
        const type = swatchTypeSelect ? swatchTypeSelect.value : 'circular';
        const weightInput = document.getElementById('swatch-weight');
        const weight = parseFloat(weightInput.value);
        
        if (isNaN(weight) || weight <= 0) {
            alert('Please enter a valid weight in grams.');
            return;
        }
        
        let gsm = 0;
        let areaCm2 = 0;
        
        if (type === 'rectangular') {
            const lengthInput = document.getElementById('swatch-length');
            const widthInput = document.getElementById('swatch-width');
            const length = parseFloat(lengthInput.value);
            const width = parseFloat(widthInput.value);
            
            if (isNaN(length) || length <= 0 || isNaN(width) || width <= 0) {
                alert('Please enter valid length and width in cm.');
                return;
            }
            areaCm2 = length * width;
            gsm = (weight * 10000) / areaCm2;
        } else {
            // Circular sample area (standard cutter is 100 cm2)
            areaCm2 = 100;
            gsm = weight * 100;
        }
        
        // Display results
        document.getElementById('result-placeholder').style.display = 'none';
        
        const outputDiv = document.getElementById('result-output');
        outputDiv.style.display = 'block';
        
        document.getElementById('calc-gsm-val').innerText = gsm.toFixed(1) + ' g/m²';
        document.getElementById('calc-area-val').innerText = areaCm2.toFixed(1) + ' cm²';
        
        // Output material classification suggestion
        let classification = 'Light Weight (e.g. T-shirt, Voile, Chiffon)';
        if (gsm > 150 && gsm <= 250) {
            classification = 'Medium Weight (e.g. Polo pique, Linen, Oxford)';
        } else if (gsm > 250) {
            classification = 'Heavy Weight (e.g. Sweatshirt fleece, Denim, Canvas)';
        }
        document.getElementById('calc-class-val').innerText = classification;
    }
});
