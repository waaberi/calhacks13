param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("host", "join")][string]$Mode,
    [string]$ServerUrl = "https://maincloud.spacetimedb.com",
    [string]$Database = "calhacks13-spatial-modeling",
    [string]$Endpoint = "127.0.0.1:8767"
)
$ErrorActionPreference = "Stop"
$bundle = Join-Path $PSScriptRoot "collaboration"
$node = Join-Path $bundle "node.exe"
$bridge = Join-Path $bundle "bridge/dist/bridge.js"
if (!(Test-Path -LiteralPath $node) -or !(Test-Path -LiteralPath $bridge)) {
    throw "Matching optional collaboration runtime is missing. Use the complete package."
}
$previousToken = $env:SPATIAL_MODELING_TOKEN
$tokenPointer = [IntPtr]::Zero
try {
    if ([string]::IsNullOrWhiteSpace($previousToken)) {
        $secureToken = Read-Host "Session token from the host add-on preferences" -AsSecureString
        $tokenPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
        $env:SPATIAL_MODELING_TOKEN = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($tokenPointer)
    }
    $endpointOption = if ($Mode -eq "host") { "--blender" } else { "--listen" }
    & $node $bridge $Mode --url $ServerUrl --database $Database $endpointOption $Endpoint
    if ($LASTEXITCODE -ne 0) { throw "Collaboration bridge exited with code $LASTEXITCODE." }
} finally {
    if ($tokenPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($tokenPointer)
    }
    $env:SPATIAL_MODELING_TOKEN = $previousToken
}
