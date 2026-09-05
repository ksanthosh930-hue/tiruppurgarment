"""
Native OCR Engine for DigiGarment Tiruppur Jobs.
Extracts verbatim text from job flyers, WhatsApp posters, and camera photos.
Uses high-accuracy Windows Native WinRT OCR on Windows environments with zero third-party dependencies,
and falls back gracefully to standard OCR or safe text preservation.
"""

import os
import sys
import uuid
import logging
import subprocess
from typing import Optional

logger = logging.getLogger("DigiGarment.OCREngine")

def _clean_ocr_text(text: str) -> str:
    if not text:
        return ""
    # Normalize unicode hyphens and OCR artifacts
    text = text.replace("\u2013", "-").replace("\u2014", "-").replace("\u2015", "-").replace("–", "-").replace("—", "-")
    text = text.replace("\ufffd", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Clean up multi-space runs but preserve line breaks
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join([l for l in lines if l])

def extract_text_from_image_file(image_path: str) -> str:
    """
    Extracts text from an image file path using native OS capabilities.
    """
    if not image_path or not os.path.exists(image_path):
        return ""

    abs_path = os.path.abspath(image_path)

    # Windows Native OCR via WinRT PowerShell
    if sys.platform.startswith("win"):
        try:
            ps_script = f"""
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = [System.WindowsRuntimeSystemExtensions].GetMethods() | ? {{ $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' }} | Select -First 1

function AwaitOp($op, $type) {{
    $netTask = $asTaskGeneric.MakeGenericMethod($type).Invoke($null, @($op))
    $null = $netTask.Wait(10000)
    return $netTask.Result
}}

[Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine, Windows.Foundation.UniversalApiContract, ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation.UniversalApiContract, ContentType=WindowsRuntime] | Out-Null

$imgFile = AwaitOp ([Windows.Storage.StorageFile]::GetFileFromPathAsync("{abs_path}")) ([Windows.Storage.StorageFile])
if (-not $imgFile) {{ exit 1 }}

$stream = AwaitOp ($imgFile.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = AwaitOp ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = AwaitOp ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if (-not $engine) {{
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new("en-US"))
}}

if ($engine -and $bitmap) {{
    $ocrRes = AwaitOp ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    Write-Output $ocrRes.Text
}}
"""
            res = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=15
            )
            if res.returncode == 0 and res.stdout.strip():
                return _clean_ocr_text(res.stdout)
        except Exception as e:
            logger.warning(f"Windows native OCR failed for {abs_path}: {e}")

    # Fallback to pytesseract if installed in environment
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(abs_path)
        text = pytesseract.image_to_string(img)
        if text.strip():
            return _clean_ocr_text(text)
    except Exception:
        pass

    return ""

def extract_text_from_image_bytes(image_bytes: bytes, suffix: str = ".jpeg") -> str:
    """
    Extracts text from raw image bytes.
    """
    if not image_bytes:
        return ""
    
    # Save bytes to temporary file for OCR processing
    temp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "uploads", "source_vault")
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = os.path.join(temp_dir, f"_temp_ocr_{uuid.uuid4().hex[:12]}{suffix}")
    
    try:
        with open(temp_path, "wb") as f:
            f.write(image_bytes)
        return extract_text_from_image_file(temp_path)
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
