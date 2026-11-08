# Trusted installer prerequisite only. Never imported by the API or agents.
Set-StrictMode -Version 2.0
foreach($module in @('NativeWsl','PrivateStore','InstallFiles')){Import-Module (Join-Path $PSScriptRoot ($module+'.psm1'))}

function Get-StationWslInstallerRecipe {
    return [pscustomobject]@{Url='https://github.com/microsoft/WSL/releases/download/3.0.3/wsl.3.0.3.0.x64.msi';Bytes=[long]367575040;Sha256='ae977286974255bd26bf925f00f40f5692c6b2084155cbc0563c09aea091f211'}
}

function Assert-StationWindowsSupportAdmin {
    $principal=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    if(-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Approve the Windows permission prompt to prepare WSL. No Windows change was made.'}
}

function Test-StationModernWsl {
    try{$path=Get-StationWslExecutable}catch{
        if($_.Exception.Data['AIStationWslFailure'] -ceq 'update_required'){return $false}
        throw # Signature/path failures are not an excuse to replace a launcher.
    }
    $info=[Diagnostics.ProcessStartInfo]::new();$info.FileName=$path;$info.Arguments='--version';$info.UseShellExecute=$false;$info.CreateNoWindow=$true
    $info.RedirectStandardInput=$true;$info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true
    $process=[Diagnostics.Process]::Start($info)
    try {
        $process.StandardInput.Close();$out=$process.StandardOutput.ReadToEndAsync();$err=$process.StandardError.ReadToEndAsync()
        if(-not $process.WaitForExit(30000)){
            $process.Kill();[void]$process.WaitForExit(10000)
            throw 'The owned WSL version check did not finish. Inspect Windows support before retrying.'
        }
        $text=$out.GetAwaiter().GetResult();[void]$err.GetAwaiter().GetResult()
        if($process.ExitCode -ne 0){return $false}
        try{Assert-StationWslVersion $text;return $true}catch{return $false}
    } finally {$process.Dispose()}
}

function Receive-StationWslInstaller {
    param([string]$Path,$Recipe)
    [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
    $request=[Net.HttpWebRequest]::Create($Recipe.Url);$request.Timeout=300000;$request.ReadWriteTimeout=300000;$request.MaximumAutomaticRedirections=5
    $response=$request.GetResponse()
    try {
        if($response.ContentLength -ne -1 -and $response.ContentLength -ne $Recipe.Bytes){throw 'The Windows prerequisite length differs from its reviewed recipe.'}
        $input=$response.GetResponseStream();$output=[IO.File]::Open($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
        try {
            $buffer=[byte[]]::new(1048576);$remaining=$Recipe.Bytes
            while($remaining -gt 0){$count=$input.Read($buffer,0,[int][Math]::Min($buffer.Length,$remaining));if($count -le 0){throw 'The Windows prerequisite download was interrupted.'};$output.Write($buffer,0,$count);$remaining-=$count}
            if($input.ReadByte() -ne -1){throw 'The Windows prerequisite exceeded its reviewed size.'}
            $output.Flush($true)
        } finally {$output.Dispose();$input.Dispose()}
    } finally {$response.Dispose()}
}

function Assert-StationWslInstallerSignature {
    param([string]$Path)
    $signature=Get-AuthenticodeSignature -LiteralPath $Path -ErrorAction Stop
    if($signature.Status -ne 'Valid' -or $null -eq $signature.SignerCertificate -or $signature.SignerCertificate.Subject -notmatch '(^|,\s*)O=Microsoft Corporation(,|$)'){throw 'The Microsoft WSL installer signature could not be verified.'}
}

function Invoke-StationWindowsFeature {
    param([ValidateSet('VirtualMachinePlatform','Microsoft-Windows-Subsystem-Linux')][string]$Name)
    $exe=Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::System)) 'dism.exe'
    $process=Start-Process -FilePath $exe -ArgumentList @('/online','/enable-feature',('/featurename:'+$Name),'/all','/norestart') -Wait -PassThru
    try{if($process.ExitCode -notin @(0,3010)){throw 'Windows could not prepare its virtualization features. Saved distributions were preserved.'};return $process.ExitCode -eq 3010}finally{$process.Dispose()}
}

function Install-StationWslInstaller {
    param([string]$Path)
    $exe=Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::System)) 'msiexec.exe'
    $process=Start-Process -FilePath $exe -ArgumentList ('/i "'+$Path+'" /passive /norestart') -Wait -PassThru
    try{if($process.ExitCode -notin @(0,3010)){throw 'The Microsoft WSL installation did not finish. Existing distributions were preserved.'};return $process.ExitCode -eq 3010}finally{$process.Dispose()}
}

function New-StationWindowsSupportDirectory {
    $path=Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)) ('AIStation-WslSetup-'+[guid]::NewGuid().ToString('N'))
    Assert-StationNoReparsePath $path
    if([IO.Directory]::Exists($path) -or [IO.File]::Exists($path)){throw 'Choose a fresh private Windows setup directory.'}
    $sid=[Security.Principal.WindowsIdentity]::GetCurrent().User
    $acl=[Security.AccessControl.DirectorySecurity]::new();$acl.SetOwner($sid);$acl.SetAccessRuleProtection($true,$false)
    $inherit=[Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [Security.AccessControl.InheritanceFlags]::ObjectInherit
    foreach($identity in @($sid,[Security.Principal.SecurityIdentifier]::new('S-1-5-18'))){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($identity,[Security.AccessControl.FileSystemRights]::FullControl,$inherit,[Security.AccessControl.PropagationFlags]::None,[Security.AccessControl.AccessControlType]::Allow))}
    [void][IO.Directory]::CreateDirectory($path,$acl);Assert-StationPrivateAcl $path
    return $path
}

function Invoke-StationWindowsSupport {
    Assert-StationWindowsPreparationReady
    Assert-StationWindowsSupportAdmin
    $directory=$null;$archive=$null;$restart=$false
    try {
        $modern=Test-StationModernWsl
        if(-not $modern){
            Write-Host 'Downloading Microsoft Windows Subsystem for Linux...'
            $directory=New-StationWindowsSupportDirectory;$path=Join-Path $directory 'wsl.x64.msi';$recipe=Get-StationWslInstallerRecipe
            Receive-StationWslInstaller $path $recipe
            $archive=Open-StationVerifiedArchive $path $recipe.Sha256 $recipe.Bytes
            Assert-StationWslInstallerSignature $path
        }
        # Only these fixed OS prerequisites change, after the explicit Windows
        # consent prompt and, for a download, exact hash + Microsoft signature.
        foreach($feature in @('VirtualMachinePlatform','Microsoft-Windows-Subsystem-Linux')){if(Invoke-StationWindowsFeature $feature){$restart=$true}}
        if(-not $modern){if(Install-StationWslInstaller $path){$restart=$true}}
        return [pscustomobject]@{RestartRequired=$restart;WslInstalled=(-not $modern)}
    } finally {
        if($null -ne $archive){$archive.Stream.Dispose()}
        if($null -ne $directory){
            $file=Join-Path $directory 'wsl.x64.msi';Assert-StationNoReparsePath $file
            if([IO.File]::Exists($file)){[IO.File]::Delete($file)}
            # Never recursively remove a directory or someone else's contents.
            if(@([IO.Directory]::EnumerateFileSystemEntries($directory)).Count -eq 0){[IO.Directory]::Delete($directory)}
        }
    }
}
Export-ModuleMember -Function Invoke-StationWindowsSupport
