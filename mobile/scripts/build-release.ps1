param(
    [string]$SigningConfig = (Join-Path $HOME 'BuildVision-signing\signing.json'),
    [string]$ApiBaseUrl = $env:VITE_API_BASE_URL
)

if (!$ApiBaseUrl) {
    throw 'Pass -ApiBaseUrl (or set $env:VITE_API_BASE_URL) to the production API URL before building a release.'
}

$ErrorActionPreference = 'Stop'
$mobileRoot = Split-Path $PSScriptRoot -Parent
$androidRoot = Join-Path $mobileRoot 'android'
$releaseDirectory = Join-Path $mobileRoot 'release'

if (!(Test-Path -LiteralPath $SigningConfig -PathType Leaf)) {
    throw 'Private signing configuration is missing. Never substitute the Android debug key.'
}
if (!$env:JAVA_HOME -or !(Test-Path (Join-Path $env:JAVA_HOME 'bin\keytool.exe'))) {
    throw 'Set JAVA_HOME to a JDK 21 installation.'
}
$sdk = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } else { $env:ANDROID_SDK_ROOT }
if (!$sdk -or !(Test-Path (Join-Path $sdk 'build-tools'))) {
    throw 'Set ANDROID_HOME or ANDROID_SDK_ROOT to the Android SDK.'
}
$tools = Get-ChildItem (Join-Path $sdk 'build-tools') -Directory |
    Where-Object { $_.Name -match '^\d+\.\d+\.\d+$' } |
    Sort-Object { [version]$_.Name } -Descending |
    Select-Object -First 1
if (!$tools) {
    throw 'Android build-tools are missing.'
}

$configuration = Get-Content -LiteralPath $SigningConfig -Raw | ConvertFrom-Json
foreach ($field in @('storeFile', 'storePassword', 'keyAlias', 'keyPassword', 'certificateSha256')) {
    if (!$configuration.$field) {
        throw "Private signing configuration is missing field: $field"
    }
}
if (!(Test-Path -LiteralPath $configuration.storeFile -PathType Leaf)) {
    throw 'The configured release keystore does not exist.'
}

$names = @(
    'VITE_API_BASE_URL', 'BUILDVISION_STORE_FILE', 'BUILDVISION_STORE_TYPE',
    'BUILDVISION_STORE_PASSWORD', 'BUILDVISION_KEY_ALIAS', 'BUILDVISION_KEY_PASSWORD'
)
$previous = @{}
foreach ($name in $names) {
    $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

try {
    # Vite-prefixed values are public; only the HTTPS API URL is provided.
    $env:VITE_API_BASE_URL = $ApiBaseUrl
    & npm.cmd --prefix $mobileRoot run lint
    if ($LASTEXITCODE -ne 0) { throw 'Mobile lint failed.' }
    & npm.cmd --prefix $mobileRoot run cap:sync
    if ($LASTEXITCODE -ne 0) { throw 'Mobile build or Capacitor sync failed.' }

    # Passwords are provided to Gradle and keytool through process environment,
    # never through command-line arguments, VITE variables, or repository files.
    $env:BUILDVISION_STORE_FILE = $configuration.storeFile
    $env:BUILDVISION_STORE_TYPE = if ($configuration.storeType) { $configuration.storeType } else { 'PKCS12' }
    $env:BUILDVISION_STORE_PASSWORD = $configuration.storePassword
    $env:BUILDVISION_KEY_ALIAS = $configuration.keyAlias
    $env:BUILDVISION_KEY_PASSWORD = $configuration.keyPassword
    & (Join-Path $androidRoot 'gradlew.bat') -p $androidRoot lintRelease assembleRelease `
        --no-daemon --no-configuration-cache --console=plain
    if ($LASTEXITCODE -ne 0) { throw 'Android release validation or build failed.' }

    $apkDirectory = Join-Path $androidRoot 'app\build\outputs\apk\release'
    $metadata = Get-Content (Join-Path $apkDirectory 'output-metadata.json') -Raw | ConvertFrom-Json
    if ($metadata.variantName -ne 'release' -or $metadata.applicationId -ne 'ru.buildvision.app' -or
        $metadata.elements.Count -ne 1) {
        throw 'Unexpected release metadata.'
    }
    $artifact = $metadata.elements[0]
    $apk = Join-Path $apkDirectory $artifact.outputFile
    $signature = & (Join-Path $tools.FullName 'apksigner.bat') verify --verbose --print-certs $apk
    if ($LASTEXITCODE -ne 0) { throw 'APK signature verification failed.' }
    $signatureText = $signature -join "`n"
    if ($signatureText -match 'CN=Android Debug') {
        throw 'A debug certificate must not be published.'
    }
    $expectedFingerprint = $configuration.certificateSha256.Replace(':', '').ToLowerInvariant()
    if ($signatureText -notmatch "certificate SHA-256 digest: $expectedFingerprint") {
        throw 'APK certificate differs from the configured release identity.'
    }
    & (Join-Path $tools.FullName 'zipalign.exe') -c -P 16 4 $apk
    if ($LASTEXITCODE -ne 0) { throw 'APK alignment verification failed.' }
    $badging = & (Join-Path $tools.FullName 'aapt2.exe') dump badging $apk
    if ($LASTEXITCODE -ne 0) { throw 'APK manifest inspection failed.' }
    $badgingText = $badging -join "`n"
    if ($badgingText -match 'application-debuggable' -or
        $badgingText -notmatch "package: name='ru\.buildvision\.app'" -or
        $badgingText -notmatch "sdkVersion:'23'" -or
        $badgingText -notmatch "targetSdkVersion:'35'") {
        throw 'APK package, SDK levels or debuggable flag do not match the release configuration.'
    }

    New-Item -ItemType Directory -Path $releaseDirectory -Force | Out-Null
    $filename = "BuildVision-$($artifact.versionName)-$($artifact.versionCode).apk"
    $destination = Join-Path $releaseDirectory $filename
    Copy-Item -LiteralPath $apk -Destination $destination
    Copy-Item (Join-Path $mobileRoot 'resources\rustore-icon-512.png') -Destination $releaseDirectory
    & (Join-Path $env:JAVA_HOME 'bin\keytool.exe') -exportcert -rfc `
        -keystore $env:BUILDVISION_STORE_FILE -storepass:env BUILDVISION_STORE_PASSWORD `
        -alias $env:BUILDVISION_KEY_ALIAS -file (Join-Path $releaseDirectory 'release-certificate.pem')
    if ($LASTEXITCODE -ne 0) { throw 'Public certificate export failed.' }
    $hash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $filename" | Set-Content (Join-Path $releaseDirectory 'SHA256SUMS.txt') -Encoding utf8
    $summary = [ordered]@{
        applicationId = $metadata.applicationId
        versionName = $artifact.versionName
        versionCode = $artifact.versionCode
        variant = 'release'
        debuggable = $false
        minSdk = 23
        targetSdk = 35
        certificateSha256 = $expectedFingerprint
        apkSha256 = $hash
        apkFile = $filename
        nativeDeviceTested = $false
    }
    $summary | ConvertTo-Json | Set-Content (Join-Path $releaseDirectory 'release-info.json') -Encoding utf8
    $summary | ConvertTo-Json
    Write-Output "Signed release APK: $destination"
}
finally {
    foreach ($name in $names) {
        [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process')
    }
    $configuration = $null
}
