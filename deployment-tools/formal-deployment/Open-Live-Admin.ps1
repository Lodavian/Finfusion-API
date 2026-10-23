$ErrorActionPreference = 'Stop'
wsl.exe -d Ubuntu -u root --cd / -- systemctl start casdoor.service finfusion.service nginx.service finfusion-api-tunnel.service
if ($LASTEXITCODE -ne 0) { throw 'Ubuntu services failed to start.' }
Start-Process 'http://127.0.0.1:8081/admin/'
