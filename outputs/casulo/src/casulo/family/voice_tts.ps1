$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$taskReader = [System.IO.StreamReader]::new([Console]::OpenStandardInput(), [Text.Encoding]::UTF8)
$taskText = $taskReader.ReadToEnd()
if ($taskText.Length -lt 1 -or $taskText.Length -gt 2048) { exit 2 }
$taskSynth = [System.Speech.Synthesis.SpeechSynthesizer]::new()
$taskStream = [System.IO.MemoryStream]::new()
try {
    $taskSynth.SelectVoice('Microsoft Maria Desktop')
    $taskSynth.Rate = 0
    $taskFormat = [System.Speech.AudioFormat.SpeechAudioFormatInfo]::new(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
    $taskSynth.SetOutputToAudioStream($taskStream, $taskFormat)
    $taskSynth.Speak($taskText)
    if ($taskStream.Length -gt 1920000) { exit 3 }
    $taskOut = [Console]::OpenStandardOutput()
    $taskStream.Position = 0
    $taskStream.CopyTo($taskOut)
    $taskOut.Flush()
} finally {
    $taskSynth.Dispose()
    $taskStream.Dispose()
    $taskReader.Dispose()
}
