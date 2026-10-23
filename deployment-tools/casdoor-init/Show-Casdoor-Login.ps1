param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$credentialFile = Join-Path $env:LOCALAPPDATA 'Finfusion\Admin\casdoor-login.json'
if (-not (Test-Path -LiteralPath $credentialFile)) { throw 'Local encrypted Casdoor credentials are missing.' }
$saved = Get-Content -LiteralPath $credentialFile -Raw | ConvertFrom-Json
function Read-LocalPassword($entry) {
    $secure = ConvertTo-SecureString $entry.password
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer); $secure.Dispose() }
}
if ($CheckOnly) {
    foreach ($entry in $saved.accounts) {
        $value = Read-LocalPassword $entry
        if ($value.Length -lt 24) { throw 'Credential validation failed.' }
        $value = $null
    }
    Write-Output 'Windows user-bound encrypted credentials validated; no secrets displayed.'
    exit
}
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
$form = New-Object Windows.Forms.Form
$form.Text = 'Finfusion | Casdoor login'
$form.Size = New-Object Drawing.Size(550, 390)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$label = New-Object Windows.Forms.Label
$label.Location = New-Object Drawing.Point(24, 20)
$label.Size = New-Object Drawing.Size(490, 42)
$label.Text = "Casdoor account: manages organizations and users.`r`nFinfusion account: signs in to the future Finfusion admin service."
$form.Controls.Add($label)
$selector = New-Object Windows.Forms.ComboBox
$selector.Location = New-Object Drawing.Point(24, 76)
$selector.Size = New-Object Drawing.Size(480, 28)
$selector.DropDownStyle = 'DropDownList'
$saved.accounts | ForEach-Object { [void]$selector.Items.Add($_.organization + ' / ' + $_.username) }
$username = New-Object Windows.Forms.TextBox
$username.Location = New-Object Drawing.Point(24, 120)
$username.Size = New-Object Drawing.Size(480, 28)
$username.ReadOnly = $true
$password = New-Object Windows.Forms.TextBox
$password.Location = New-Object Drawing.Point(24, 160)
$password.Size = New-Object Drawing.Size(480, 28)
$password.ReadOnly = $true
$password.UseSystemPasswordChar = $true
$show = New-Object Windows.Forms.CheckBox
$show.Location = New-Object Drawing.Point(24, 204)
$show.Size = New-Object Drawing.Size(200, 28)
$show.Text = 'Show initial password'
$show.Add_CheckedChanged({ $password.UseSystemPasswordChar = -not $show.Checked })
$open = New-Object Windows.Forms.Button
$open.Location = New-Object Drawing.Point(24, 248)
$open.Size = New-Object Drawing.Size(220, 36)
$open.Text = 'Open login page'
$open.Add_Click({
    $entry = $saved.accounts[$selector.SelectedIndex]
    $loginUrl = if ($entry.organization -eq 'built-in') { $saved.url + '/login' } else { $saved.url + '/login/finfusion-admin' }
    Start-Process $loginUrl
})
$notice = New-Object Windows.Forms.Label
$notice.Location = New-Object Drawing.Point(24, 300)
$notice.Size = New-Object Drawing.Size(490, 38)
$notice.Text = 'Passwords are encrypted for this Windows user. After changing a password, this initial-password record will be outdated.'
$selector.Add_SelectedIndexChanged({
    $entry = $saved.accounts[$selector.SelectedIndex]
    $username.Text = $entry.username
    $password.Text = Read-LocalPassword $entry
})
$form.Controls.AddRange(@($selector, $username, $password, $show, $open, $notice))
$selector.SelectedIndex = 0
try { [void]$form.ShowDialog() }
finally { $password.Text = ''; $form.Dispose() }
