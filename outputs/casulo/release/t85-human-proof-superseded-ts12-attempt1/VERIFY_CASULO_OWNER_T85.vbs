Option Explicit
Dim shell, fso, releaseDir, pyw, helper, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
releaseDir = fso.GetParentFolderName(WScript.ScriptFullName)
pyw = shell.ExpandEnvironmentStrings("%WINDIR%") & "\pyw.exe"
helper = releaseDir & "\OWNER_VM\app\tools\human_proof_control.pyw"
If shell.ExpandEnvironmentStrings("%CASULO_LAUNCHER_DRY_RUN%") = "1" Then
  WScript.Echo "CASULO_T85_VBS_PARSE_PASS"
  WScript.Quit 0
End If
If Not fso.FileExists(pyw) Or Not fso.FileExists(helper) Then
  MsgBox "Componente local ausente. Nenhum estado foi alterado.", 16, "Casulo T85"
  WScript.Quit 2
End If
shell.CurrentDirectory = releaseDir
command = Chr(34) & pyw & Chr(34) & " " & Chr(34) & helper & Chr(34) & " verify --release " & Chr(34) & releaseDir & Chr(34)
shell.Run command, 0, False
