param([string]$Sdk='D:\Android',[string]$Java='D:\Program Files\Android\Android Studio\jbr',[switch]$Debuggable,[switch]$LeaseTestPackage)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$work=if($Debuggable){'.cache/android-debug'}else{'.cache/android'}
$buildRoot=Join-Path $projectRoot $work
$toolsRoot=Join-Path $Sdk 'build-tools/30.0.3'
$platform=Join-Path $Sdk 'platforms/android-32/android.jar'
$env:JAVA_HOME=$Java
$env:PYTHONUTF8='1'
$env:PATH="$Java\bin;$env:PATH"
New-Item -ItemType Directory -Force -Path "$buildRoot/classes","$buildRoot/dex","$projectRoot/dist" | Out-Null
function Run-Checked([string]$program,[string[]]$arguments) { & $program @arguments; if($LASTEXITCODE -ne 0){throw "构建步骤失败：$program"} }
Push-Location $projectRoot
try {
  Run-Checked 'python' @('scripts/build_assets.py')
  $manifest='android/AndroidManifest.xml'
  if($Debuggable) {
    $manifest=Join-Path $work 'AndroidManifest.xml'
    $contents=Get-Content -LiteralPath 'android/AndroidManifest.xml' -Raw
    $contents=$contents.Replace('<application ', '<application android:debuggable="true" ').Replace('android:usesCleartextTraffic="false"','android:usesCleartextTraffic="true"')
    if($LeaseTestPackage){
      $contents=$contents.Replace('package="me.jitian.projectmap"','package="me.jitian.projectmap.leaseqa"').Replace('android:name=".MainActivity"','android:name="me.jitian.projectmap.MainActivity"').Replace('android:label="项目航图"','android:label="项目航图交接测试"')
    }
    [IO.File]::WriteAllText((Join-Path $projectRoot $manifest),$contents,[Text.UTF8Encoding]::new($false))
  }
  Run-Checked "$toolsRoot/aapt2.exe" @('compile','--dir','android/res','-o',"$work/resources.zip")
  Run-Checked "$toolsRoot/aapt2.exe" @('link','-o',"$work/base.apk",'-I',$platform,'--manifest',$manifest,'-A','android/assets','--auto-add-overlay',"$work/resources.zip")
  Run-Checked 'python' @('scripts/normalize_apk.py',"$work/base.apk")
  $sources=Get-ChildItem 'android/src' -Recurse -Filter '*.java' | ForEach-Object { [IO.Path]::GetRelativePath($projectRoot,$_.FullName) }
  Run-Checked "$Java/bin/javac.exe" (@('--release','8','-encoding','UTF-8','-classpath',$platform,'-d',"$work/classes")+$sources)
  Run-Checked "$Java/bin/jar.exe" @('cf',"$work/classes.jar",'-C',"$work/classes",'.')
  if(-not(Test-Path -LiteralPath '.toolchains/r8-9.5.22.jar')){
    New-Item -ItemType Directory -Path '.toolchains' -Force | Out-Null
    Invoke-WebRequest 'https://dl.google.com/dl/android/maven2/com/android/tools/r8/9.5.22/r8-9.5.22.jar' -OutFile '.toolchains/r8-9.5.22.jar'
  }
  if((Get-FileHash '.toolchains/r8-9.5.22.jar' -Algorithm SHA256).Hash -ne 'A55B40DE220EFD4F3C252DD6239D54EF86A319FF4DCB06701084056ECFFFC308'){throw 'R8 工具链校验失败'}
  Run-Checked "$Java/bin/java.exe" @('-cp','.toolchains/r8-9.5.22.jar','com.android.tools.r8.D8','--lib',$platform,'--min-api','26','--output',"$work/dex", "$work/classes.jar")
  Copy-Item -LiteralPath "$buildRoot/base.apk" -Destination "$buildRoot/unsigned.apk" -Force
  Run-Checked "$Java/bin/jar.exe" @('uf',"$work/unsigned.apk",'-C',"$work/dex",'classes.dex')
  Run-Checked "$toolsRoot/zipalign.exe" @('-f','4',"$work/unsigned.apk", "$work/aligned.apk")
  $env:PM_SIGN_PASSWORD=(& python scripts/signing_secret.py --read).Trim()
  if($LASTEXITCODE -ne 0){throw '签名密钥初始化失败'}
  $keyStore="$projectRoot/.secrets/android-release.jks"
  if(-not(Test-Path -LiteralPath $keyStore)) {
    Run-Checked "$Java/bin/keytool.exe" @('-genkeypair','-keystore','.secrets/android-release.jks','-storepass:env','PM_SIGN_PASSWORD','-keypass:env','PM_SIGN_PASSWORD','-alias','project-map','-keyalg','RSA','-keysize','3072','-validity','10000','-dname','CN=Project Map, OU=Personal, O=Jitian, C=CN')
  }
  $output=if($Debuggable){"$work/project-map-debug.apk"}else{'dist/project-map.apk'}
  Run-Checked "$Java/bin/java.exe" @('-jar',"$toolsRoot/lib/apksigner.jar",'sign','--ks','.secrets/android-release.jks','--ks-key-alias','project-map','--ks-pass','env:PM_SIGN_PASSWORD','--key-pass','env:PM_SIGN_PASSWORD','--out',$output,"$work/aligned.apk")
  Run-Checked "$Java/bin/java.exe" @('-jar',"$toolsRoot/lib/apksigner.jar",'verify','--verbose',$output)
  if(-not $Debuggable){Copy-Item -LiteralPath 'dist/project-map.apk' -Destination 'dist/项目航图-云端.apk' -Force}
  Get-FileHash -LiteralPath (Join-Path $projectRoot $output) -Algorithm SHA256
} finally {Remove-Item Env:PM_SIGN_PASSWORD -ErrorAction SilentlyContinue;Pop-Location}
