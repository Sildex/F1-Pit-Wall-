$dir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$shell = New-Object -ComObject WScript.Shell
$desktop = [System.Environment]::GetFolderPath('Desktop')
$lnk = $shell.CreateShortcut("$desktop\F1 Helper.lnk")
$lnk.TargetPath = "$dir\start.vbs"
$lnk.WorkingDirectory = $dir
$lnk.Description = "F1 Helper Race Engineer"
$lnk.Save()
Write-Host "Shortcut created: $desktop\F1 Helper.lnk"
