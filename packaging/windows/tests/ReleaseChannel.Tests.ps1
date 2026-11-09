$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
Import-Module (Join-Path $PSScriptRoot '../ReleaseChannel.psm1') -Force
$fixture=[IO.File]::ReadAllText((Join-Path $PSScriptRoot 'fixtures/release-offer.json'))|ConvertFrom-Json
$raw=$fixture.raw|ConvertTo-Json -Depth 10 -Compress
$expected=$fixture.expected.fingerprint
$offer=ConvertTo-StationReleaseOffer $raw 123 '0.4.0' $expected
if($offer.Version -cne '0.5.1' -or $offer.Fingerprint -cne $expected -or $offer.Package.id -ne 456 -or $offer.Package.size_bytes -ne 1024){throw 'Shared publisher fingerprint or Windows package differs.'}
$count=1
function Reject([scriptblock]$Action){
 $rejected=$false
 try{& $Action|Out-Null}catch{$rejected=$true}
 if(-not $rejected){throw 'Unsafe release observation was accepted.'}
 $script:count++
}
foreach($version in @('0.5.1','0.6.0','00.4.0','0.4','0.4.0-rc1','65536.0.0')){
 Reject {ConvertTo-StationReleaseOffer $raw 123 $version $expected}
}
Reject {ConvertTo-StationReleaseOffer $raw 124 '0.4.0' $expected}
Reject {ConvertTo-StationReleaseOffer $raw 123 '0.4.0' ('b'*64)}
foreach($mutation in @('draft','prerelease','identity','url','asset-url','digest','size','duplicate','missing-windows','publication')){
 $value=$raw|ConvertFrom-Json
 switch($mutation){
  'draft'{$value.draft=$true}
  'prerelease'{$value.prerelease=$true}
  'identity'{$value.id=$true}
  'url'{$value.html_url='https://example.invalid/release'}
  'asset-url'{$value.assets[0].url='https://example.invalid/installer'}
  'digest'{$value.assets[0].digest='sha256:'+('b'*64)}
  'size'{$value.assets[0].size=4294967297}
  'duplicate'{$value.assets=@($value.assets)+@($value.assets[0])}
  'missing-windows'{$value.assets=@($value.assets[1])}
  'publication'{$value.published_at='2026-11-09'}
 }
 $text=$value|ConvertTo-Json -Depth 10 -Compress
 Reject {ConvertTo-StationReleaseOffer $text 123 '0.4.0' $expected}
}
$value=$raw|ConvertFrom-Json;$value.body='Edited notes do not authorize different executable bytes.'
$changed=ConvertTo-StationReleaseOffer ($value|ConvertTo-Json -Depth 10 -Compress) 123 '0.4.0' $expected
if($changed.Fingerprint -cne $expected){throw 'Release notes changed executable authority.'};$count++
"Release channel: $count assertions passed. No network or installer was run."
