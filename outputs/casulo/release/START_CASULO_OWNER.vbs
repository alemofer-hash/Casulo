Option Explicit
Dim shell, fso, releaseDir, repoDir, pyw, scriptPath, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
releaseDir = fso.GetParentFolderName(WScript.ScriptFullName)
repoDir = fso.GetParentFolderName(releaseDir)
pyw = shell.ExpandEnvironmentStrings("%WINDIR%") & "\pyw.exe"
scriptPath = repoDir & "\tools\casulo_owner_appliance.pyw"
If Not fso.FileExists(pyw) Then
  MsgBox "Python Launcher não foi localizado. Execute VERIFY_CASULO_OWNER.", 16, "Casulo"
  WScript.Quit 2
End If
If Not fso.FileExists(scriptPath) Then
  MsgBox "O launcher do Casulo não foi localizado. O estado owner não foi alterado.", 16, "Casulo"
  WScript.Quit 2
End If
shell.CurrentDirectory = repoDir
command = Chr(34) & pyw & Chr(34) & " " & Chr(34) & scriptPath & Chr(34) & " --repo " & Chr(34) & repoDir & Chr(34)
shell.Run command, 0, False
