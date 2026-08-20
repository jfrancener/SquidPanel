# ==============================================================================
# TACTICAL RMM - CONFIGURAÇÃO SQUID PROXY (PAC 9011) + CERTIFICADO SSL + BLOQUEIO
# ==============================================================================
$ErrorActionPreference = "SilentlyContinue"

Write-Host ">>> [1/4] Baixando e instalando o Certificado Raiz Squid CA..." -ForegroundColor Cyan
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

Write-Host "`n>>> [2/4] Aplicando Script PAC 9011 no Registro..." -ForegroundColor Cyan
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

Write-Host "`n>>> [3/4] Aplicando Bloqueios de Diretiva (GPO Local e Navegadores)..." -ForegroundColor Cyan

# A) Força proxy por máquina (ignora bypass por usuário)
Set-ItemProperty -Path 'HKLM:\Software\Policies\Microsoft\Windows\CurrentVersion\Internet Settings' -Name 'ProxySettingsPerUser' -Value 0 -Type DWord -Force

# B) Desabilita interface de configurações de Proxy no Painel de Controle e Configurações do Windows
$controlPanelKey = 'HKLM:\Software\Policies\Microsoft\Internet Explorer\Control Panel'
if (-not (Test-Path $controlPanelKey)) { New-Item -Path $controlPanelKey -Force | Out-Null }
Set-ItemProperty -Path $controlPanelKey -Name 'Proxy' -Value 1 -Type DWord -Force
Set-ItemProperty -Path $controlPanelKey -Name 'Connection Settings' -Value 1 -Type DWord -Force
Set-ItemProperty -Path $controlPanelKey -Name 'Connwiz Admin' -Value 1 -Type DWord -Force

# C) Força Script PAC via Políticas do Google Chrome
$chromePol = 'HKLM:\Software\Policies\Google\Chrome'
if (-not (Test-Path $chromePol)) { New-Item -Path $chromePol -Force | Out-Null }
Set-ItemProperty -Path $chromePol -Name 'ProxyMode' -Value 'pac_script' -Type String -Force
Set-ItemProperty -Path $chromePol -Name 'ProxyPacUrl' -Value $pacUrl -Type String -Force

# D) Força Script PAC via Políticas do Microsoft Edge
$edgePol = 'HKLM:\Software\Policies\Microsoft\Edge'
if (-not (Test-Path $edgePol)) { New-Item -Path $edgePol -Force | Out-Null }
Set-ItemProperty -Path $edgePol -Name 'ProxyMode' -Value 'pac_script' -Type String -Force
Set-ItemProperty -Path $edgePol -Name 'ProxyPacUrl' -Value $pacUrl -Type String -Force

# E) Bloqueia no HKEY_USERS das contas logadas
Get-ChildItem Registry::HKEY_USERS | ForEach-Object {
    $sub = $_.PSChildName
    if ($sub -match '^S-1-5-21-' -and $sub -notmatch '_Classes$') {
        $uCp = "Registry::HKEY_USERS\$sub\Software\Policies\Microsoft\Internet Explorer\Control Panel"
        if (-not (Test-Path $uCp)) { New-Item -Path $uCp -Force -ErrorAction SilentlyContinue | Out-Null }
        Set-ItemProperty -Path $uCp -Name 'Proxy' -Value 1 -Type DWord -Force -ErrorAction SilentlyContinue
        Set-ItemProperty -Path $uCp -Name 'Connection Settings' -Value 1 -Type DWord -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "[OK] Diretivas de bloqueio aplicadas com sucesso (Windows, Chrome e Edge)." -ForegroundColor Green

Write-Host "`n>>> [4/4] Reiniciando navegadores..." -ForegroundColor Cyan
taskkill.exe /F /IM chrome.exe /IM msedge.exe /IM brave.exe /IM firefox.exe 2>$null | Out-Null

Write-Host "`n==========================================================" -ForegroundColor Yellow
Write-Host " SUCESSO: Proxy PAC 9011 configurado e BLOQUEADO para alteracoes!" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Yellow
