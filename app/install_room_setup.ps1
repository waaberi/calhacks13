param(
    [Parameter(Mandatory=$true)][string]$Adb,
    [Parameter(Mandatory=$true)][string]$Apk,
    [switch]$Launch
)
$ErrorActionPreference='Stop'
if(!(Test-Path -LiteralPath $Adb -PathType Leaf) -or !(Test-Path -LiteralPath $Apk -PathType Leaf)) {
    throw 'Supply the real adb.exe and built Room Setup APK paths.'
}
$state=& $Adb get-state 2>&1
if($LASTEXITCODE -ne 0 -or ($state -join '') -ne 'device') {
    throw 'Quest is not authorized for ADB. Connect USB and allow USB debugging on the headset; no app was installed.'
}
Get-FileHash -LiteralPath $Apk -Algorithm SHA256
& $Adb install -r $Apk
if($LASTEXITCODE -ne 0) {throw 'APK installation failed; existing app/data was preserved.'}
if($Launch) {
    # Let Android resolve the actual Unity activity, rather than guessing its class.
    $activity=& $Adb shell cmd package resolve-activity --brief com.calhacks13.roomsetup
    $component=$activity | Where-Object {$_ -match '^com\.calhacks13\.roomsetup/'} | Select-Object -Last 1
    if(!$component) {throw 'Installed package has no resolved launch activity.'}
    & $Adb shell am start -n $component
    if($LASTEXITCODE -ne 0) {throw 'Room Setup did not launch.'}
}
