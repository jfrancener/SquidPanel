# ==============================================================================
# TACTICAL RMM - CONFIGURAÇÃO SQUID PROXY (PAC 9011) + CERTIFICADO SSL
# ==============================================================================
$ErrorActionPreference = "SilentlyContinue"

Write-Host ">>> [1/3] Baixando e instalando o Certificado Raiz Squid CA..." -ForegroundColor Cyan
$certUrl = "http://10.40.88.5/proxy/certificate/download/"
$certPath = "$env:TEMP\squid_ca.crt"

try {
    (New-Object System.Net.WebClient).DownloadFile($certUrl, $certPath)
    if (Test-Path $certPath) {
        # Instala no repositório Raiz Confiável da Máquina Local
        certutil.exe -addstore -f Root $certPath | Out-Null
        Import-Certificate -FilePath $certPath -CertStoreLocation 'Cert:\LocalMachine\Root' | Out-Null
        Write-Host "[OK] Certificado Raiz instalado com sucesso na Maquina Local." -ForegroundColor Green
    } else {
        Write-Host "[ERRO] Nao foi possivel baixar o certificado." -ForegroundColor Red
    }
} catch {
    Write-Host "[ERRO] Falha ao baixar/instalar certificado: $_" -ForegroundColor Red
}

Write-Host "`n>>> [2/3] Aplicando Script PAC 9011 no Registro..." -ForegroundColor Cyan
$pacUrl = "http://10.40.88.5/9011.pac"

# 1. Configura em HKLM (Politica Global da Maquina)
Set-ItemProperty -Path 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -Name AutoConfigURL -Value $pacUrl -Type String
Set-ItemProperty -Path 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -Name ProxyEnable -Value 0 -Type DWord
Remove-ItemProperty -Path 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -Name ProxyServer -ErrorAction SilentlyContinue

# 2. Monta o Blob binário de conexão com Flag 0x05 (PAC Ativo)
$urlBytes = [System.Text.Encoding]::ASCII.GetBytes($pacUrl)
$urlLen = $urlBytes.Length
$blob = [System.Collections.Generic.List[byte]]::new()
$blob.AddRange([byte[]]@(0x46, 0x00, 0x00, 0x00, 0x0E, 0x00, 0x00, 0x00, 0x05, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x07, 0x00, 0x00, 0x00))
$blob.AddRange([System.Text.Encoding]::ASCII.GetBytes("<local>"))
$blob.AddRange([BitConverter]::GetBytes([int]$urlLen))
$blob.AddRange($urlBytes)
for ($i = 0; $i -lt 32; $i++) { $blob.Add(0x00) }
$finalBytes = $blob.ToArray()

# 3. Aplica nas Conexoes de HKLM
$hklmConn = 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Internet Settings\Connections'
if (-not (Test-Path $hklmConn)) { New-Item -Path $hklmConn -Force | Out-Null }
Set-ItemProperty -Path $hklmConn -Name DefaultConnectionSettings -Value $finalBytes -Type Binary
Set-ItemProperty -Path $hklmConn -Name SavedLegacySettings -Value $finalBytes -Type Binary

# 4. Aplica em TODOS os Perfis de Usuarios existentes (HKEY_USERS)
Get-ChildItem Registry::HKEY_USERS | ForEach-Object {
    $sub = $_.PSChildName
    if ($sub -match '^S-1-5-21-' -and $sub -notmatch '_Classes$') {
        $uSettings = "Registry::HKEY_USERS\$sub\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        Set-ItemProperty -Path $uSettings -Name AutoConfigURL -Value $pacUrl -Type String -ErrorAction SilentlyContinue
        Set-ItemProperty -Path $uSettings -Name ProxyEnable -Value 0 -Type DWord -ErrorAction SilentlyContinue
        Remove-ItemProperty -Path $uSettings -Name ProxyServer -ErrorAction SilentlyContinue

        $uConn = "$uSettings\Connections"
        if (-not (Test-Path $uConn)) { New-Item -Path $uConn -Force -ErrorAction SilentlyContinue | Out-Null }
        Set-ItemProperty -Path $uConn -Name DefaultConnectionSettings -Value $finalBytes -Type Binary -ErrorAction SilentlyContinue
        Set-ItemProperty -Path $uConn -Name SavedLegacySettings -Value $finalBytes -Type Binary -ErrorAction SilentlyContinue
    }
}

# 5. Aplica no perfil Default (para novos usuarios criados)
reg.exe load "HKU\DefaultUser" "C:\Users\Default\NTUSER.DAT" 2>$null | Out-Null
if (Test-Path "Registry::HKEY_USERS\DefaultUser") {
    Set-ItemProperty -Path "Registry::HKEY_USERS\DefaultUser\Software\Microsoft\Windows\CurrentVersion\Internet Settings" -Name AutoConfigURL -Value $pacUrl -Type String -ErrorAction SilentlyContinue
    Set-ItemProperty -Path "Registry::HKEY_USERS\DefaultUser\Software\Microsoft\Windows\CurrentVersion\Internet Settings" -Name ProxyEnable -Value 0 -Type DWord -ErrorAction SilentlyContinue
    reg.exe unload "HKU\DefaultUser" 2>$null | Out-Null
}

Write-Host "[OK] PAC 9011 configurado em todos os perfis de usuario." -ForegroundColor Green

Write-Host "`n>>> [3/3] Reiniciando navegadores..." -ForegroundColor Cyan
taskkill.exe /F /IM chrome.exe /IM msedge.exe /IM brave.exe /IM firefox.exe 2>$null | Out-Null

Write-Host "`n==========================================================" -ForegroundColor Yellow
Write-Host " SUCESSO: PIJ-VC-AGENTE configurado com PAC 9011 e Certificado!" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Yellow
