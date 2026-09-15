# Skaliert die generierten Schadensfotos auf 1024 px JPEG, baut einen Kontaktabzug
# und schreibt MD5-Summen. 1024 px entspricht DAMAGE_MAX_EDGE im Backend.
param(
    [string]$Quelle = "$HOME\Downloads",
    [Parameter(Mandatory = $true)][string]$Ziel,
    [string]$Muster = "damage_*.png",
    [int]$Kante = 1024,
    [int]$Qualitaet = 88
)

Add-Type -AssemblyName System.Drawing

$originale = Get-ChildItem $Quelle -File -Filter $Muster | Sort-Object Name
if ($originale.Count -eq 0) { throw "Keine Dateien '$Muster' in $Quelle gefunden." }

$fotos = Join-Path $Ziel "fotos"
$rohdaten = Join-Path $Ziel "fotos_original"
New-Item -ItemType Directory -Force $fotos, $rohdaten | Out-Null

$encoder = [System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() | Where-Object { $_.MimeType -eq 'image/jpeg' }
$parameter = New-Object System.Drawing.Imaging.EncoderParameters(1)
$parameter.Param[0] = New-Object System.Drawing.Imaging.EncoderParameter([System.Drawing.Imaging.Encoder]::Quality, [long]$Qualitaet)

$index = 0
$ziele = @()
foreach ($datei in $originale) {
    $index++
    $nummer = '{0:d2}' -f $index
    Copy-Item $datei.FullName (Join-Path $rohdaten $datei.Name) -Force

    $bild = [System.Drawing.Image]::FromFile($datei.FullName)
    $leinwand = New-Object System.Drawing.Bitmap($Kante, $Kante)
    $grafik = [System.Drawing.Graphics]::FromImage($leinwand)
    $grafik.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $grafik.DrawImage($bild, 0, 0, $Kante, $Kante)
    $grafik.Dispose(); $bild.Dispose()

    $ausgabe = Join-Path $fotos "qa_photo_$nummer.jpg"
    $leinwand.Save($ausgabe, $encoder, $parameter)
    $leinwand.Dispose()
    $ziele += $ausgabe
}

# Kontaktabzug über alle Perspektiven
$zelle = 260
$blatt = New-Object System.Drawing.Bitmap(($zelle * $ziele.Count), $zelle)
$grafik = [System.Drawing.Graphics]::FromImage($blatt)
$grafik.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
for ($i = 0; $i -lt $ziele.Count; $i++) {
    $bild = [System.Drawing.Image]::FromFile($ziele[$i])
    $grafik.DrawImage($bild, ($i * $zelle), 0, $zelle, $zelle)
    $bild.Dispose()
}
$grafik.Dispose()
$blatt.Save((Join-Path $Ziel "kontaktabzug.jpg"), [System.Drawing.Imaging.ImageFormat]::Jpeg)
$blatt.Dispose()

# Prüfsummen als Nachweis der Unterscheidbarkeit.
# @(...) erzwingt Arrays — bei genau einer Datei würde + sonst Strings verketten.
Get-FileHash (@($originale.FullName) + @($ziele)) -Algorithm MD5 |
    Select-Object @{n = 'Datei'; e = { Split-Path $_.Path -Leaf } }, Hash |
    Tee-Object (Join-Path $Ziel "pruefsummen.txt")

$gesamt = [math]::Round(((Get-ChildItem $fotos -Filter '*.jpg' | Measure-Object Length -Sum).Sum / 1KB), 0)
"Aufbereitet: $($ziele.Count) Fotos, $gesamt KB gesamt (Limit file_upload: 10 MB)"
