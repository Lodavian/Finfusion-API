param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$targetDirectory = Join-Path $env:LOCALAPPDATA 'Finfusion\Admin'
$target = Join-Path $targetDirectory 'sandbox-broker.json'
if ($CheckOnly) {
    if (-not (Test-Path -LiteralPath $target)) { Write-Output 'Sandbox credentials have not been entered.'; exit }
    $saved = Get-Content -LiteralPath $target -Raw | ConvertFrom-Json
    foreach ($name in @('appKey', 'appSecret')) {
        $secure = ConvertTo-SecureString $saved.$name
        if ($secure.Length -lt 8) { throw 'Saved credentials are incomplete.' }
        $secure.Dispose()
    }
    Write-Output 'Encrypted Sandbox credentials are present; values not displayed.'
    exit
}
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
$form = New-Object Windows.Forms.Form
$form.Text = 'Finfusion | Webull Sandbox credentials'
$form.Size = New-Object Drawing.Size(590, 330)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$notice = New-Object Windows.Forms.Label
$notice.Location = New-Object Drawing.Point(24, 18)
$notice.Size = New-Object Drawing.Size(530, 50)
$notice.Text = "Enter Sandbox credentials only. Do not enter LIVE credentials.`r`nSaving encrypts them for this Windows user; it does not start trading."
$keyLabel = New-Object Windows.Forms.Label
$keyLabel.Text = 'Sandbox App Key'
$keyLabel.Location = New-Object Drawing.Point(24, 80)
$keyLabel.Size = New-Object Drawing.Size(180, 22)
$key = New-Object Windows.Forms.TextBox
$key.Location = New-Object Drawing.Point(24, 104)
$key.Size = New-Object Drawing.Size(530, 28)
$key.UseSystemPasswordChar = $true
$secretLabel = New-Object Windows.Forms.Label
$secretLabel.Text = 'Sandbox App Secret'
$secretLabel.Location = New-Object Drawing.Point(24, 146)
$secretLabel.Size = New-Object Drawing.Size(180, 22)
$secret = New-Object Windows.Forms.TextBox
$secret.Location = New-Object Drawing.Point(24, 170)
$secret.Size = New-Object Drawing.Size(530, 28)
$secret.UseSystemPasswordChar = $true
$save = New-Object Windows.Forms.Button
$save.Location = New-Object Drawing.Point(24, 226)
$save.Size = New-Object Drawing.Size(220, 36)
$save.Text = 'Save encrypted credentials'
$save.Add_Click({
    if ($key.Text.Trim().Length -lt 8 -or $secret.Text.Trim().Length -lt 8 -or $key.Text -match '[\r\n]' -or $secret.Text -match '[\r\n]') {
        [void][Windows.Forms.MessageBox]::Show('Please enter both single-line Sandbox credentials.')
        return
    }
    [void](New-Item -ItemType Directory -Force -Path $targetDirectory)
    $secureKey = ConvertTo-SecureString $key.Text.Trim() -AsPlainText -Force
    $secureSecret = ConvertTo-SecureString $secret.Text.Trim() -AsPlainText -Force
    try {
        [ordered]@{environment='SANDBOX'; appKey=(ConvertFrom-SecureString $secureKey); appSecret=(ConvertFrom-SecureString $secureSecret)} | ConvertTo-Json | Set-Content -LiteralPath $target -Encoding utf8
    } finally { $secureKey.Dispose(); $secureSecret.Dispose() }
    $key.Text = ''; $secret.Text = ''
    [void][Windows.Forms.MessageBox]::Show('Encrypted locally. Return to this chat and say the Sandbox credentials are saved. No service or trading switch was started.')
    $form.Close()
})
$form.Controls.AddRange(@($notice,$keyLabel,$key,$secretLabel,$secret,$save))
try { [void]$form.ShowDialog() }
finally { $key.Text='';$secret.Text='';$form.Dispose() }
