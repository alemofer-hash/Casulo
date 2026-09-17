Option Explicit
Dim shell, fso, releaseDir, repoDir, pyw, helper, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
releaseDir = fso.GetParentFolderName(WScript.ScriptFullName)
repoDir = fso.GetParentFolderName(fso.GetParentFolderName(releaseDir))
pyw = shell.ExpandEnvironmentStrings("%WINDIR%") & "\pyw.exe"
helper = repoDir & "\tools\human_proof_window.pyw"
If Not fso.FileExists(pyw) Or Not fso.FileExists(helper) Then
  MsgBox "Componente local ausente. Nenhum estado foi alterado.", 16, "Casulo"
  WScript.Quit 2
End If
shell.CurrentDirectory = repoDir
command = Chr(34) & pyw & Chr(34) & " " & Chr(34) & helper & Chr(34) & "  --release " & Chr(34) & releaseDir & Chr(34)
shell.Run command, 0, False
