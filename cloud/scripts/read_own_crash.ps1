$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$expectedPath=Join-Path $projectRoot 'dist/windows/项目航图-云端/项目航图-云端.exe'
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class CloudCrashDiagnostic {
public delegate bool Callback(IntPtr window,IntPtr arg);
[DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr parent,Callback callback,IntPtr arg);
[DllImport("user32.dll",CharSet=CharSet.Unicode)] public static extern IntPtr SendMessage(IntPtr window,uint message,IntPtr count,StringBuilder text);
public static void Read(IntPtr parent) { EnumChildWindows(parent,(window,arg)=>{var value=new StringBuilder(30000);SendMessage(window,0x000D,new IntPtr(value.Capacity),value);if(value.Length>0)Console.WriteLine(value.ToString());return true;},IntPtr.Zero);}
}
'@
Get-Process -Name '项目航图-云端' -ErrorAction SilentlyContinue | Where-Object Path -EQ $expectedPath | ForEach-Object {
  [CloudCrashDiagnostic]::Read($_.MainWindowHandle)
  $_.Modules | Where-Object ModuleName -Match '(?i)qt|shiboken|pyside|140|python' | Select-Object ModuleName,FileName | Format-List
}
