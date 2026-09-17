Option Explicit
Dim shell, fso, scriptDir, repoRoot, pyw, helper, releaseDir, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
repoRoot = fso.GetAbsolutePathName(scriptDir & "\..\..\..")
pyw = shell.ExpandEnvironmentStrings("%WINDIR%") & "\pyw.exe"
helper = repoRoot & "\tools\monday_discovery_session.pyw"
releaseDir = repoRoot & "\release\t85-human-proof"
If shell.ExpandEnvironmentStrings("%CASULO_MONDAY_DISCOVERY_DRY_RUN%") = "1" Then
  WScript.Echo "CASULO_ARC9_VBS_PARSE_PASS"
  WScript.Quit 0
End If
If Not fso.FileExists(pyw) Or Not fso.FileExists(helper) Or Not fso.FolderExists(releaseDir) Then
  MsgBox "Componente Casulo ARC-9 ausente. O release owner nao foi alterado.", 16, "Casulo"
  WScript.Quit 2
End If
shell.CurrentDirectory = repoRoot
command = Chr(34) & pyw & Chr(34) & " " & Chr(34) & helper & Chr(34) & " --release " & Chr(34) & releaseDir & Chr(34) & " --dialogue-transport host-direct"
shell.Run command, 0, False
